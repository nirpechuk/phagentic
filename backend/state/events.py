"""Request/done event pairs for blocking operations the DeviceWorker must run
between ticks (it owns the Controller). Same pattern as hub/dashboard.py:30-33.

The web layer sets a ``*_req`` event and (optionally) waits on the matching
``*_done`` in a thread-pool so the asyncio loop never blocks.
"""
import threading


class DeviceEvents:
    def __init__(self):
        self.recalib_req = threading.Event()
        self.recalib_done = threading.Event()
        self.reload_req = threading.Event()
        self.reload_done = threading.Event()
        self.shutdown_req = threading.Event()
        self.shutdown_done = threading.Event()
        # Last calibration result, published for the recalibrate ack.
        self.wb = (1.0, 1.0, 1.0)
        self.white_c = 1.0
