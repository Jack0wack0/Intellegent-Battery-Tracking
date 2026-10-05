"""Synthetic, offline collector for manual/native Chromium acceptance. Never uses credentials."""
import os
from pathlib import Path
import tempfile
from test_reliability import CartState, Clock, LocalQueue
from local_kiosk import server

with tempfile.TemporaryDirectory() as directory:
    journal = LocalQueue(Path(directory)/'cart.sqlite3')
    clock = Clock()
    state = CartState(journal, wall=clock.now, monotonic=clock.now)
    state.presence(0, False, snapshot=True)
    state.scan('1234567890'); state.presence(0, True)
    clock.advance(1.1); state.tick()
    state.presence(0, False); clock.advance(4); state.tick()
    listener = server(journal, state, int(os.environ.get('KIOSK_PORT', '8765')))
    try: listener.serve_forever()
    finally: listener.server_close(); journal.close()
