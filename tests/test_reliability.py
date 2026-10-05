"""Network-free regression coverage for cart history, scoring, and telemetry artifacts."""
import copy
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import threading
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'MachineA_BatteryCart'), str(ROOT / 'MachineC_OffsiteCompute')]
sys.path.insert(0, str(ROOT / 'Shared'))
from migrate_legacy_cycles import plan as migration_plan
from wal import LocalQueue
from cart_state import CartState, pick_next
from input_listener import SerialWorker, RFIDReader, led_loop
from battery_scoring.config import load_config, CURRENT_VERSION, validate_config
from battery_scoring.models import PullMeasurement, Battery
from battery_scoring.match_score import compute_match_score
from battery_scoring.health_score import _trend_change_pct, compute_health_score
from battery_scoring.firebase_store import parse_records, completed_cycles
from battery_scoring.engine import recompute_battery, recompute_all
from dslogtocsvlibrary.entry.pdp_ctre_data import PdpCtreData
from dslogtocsvlibrary.entry.metadata import Metadata
from dslogtocsvlibrary.entry.log_entry import LogEntry
from dslogtocsvlibrary.entry.event_entry import EventEntry
from dslogtocsvlibrary.dslogstream import DsLogStream
from dslogtocsvlibrary.dseventstream import DsEventStream
from DSConverter import convert_file
from filter_csv import process_csv
from artifacts import safe_path, digest
from drive_sync import list_new_files
from main import Pipeline
from parser import event_records
from FirebaseScraper import heartbeat_online


class Clock:
    def __init__(self): self.t = 1_791_200_000.0
    def now(self): return self.t
    def advance(self, seconds): self.t += seconds


class Reference:
    def __init__(self, data=None, path='', write=None):
        self.data = data if data is not None else {}
        self.path, self.write = path, write
        self.key = path.rsplit('/',1)[-1]
    def child(self, path): return Reference(self.data, '/'.join(filter(None,[self.path,path])), self.write)
    def get(self):
        value = self.data
        for key in self.path.split('/') if self.path else []:
            value = value.get(key) if isinstance(value,dict) else None
        return copy.deepcopy(value)
    def update(self, patch_data):
        if self.write: self.write(self.path, patch_data)
        for key,value in patch_data.items():
            node=self.data
            parts='/'.join(filter(None,[self.path,key])).split('/')
            for part in parts[:-1]: node=node.setdefault(part,{})
            if value is None: node.pop(parts[-1],None)
            elif isinstance(value,dict) and value.get('.sv') == {'increment':1}:
                node[parts[-1]]=node.get(parts[-1],0)+1
            else: node[parts[-1]]=copy.deepcopy(value)
    def set(self, value):
        if self.write: self.write(self.path,value)
        self.child('..') if False else None
        parts=self.path.split('/'); node=self.data
        for part in parts[:-1]: node=node.setdefault(part,{})
        node[parts[-1]]=copy.deepcopy(value)
    def order_by_child(self, key): return self
    def transaction(self, callback):
        value = callback(self.get())
        self.set(value)
        return value
    def equal_to(self, value): return self
    def push(self): return self.child('snapshot')


class ReliabilityTests(unittest.TestCase):
    def test_cba_csv_dry_plan_deduplicates_and_rejects_invalid_rows(self):
        from import_cba_csv import plan
        path=self.root/'cba.csv'
        row='1234567890,2026-10-05T12:00:00Z,17,2026,bench test\n'
        path.write_text('battery_id,timestamp,capacity_ah,season,notes\n'+row+row)
        updates=plan(path)
        self.assertEqual(len(updates),1)
        record=next(iter(updates.values()))
        self.assertEqual(record['capacityAh'],17)
        self.assertEqual(len(record['source']['sha256']),64)
        path.write_text(path.read_text()+row.replace(',17,',',NaN,'))
        with self.assertRaises(ValueError): plan(path)

    def test_local_kiosk_offline_enroll_pull_restart(self):
        from local_kiosk import KioskStore
        kiosk = KioskStore(self.q, self.state)
        self.insert()
        self.assertEqual(kiosk.snapshot()['enrollmentRequests'], ['1234567890'])
        kiosk.enroll({'id':'1234567890','name':'Pit A','brand':'Test','purchaseDate':'2025-01-01'})
        self.state.presence(0, False); self.clock.advance(4); self.state.tick()
        identity = next(iter(kiosk.snapshot()['pullRequests']))
        request = {'kind':'pull','id':identity,'batteryId':'1234567890','currentVoltage':12.7}
        saved = kiosk.observation(request)
        self.assertIsNone(saved['socPercent'])
        size = self.q.size()
        self.assertEqual(kiosk.observation({**request,'currentVoltage':11}), saved)
        self.assertEqual(self.q.size(), size)
        other = LocalQueue(self.root/'cart.sqlite3')
        try:
            self.assertEqual(KioskStore(other,self.state).snapshot()['pullRequests'], {})
            self.assertEqual(other.records('pull_measurements')[identity]['currentVoltage'],12.7)
        finally: other.close()
        remote=Reference(); self.q.process(remote)
        self.assertEqual(self.q.size(),0)
        self.assertEqual(remote.data['Cycles'][identity]['pullMeasurementId'],identity)
        self.assertEqual(remote.data['PullMeasurements']['1234567890'][identity]['currentVoltage'],12.7)

    def test_local_kiosk_validation_cba_and_conflict(self):
        from local_kiosk import KioskStore
        kiosk=KioskStore(self.q,self.state)
        for purchased in ('2025-02-30','2999-01-01'):
            with self.assertRaises(ValueError): kiosk.enroll({'id':'1234567890','name':'A','brand':'B','purchaseDate':purchased})
        kiosk.enroll({'id':'1234567890','name':'A','brand':'B','purchaseDate':'2025-01-01'})
        data={'id':'testA','kind':'cba','batteryId':'1234567890','capacityAh':17,'season':'2026'}
        for capacity in (True,float('nan'),0,101):
            with self.assertRaises(ValueError): kiosk.observation({**data,'capacityAh':capacity})
        kiosk.observation(data)
        remote=Reference({'CBATests':{'1234567890':{'testA':{'capacityAh':15,'season':'2026'}}}})
        self.q.process(remote)
        self.assertEqual(self.q.size(),0)
        self.assertEqual(self.q.records('cba_tests')['testA']['capacityAh'],17)
        self.assertEqual(self.q.records('conflicts')['testA']['serverRecord']['capacityAh'],15)

    def test_local_kiosk_remote_receipt_reconciliation(self):
        from local_kiosk import KioskStore
        self.q.put_record('pull_requests','cycle',{'batteryId':'1234567890'})
        root=Reference({'Cycles':{'cycle':{'pullMeasurementId':'correction'}},'PullMeasurements':{'1234567890':{'correction':{'cycleId':'cycle','currentVoltage':12.5}}}})
        KioskStore(self.q,self.state).reconcile(root)
        self.assertEqual(self.q.pending_pulls(),{})
        self.assertEqual(self.q.records('pull_measurements')['cycle']['currentVoltage'],12.5)

    def test_local_observation_repairs_ack_retry_without_overwriting_correction(self):
        record={'cycleId':'cycle','currentVoltage':12.7,'timestamp':'2026-10-05T12:00:00Z'}
        root=Reference({'Cycles':{'cycle':{'pullMeasurementId':'corrected'}}})
        value={'id':'cycle','batteryId':'1234567890','kind':'pull','path':'PullMeasurements/1234567890/cycle','record':record}
        self.q.upload_observation(root,value); self.q.upload_observation(root,value)
        self.assertEqual(root.data['Cycles']['cycle']['pullMeasurementId'],'corrected')
        self.assertEqual(len(root.data['PullMeasurements']['1234567890']),1)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.clock=Clock()
        self.q=LocalQueue(self.root/'cart.sqlite3'); self.addCleanup(self.q.close)
        self.state=CartState(self.q,wall=self.clock.now,monotonic=self.clock.now)
        self.config=load_config(CURRENT_VERSION)
        self.now=datetime(2026,10,5,tzinfo=timezone.utc)
    def insert(self, slot=0, tag='1234567890'):
        self.state.presence(slot,False,snapshot=True)
        self.state.scan(tag); self.state.presence(slot,True)
        self.clock.advance(1.1); self.state.tick()
    def test_outbox_concurrent_enqueue_survives(self):
        self.q.enqueue('one',{'v':1})
        self.q.process(Reference(write=lambda *_: self.q.enqueue('two',{'v':2})))
        self.assertEqual(self.q.size(),1)
    def test_outbox_failed_old_write_blocks_new(self):
        self.q.enqueue('b',{'charging':True}); self.q.enqueue('b',{'charging':False})
        def fail(*_): raise OSError('offline')
        self.q.process(Reference(write=fail)); self.assertEqual(self.q.size(),2)
        ref=Reference(); self.q.process(ref); self.assertFalse(ref.data['b']['charging'])
    def test_outbox_restart_persistence(self):
        self.q.enqueue('b',{'v':1}); other=LocalQueue(self.root/'cart.sqlite3')
        try: self.assertEqual(other.size(),1)
        finally: other.close()
    def test_unclean_process_exit_retains_outbox(self):
        target=self.root/'crash.sqlite3'
        code='import sys,os; sys.path.insert(0,sys.argv[1]); from wal import LocalQueue; q=LocalQueue(sys.argv[2]); [q.enqueue("b",{"n":n}) for n in range(10)]; os._exit(0)'
        subprocess.run([sys.executable,'-c',code,str(ROOT/'MachineA_BatteryCart'),str(target)],check=True)
        recovered=LocalQueue(target)
        try: self.assertEqual(recovered.size(),10)
        finally: recovered.close()
    def test_disk_full_fails_visibly_and_rolls_back_state(self):
        current=self.q.connection.execute('PRAGMA page_count').fetchone()[0]
        self.q.connection.execute(f'PRAGMA max_page_count={current+1}')
        with self.assertRaises(sqlite3.OperationalError):
            with self.q.transaction():
                self.q.set_state('session','new')
                self.q.enqueue('b',{'payload':'x'*100000})
        self.assertIsNone(self.q.get_state('session'))
        self.assertEqual(self.q.size(),0)
    def test_corrupt_sqlite_is_not_silently_reinitialized(self):
        source=self.root/'corrupt.sqlite3'; source.write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError): LocalQueue(source)
        self.assertEqual(source.read_bytes(),b'not a database')
    def test_serial_reader_reopens_after_unplug(self):
        stop=threading.Event(); opened=[]
        class Port:
            def __init__(self,broken):
                self.broken=broken
                self.lines=[b'BEGIN 1 V2\n',b'LAYOUT 7 60\n']+[f'SLOT_{i}:REMOVED\n'.encode() for i in range(6)]+[b'END 1\n']
            def write(self,value): return len(value)
            def read_until(self,*args,**kwargs):
                if self.broken: raise OSError('unplug')
                if self.lines: return self.lines.pop(0)
                stop.set(); return b''
            def close(self): pass
        def factory(*args,**kwargs): opened.append(True); return Port(len(opened)==1)
        worker=SerialWorker('fake',1,self.state,stop,serial_factory=factory)
        # Retry wait is shortened only in the fake, while real state/timeouts still execute.
        original=stop.wait
        stop.wait=lambda timeout=None: original(0)
        worker.run(); self.assertEqual(len(opened),2); self.assertIsNone(worker.port)
    def test_outbox_invalid_operation_visible(self):
        with self.assertRaises(ValueError): self.q.enqueue('b',{},'invalid')
    def test_outbox_state_event_rollback_together(self):
        with self.assertRaises(ValueError):
            with self.q.transaction():
                self.q.set_state('session',True); self.q.enqueue('b',{'v':float('nan')})
        self.assertIsNone(self.q.get_state('session')); self.assertEqual(self.q.size(),0)
    def test_corrupt_legacy_preserved(self):
        legacy=self.root/'bad.json'; legacy.write_text('[bad')
        with self.assertRaises(ValueError): LocalQueue(legacy)
        self.assertEqual(legacy.read_text(),'[bad')
    def test_legacy_import_once(self):
        legacy=self.root/'legacy.json'; legacy.write_text(json.dumps([{'path':'b','data':{'v':1}}]))
        q=LocalQueue(legacy); q.close(); q=LocalQueue(legacy)
        try: self.assertEqual(q.size(),1)
        finally: q.close()
    def test_coalescing_bounds_ephemeral_status(self):
        for n in range(1000): self.q.enqueue('status',{'n':n},coalesce_key='heartbeat')
        self.assertEqual(self.q.size(),1)
        self.assertEqual(self.q.get_queue_contents()[0]['data']['n'],999)
    def test_fast_offline_pull_creates_cycle(self):
        self.insert(); self.state.presence(0,False); self.clock.advance(3.1); self.state.tick()
        self.assertEqual(self.q.size(),2)
        remote=Reference(); self.q.process(remote)
        self.assertEqual(len(remote.data['Cycles']),1)
        self.assertEqual(len(remote.data['PullRequests']),1)
        self.assertFalse(remote.data['BatteryList']['1234567890']['IsCharging'])
    def test_flicker_preserves_start_and_cycle(self):
        self.insert(); old=dict(self.state.sessions['0'])
        self.state.presence(0,False); self.clock.advance(1); self.state.presence(0,True)
        self.clock.advance(5); self.state.tick()
        self.assertEqual(self.state.sessions['0']['id'],old['id'])
        self.assertEqual(self.state.sessions['0']['start'],old['start'])
        self.assertEqual(self.q.size(),1)
    def test_restart_during_grace_finishes_same_session(self):
        self.insert(); identity=self.state.sessions['0']['id']; self.state.presence(0,False)
        state=CartState(self.q,wall=self.clock.now,monotonic=self.clock.now)
        self.clock.advance(20); state.presence(0,False,snapshot=True); self.clock.advance(3.1); state.tick()
        remote=Reference(); self.q.process(remote); self.assertIn(identity,remote.data['Cycles'])
    def test_startup_occupied_is_unknown_identity(self):
        self.state.presence(0,True,snapshot=True); self.state.scan('1234567890')
        self.clock.advance(2); self.state.tick(); self.assertFalse(self.state.sessions)
    def test_simultaneous_inserts_do_not_guess(self):
        self.state.scan('1234567890'); self.state.scan('1234567891')
        self.state.presence(0,True); self.state.presence(1,True); self.clock.advance(1.1); self.state.tick()
        self.assertFalse(self.state.sessions)
    def test_duplicate_tag_not_assigned_twice(self):
        self.insert(); self.assertFalse(self.state.scan('1234567890'))
        self.state.presence(1,True); self.clock.advance(1.1); self.state.tick()
        self.assertEqual(len(self.state.sessions),1)
    def test_unmatched_scans_expire_and_are_bounded(self):
        for i in range(100): self.state.scan(f'{i:010d}')
        self.assertLessEqual(len(self.state.scans),32); self.clock.advance(4); self.state.tick()
        self.assertFalse(self.state.scans)
    def test_removed_slot_not_matched_after_wait(self):
        self.state.scan('1234567890'); self.state.presence(0,True); self.state.presence(0,False)
        self.clock.advance(2); self.state.tick(); self.assertFalse(self.state.sessions)
    def test_disconnect_not_invented_removal(self):
        self.insert(); self.state.disconnect(1); self.clock.advance(20); self.state.tick()
        self.assertIn('0',self.state.sessions); self.assertIsNone(self.state.occupancy[0])
    def test_restart_occupied_session_requires_reverification(self):
        self.insert()
        state=CartState(self.q,wall=self.clock.now,monotonic=self.clock.now)
        state.presence(0,True,snapshot=True)
        self.assertFalse(state.snapshot()[0]['session']['verified'])
        state.scan('1234567890')
        self.assertTrue(state.snapshot()[0]['session']['verified'])
    def test_replay_preserves_kiosk_acknowledgment(self):
        self.insert(); self.state.presence(0,False); self.clock.advance(3.1); self.state.tick()
        ref=Reference(); items=self.q.get_queue_contents()
        for item in items: ref.update(item['data'])
        identity=next(iter(ref.data['Cycles']))
        ref.update({f'Cycles/{identity}/pullMeasurementId':'measurement',f'PullRequests/{identity}/submittedAt':'timestamp'})
        for item in items: ref.update(item['data'])
        self.assertEqual(ref.data['Cycles'][identity]['pullMeasurementId'],'measurement')
        self.assertEqual(ref.data['PullRequests'][identity]['submittedAt'],'timestamp')
    def test_different_tag_within_grace_is_new_session(self):
        self.insert(); old=self.state.sessions['0']['id']
        self.state.presence(0,False); self.state.scan('1234567891'); self.clock.advance(.5)
        self.state.presence(0,True); self.clock.advance(1.1); self.state.tick()
        self.assertNotEqual(self.state.sessions['0']['id'],old)
        self.state.presence(0,False); self.clock.advance(3.1); self.state.tick()
        ref=Reference(); self.q.process(ref); self.assertEqual(len(ref.data['Cycles']),2)
    def test_led_worker_sends_commands_without_stalling_state_tick(self):
        class Stop:
            calls=0
            def wait(self, _): self.calls+=1; return self.calls>1
        class Port:
            generation=1; healthy=True
            def __init__(self): self.commands=[]
            def command(self, command): self.commands.append(command); return True
        from types import SimpleNamespace
        ports=[Port(),Port()]
        led_loop(self.state,ports,SimpleNamespace(connected=1),Stop(),
                 {'lock':threading.Lock(),'fetched':0,'metadata':None,'settings':None})
        self.assertEqual(len(ports[0].commands),7)
    def test_board_snapshot_requires_all_six_and_ownership(self):
        worker=SerialWorker('fake',1,self.state,threading.Event())
        worker.consume('BEGIN 1 V2'); worker.consume('SLOT_0:PRESENT')
        with self.assertRaises(ValueError): worker.consume('END 1')
        with self.assertRaises(ValueError): worker.consume('SLOT_6:PRESENT')
        worker.consume('BEGIN 1 V2')
        worker.consume('LAYOUT 7 60')
        for i in range(6): worker.consume(f'SLOT_{i}:REMOVED')
        worker.consume('END 1'); self.assertTrue(worker.synchronized)
    def test_presence_mask_repairs_dropped_removal(self):
        self.insert(); worker=SerialWorker('fake',1,self.state,threading.Event())
        worker.synchronized=True
        worker.consume('PONG 0')
        self.clock.advance(3.1); self.state.tick()
        ref=Reference(); self.q.process(ref)
        self.assertEqual(len(ref.data['Cycles']),1)
        self.assertTrue(next(iter(ref.data['Cycles'].values()))['endTimeEstimated'])
    def test_immediate_ack_survives(self):
        worker=SerialWorker('fake',1,self.state,threading.Event())
        worker.send=lambda command: (worker.consume('ACK '+command.split()[1]) or True)
        self.assertTrue(worker.command('SEG 0 POS 3 COLOR 0 MODE SOLID',timeout=0))
    def test_late_ack_does_not_ack_another_command(self):
        worker=SerialWorker('fake',1,self.state,threading.Event())
        worker.send=lambda _: (worker.consume('ACK aaaaaaaaaaaa') or True)
        self.assertFalse(worker.command('SEG 0 POS 3 COLOR 0 MODE SOLID',timeout=0))
    def test_rfid_requires_explicit_devices(self):
        with self.assertRaises(ValueError): RFIDReader([],self.state,threading.Event())
    def test_recommendation_conservative(self):
        self.insert(); slots=self.state.snapshot()
        metadata={'1234567890':{'id':'1234567890','name':'Blue','brand':'MK','purchaseDate':'2026-01-01','cache':{'latestMatchScore':90,'latestMatchConfidence':.45,'latestVoltageAt':datetime.fromtimestamp(self.clock.now(),timezone.utc).isoformat()}}}
        self.assertEqual(pick_next(slots,metadata,{'minTime':0},self.clock.now()),0)
        self.assertIsNone(pick_next(slots,metadata,{},self.clock.now()))
        metadata['1234567890']['retirementDate']='2026-10-01'
        self.assertIsNone(pick_next(slots,metadata,{'minTime':0},self.clock.now()))
    def test_stale_score_never_recommended(self):
        self.insert(); metadata={'1234567890':{'cache':{'latestMatchScore':100,'latestMatchConfidence':1,'latestVoltageAt':'2020-01-01T00:00:00Z'}}}
        self.assertIsNone(pick_next(self.state.snapshot(),metadata,{'minTime':0},self.clock.now()))
    def test_score_validation_and_optional_zero(self):
        for value in (-1,float('nan'),float('inf'),True,'12.5'):
            with self.assertRaises(ValueError): PullMeasurement.from_dict('m','b',{'currentVoltage':value})
        m=PullMeasurement.from_dict('m','b',{'currentVoltage':12.9,'socPercent':0,'timestamp':self.now.isoformat()})
        self.assertEqual(m.soc_percent,0)
    def test_undated_voltage_is_not_fresh(self):
        m=PullMeasurement.from_dict('m','b',{'currentVoltage':12.9})
        self.assertEqual(compute_match_score(m,self.config,self.now).confidence,0)
    def test_voltage_only_score_not_penalized(self):
        result=compute_match_score(PullMeasurement('m','b',self.now,12.9),self.config,self.now)
        self.assertEqual(result.score,100); self.assertEqual(result.confidence,.45)
    def test_optional_history_has_individual_freshness(self):
        recent=PullMeasurement('recent','b',self.now,12.9)
        history=[PullMeasurement('old','b',self.now-timedelta(hours=1),12.5,internal_resistance_milliohm=25),recent]
        result=compute_match_score(recent,self.config,self.now,history=history)
        self.assertLess(result.score,100)
        history[0].timestamp=self.now-timedelta(days=5)
        result=compute_match_score(recent,self.config,self.now,history=history)
        self.assertEqual(result.score,100)
    def test_stale_and_future_confidence(self):
        for timestamp in (self.now-timedelta(days=4),self.now+timedelta(hours=1)):
            self.assertEqual(compute_match_score(PullMeasurement('m','b',timestamp,12.9),self.config,self.now).confidence,0)
    def test_independent_health_windows(self):
        self.assertIsNone(_trend_change_pct([8,10,14,20,25],3,3,6))
        self.assertGreater(_trend_change_pct([8,8,8,25,25,25],3,3,6),100)
        self.assertEqual(_trend_change_pct([8]*6,3,3,6),0)
    def test_invalid_records_do_not_hide_valid_history(self):
        records,warnings=parse_records({'bad':{'currentVoltage':-1},'valid':{'currentVoltage':12.5,'timestamp':self.now.isoformat()}},'b',PullMeasurement,self.now)
        self.assertEqual(len(records),1); self.assertEqual(len(warnings),1)
    def test_only_completed_cycles_count(self):
        self.assertEqual(len(completed_cycles({'open':{'batteryId':'b'},'done':{'endTime':'2026-10-05T00:00:00Z'},'void':{'endTime':'2026-10-05','voided':True}})),1)
    def test_invalid_config_refused(self):
        config=copy.deepcopy(self.config); config['match_score']['weights']['voltage']=-1
        with self.assertRaises(ValueError): validate_config(config)
    def test_atomic_scores_include_all_inputs_and_counts(self):
        source={'Batteries':{'b':{'id':'b','name':'B','brand':'MK','purchaseDate':'2026-01-01'}},
                'PullMeasurements':{'b':{'m':{'currentVoltage':12.9,'timestamp':self.now.isoformat()}}},
                'Cycles':{'c':{'batteryId':'b','endTime':self.now.isoformat(),'season':'2026'}}}
        writes=[]; ref=Reference(source,write=lambda p,v: writes.append((p,v)))
        snapshot,cache=recompute_battery(ref,'b',self.config,self.now)
        self.assertEqual(len(writes),1); self.assertEqual(writes[0][0],'')
        self.assertEqual(snapshot['inputRefs']['measurementIds'],['m'])
        self.assertEqual(cache['seasonCycleCount'],{'2026':1})
        self.assertEqual(cache['totalCycleCount'],1)
    def test_deleting_voltage_clears_stale_cache(self):
        ref=Reference({'Batteries':{'b':{'id':'b','cache':{'latestMatchScore':100}}}})
        _,cache=recompute_battery(ref,'b',self.config,self.now)
        self.assertIsNone(cache['latestMatchScore']); self.assertEqual(cache['latestMatchConfidence'],0)
    def test_lease_loss_refuses_publication(self):
        ref=Reference({'Batteries':{'b':{'id':'b'}}})
        with self.assertRaises(RuntimeError): recompute_battery(ref,'b',self.config,self.now,before_publish=lambda:False)
    def test_input_cache_refreshes_on_revision_without_repeated_history_downloads(self):
        source={'Batteries':{'b':{'id':'b'}},'ScoringRevisions':{'b':1}}
        cache={}; ref=Reference(source)
        recompute_all(ref,self.config,input_cache=cache)
        first=cache['b']['inputs']
        recompute_all(ref,self.config,input_cache=cache)
        self.assertIs(cache['b']['inputs'],first)
        source['ScoringRevisions']['b']=2
        recompute_all(ref,self.config,input_cache=cache)
        self.assertIsNot(cache['b']['inputs'],first)
    def test_legacy_migration_is_additive_and_idempotent(self):
        exported={'BatteryList':{'1234567890':{'ChargingRecords':[{'StartTime':'2026-01-01 12:00:00','EndTime':'2026-01-01 13:00:00'}]}}}
        patch,warnings=migration_plan(exported)
        self.assertTrue(warnings); self.assertFalse(patch)
        patch,warnings=migration_plan(exported,'America/Chicago')
        self.assertFalse(warnings); self.assertTrue(patch)
        ref=Reference(copy.deepcopy(exported)); ref.update(patch)
        repeated,_=migration_plan(ref.data,'America/Chicago'); self.assertFalse(repeated)
        self.assertEqual(ref.data['BatteryList'],exported['BatteryList'])
    def test_stale_heartbeat_does_not_mean_removed(self):
        self.assertTrue(heartbeat_online(self.now.isoformat(),self.now))
        self.assertFalse(heartbeat_online((self.now-timedelta(seconds=31)).isoformat(),self.now))
        self.assertFalse(heartbeat_online('invalid',self.now))
    def test_ctre_exact_packed_currents(self):
        packed=sum(8 << (54-10*i) for i in range(6)); third=sum(8 << (54-10*i) for i in range(4))
        tail=list((third>>24).to_bytes(5,'big'))+[0,170,25]
        data=struct.pack(PdpCtreData.byte_code,0,packed,packed,*tail)
        self.assertEqual(PdpCtreData.from_bytes(data).currents,[1.0]*16)
    def log_bytes(self):
        return struct.pack(Metadata.byte_code,4,3_800_000_000,0)+struct.pack(LogEntry.byte_code,0,0,3200,0,0,0,0,0,0)+b'\x00\x00\x00'
    def test_truncated_ds_record_rejected(self):
        data=self.log_bytes()
        for trim in (1,2,3,4):
            with self.assertRaises(ValueError): list(DsLogStream(io.BytesIO(data[:-trim])))
        self.assertEqual(len(list(DsLogStream(io.BytesIO(data)))),1)
    def test_incomplete_conversion_preserves_existing_output(self):
        source=self.root/'log.dslog'; output=self.root/'raw.csv'
        source.write_bytes(self.log_bytes()[:-1]); output.write_text('old-good')
        with self.assertRaises(ValueError): convert_file(source,output)
        self.assertEqual(output.read_text(),'old-good')
    def test_filter_preserves_raw_and_missing_current(self):
        source=self.root/'raw.csv'; output=self.root/'derived.csv'
        source.write_text('date,voltage,pdp_data_currents\nnow,12.5,"[1, 2]"\nlater,255.6,\n')
        before=source.read_bytes(); process_csv(source,output)
        self.assertEqual(source.read_bytes(),before)
        with output.open() as f: rows=list(csv.DictReader(f))
        self.assertEqual(float(rows[0]['total_current']),3)
        self.assertEqual(rows[1]['total_current'],''); self.assertIn('invalid_voltage',rows[1]['quality_flags'])
        other=self.root/'again.csv'; process_csv(output,other)
        with other.open() as f: again=list(csv.DictReader(f))
        self.assertEqual(float(again[0]['total_current']),3)
    def test_filter_refuses_inplace_destruction(self):
        with self.assertRaises(ValueError): process_csv(self.root/'raw.csv',self.root/'raw.csv')
    def test_safe_paths_refuse_traversal_absolute_and_symlinks(self):
        for name in ('../x.dslog','/tmp/x.dslog','..','a/b.dslog','a\\b.dslog'):
            with self.assertRaises(ValueError): safe_path(self.root,name)
        (self.root/'link').symlink_to('/tmp')
        with self.assertRaises(ValueError): safe_path(self.root,'link')
    def test_drive_pagination(self):
        class Service:
            def __init__(self): self.calls=0
            def files(self): return self
            def list(self,**kwargs): self.calls+=1; return self
            def execute(self,**kwargs):
                return {'files':[{'id':str(self.calls),'name':f'{self.calls}.dslog'}],**({'nextPageToken':'next'} if self.calls==1 else {})}
        self.assertEqual(len(list_new_files(Service(),'folder')),2)
    def test_ingestion_failed_copy_retries_and_preserves_raw(self):
        storage=self.root/'store'; storage.mkdir(); pipe=Pipeline(self.root/'stage',storage)
        self.addCleanup(pipe.close); file={'id':'a','name':'same.dslog','modifiedTime':'today'}
        def download(service,identity,dest,metadata=None): Path(dest).write_bytes(self.log_bytes())
        with patch('main.download_file',download), patch('main.copy_verified',side_effect=OSError('unmounted')):
            with self.assertRaises(OSError): pipe.process(None,file)
        self.assertEqual(pipe.db.execute('SELECT status FROM files').fetchone()[0],'pending')
        with patch('main.download_file',download): identity=pipe.process(None,file)
        self.assertEqual(pipe.db.execute('SELECT status FROM files').fetchone()[0],'complete')
        self.assertTrue((storage/(identity+'.dslog')).is_file())
    def test_binary_events_exact_tag_and_last_character(self):
        message=b'<TagVersion>1 <Message>Battery ID: 1234567890'
        raw=struct.pack(Metadata.byte_code,4,3_800_000_000,0)+struct.pack(EventEntry.byte_code,3_800_000_000,0,len(message))+message
        source=self.root/'events.dsevents'; source.write_bytes(raw)
        records=list(event_records(source)); self.assertEqual(records[0]['battery_id'],'1234567890')
        self.assertTrue(records[0]['message'].endswith('0'))
        with self.assertRaises(ValueError): list(DsEventStream(io.BytesIO(raw[:-1])))


if __name__=='__main__': unittest.main()
