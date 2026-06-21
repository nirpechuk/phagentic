"""FastAPI app: a state-broadcasting WebSocket + one REST route for the layout.

The asyncio side never blocks on the device: inbound frames are validated and
pushed onto the command queue / event flags, and a single broadcast task fans
the latest StateStore snapshot out to all connected clients. The few blocking
operations (recalibrate, reload) set an event and await its 'done' flag in a
thread-pool so the event loop stays responsive.
"""
import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.protocol import messages as M
from backend.state.commands import (
    CommandQueue, PULSE_ACTUATOR, RESET_RUN, SET_ACTUATOR, SET_MODE,
    SET_MODEL, SET_MODEL_PARAMS,
)
from backend.state.events import DeviceEvents
from backend.state.store import StateStore

log = logging.getLogger("backend.server")

BROADCAST_HZ = 15


def create_app(worker, store: StateStore, commands: CommandQueue, events: DeviceEvents) -> FastAPI:
    clients: set[WebSocket] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(_broadcast_loop(store, clients))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            # Drive actuators safe on the device thread, then let it exit.
            events.shutdown_req.set()
            await asyncio.get_event_loop().run_in_executor(None, events.shutdown_done.wait, 5.0)

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/config")
    def config_route():
        return JSONResponse(worker.layout())

    @app.get("/")
    def index():
        return JSONResponse({"service": "bioreactor-backend", "ws": "/ws", "config": "/config"})

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        clients.add(ws)
        with contextlib.suppress(Exception):
            await ws.send_text(json.dumps({"type": M.S_CONFIG, **worker.layout()}))
            await ws.send_text(json.dumps({"type": M.S_STATE, **store.snapshot(), "narr_new": []}))
        try:
            while True:
                raw = await ws.receive_text()
                await _handle_inbound(ws, raw, worker, commands, events)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.warning("ws error", exc_info=True)
        finally:
            clients.discard(ws)

    return app


async def _broadcast_loop(store: StateStore, clients: set[WebSocket]) -> None:
    interval = 1.0 / BROADCAST_HZ
    while True:
        await asyncio.sleep(interval)
        if not clients:
            store.drain_narr()   # don't let narration pile up with nobody listening
            continue
        snap = store.snapshot()
        narr = store.drain_narr()
        data = json.dumps({"type": M.S_STATE, **snap, "narr_new": narr})
        for ws in list(clients):
            try:
                await ws.send_text(data)
            except Exception:
                clients.discard(ws)


async def _ack(ws: WebSocket, ref, ok: bool, msg: str = "") -> None:
    with contextlib.suppress(Exception):
        await ws.send_text(json.dumps({"type": M.S_ACK, "ref": ref, "ok": ok, "msg": msg}))


async def _handle_inbound(ws, raw, worker, commands: CommandQueue, events: DeviceEvents) -> None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return await _ack(ws, None, False, "bad json")
    typ = msg.get("type")
    ref = msg.get("ref")

    if typ == M.C_SET_ACTUATOR:
        if msg.get("role") not in M.VALID_ROLES:
            return await _ack(ws, ref, False, "bad role")
        commands.put(SET_ACTUATOR, {"role": msg["role"], "value": msg.get("value")})
        return await _ack(ws, ref, True)

    if typ == M.C_PULSE_ACTUATOR:
        if msg.get("role") not in M.VALID_ROLES:
            return await _ack(ws, ref, False, "bad role")
        commands.put(PULSE_ACTUATOR, {"role": msg["role"], "ms": int(msg.get("ms", 500))})
        return await _ack(ws, ref, True)

    if typ == M.C_SET_MODE:
        if msg.get("mode") not in M.VALID_MODES:
            return await _ack(ws, ref, False, "bad mode")
        commands.put(SET_MODE, {"mode": msg["mode"]})
        return await _ack(ws, ref, True)

    if typ == M.C_SET_MODEL:
        commands.put(SET_MODEL, {"name": msg.get("name")})
        return await _ack(ws, ref, True)

    if typ == M.C_SET_MODEL_PARAMS:
        commands.put(SET_MODEL_PARAMS, {"params": msg.get("params", {})})
        return await _ack(ws, ref, True)

    if typ == M.C_RESET_RUN:
        commands.put(RESET_RUN, {})
        return await _ack(ws, ref, True)

    if typ == M.C_RECALIBRATE:
        events.recalib_done.clear()
        events.recalib_req.set()
        ok = await asyncio.get_event_loop().run_in_executor(None, events.recalib_done.wait, 15.0)
        with contextlib.suppress(Exception):
            await ws.send_text(json.dumps({
                "type": M.S_CALIBRATION,
                "status": "ok" if ok else "timeout",
                "wb": list(events.wb), "white_c": events.white_c,
            }))
        return await _ack(ws, ref, ok, "" if ok else "timeout")

    if typ == M.C_RELOAD_CONFIG:
        events.reload_done.clear()
        events.reload_req.set()
        ok = await asyncio.get_event_loop().run_in_executor(None, events.reload_done.wait, 5.0)
        with contextlib.suppress(Exception):
            await ws.send_text(json.dumps({"type": M.S_CONFIG, **worker.layout()}))
        return await _ack(ws, ref, ok, "" if ok else "timeout")

    if typ == M.C_PING:
        return await _ack(ws, ref, True, "pong")

    return await _ack(ws, ref, False, f"unknown type {typ!r}")
