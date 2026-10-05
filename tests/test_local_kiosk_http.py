"""Real loopback HTTP contract, independent of Firebase or attached hardware."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from test_reliability import CartState, LocalQueue
from local_kiosk import server


class LocalHTTPTests(unittest.TestCase):
    def test_origin_validation_and_durable_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = LocalQueue(Path(directory)/'cart.sqlite3')
            listener = server(journal, CartState(journal), 0)
            thread = threading.Thread(target=listener.serve_forever)
            thread.start()
            try:
                def request(method, path, data=None, origin=None):
                    connection = http.client.HTTPConnection('127.0.0.1', listener.server_port, timeout=3)
                    headers={'Content-Type':'application/json'}
                    if origin: headers['Origin']=origin
                    connection.request(method,path,json.dumps(data) if data is not None else None,headers)
                    response=connection.getresponse(); body=response.read(); connection.close()
                    return response.status, body
                self.assertEqual(request('GET','/')[0],200)
                data={'id':'1234567890','name':'Pit','brand':'Test','purchaseDate':'2025-01-01'}
                self.assertEqual(request('POST','/api/enroll',data,'https://attacker.invalid')[0],403)
                self.assertEqual(journal.size(),0)
                status,body=request('POST','/api/enroll',data)
                self.assertEqual(status,200); self.assertTrue(json.loads(body)['savedLocally'])
                self.assertEqual(journal.records('enrollments')['1234567890']['name'],'Pit')
                self.assertEqual(journal.size(),1)
            finally:
                listener.shutdown(); listener.server_close(); thread.join(); journal.close()
