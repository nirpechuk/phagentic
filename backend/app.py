#!/usr/bin/env python3
"""Headless bioreactor backend entrypoint.

Loads config, wires the pieces, starts the DeviceWorker thread (owns the BLE
link + control loop), and serves the WebSocket/REST API with uvicorn. Run from
the repo root:  ``python -m backend.app``  (override port with PORT env var).
"""
import logging
import os
import threading

import uvicorn

from backend.control.arbiter import ControlArbiter
from backend.analysis.detector import Detector
from backend.hardware._hublink import config
from backend.hardware.device import DeviceWorker
from backend.hardware.roles import RoleMap
from backend.server import create_app
from backend.state.commands import CommandQueue
from backend.state.events import DeviceEvents
from backend.state.store import StateStore

LOOP_HZ = int(os.environ.get("LOOP_HZ", "20"))
HTTP_PORT = int(os.environ.get("PORT", "8080"))


def build():
    cfg = config.load_config()
    store = StateStore()
    commands = CommandQueue()
    events = DeviceEvents()
    roles = RoleMap(cfg)
    arbiter = ControlArbiter()
    detector = Detector()
    worker = DeviceWorker(cfg, store, commands, events, arbiter, detector, roles, loop_hz=LOOP_HZ)
    thread = threading.Thread(target=worker.run, name="device", daemon=True)
    thread.start()
    app = create_app(worker, store, commands, events)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = build()
    log = logging.getLogger("backend")
    log.info("Bioreactor backend → http://localhost:%d  (ws://localhost:%d/ws)", HTTP_PORT, HTTP_PORT)
    # Use the standard asyncio loop, not uvloop. uvicorn[standard] defaults to
    # uvloop; on macOS a uvloop loop on the main thread measurably slows bleak's
    # CoreBluetooth BLE connect (~5x in testing) since its callbacks land on the
    # transport's own loop thread. Our async workload is just a 15 Hz broadcast,
    # so we don't need uvloop's throughput — asyncio keeps BLE snappy.
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning", loop="asyncio")


if __name__ == "__main__":
    main()
