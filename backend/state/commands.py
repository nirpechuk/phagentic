"""Inbound commands, queued by the WebSocket layer and executed on the
DeviceWorker thread (which owns the Controller). The web layer never touches the
transport — it only enqueues.

Actuator commands collapse naturally: each only mutates the arbiter's desired
state, and the DeviceWorker diffs desired-vs-applied once per tick, so a burst
of slider events results in a single BLE write.
"""
import queue
from dataclasses import dataclass, field

# Command types handled by DeviceWorker._drain_commands.
SET_ACTUATOR = "set_actuator"      # {role, value}
PULSE_ACTUATOR = "pulse_actuator"  # {role, ms}
SET_MODE = "set_mode"              # {mode}
SET_MODEL = "set_model"            # {name}
SET_MODEL_PARAMS = "set_model_params"  # {params}
RESET_RUN = "reset_run"            # {}


@dataclass
class Command:
    type: str
    payload: dict = field(default_factory=dict)


class CommandQueue:
    def __init__(self):
        self._q: queue.Queue = queue.Queue()

    def put(self, type: str, payload: dict | None = None) -> None:
        self._q.put(Command(type, payload or {}))

    def drain(self) -> list[Command]:
        out: list[Command] = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                break
        return out
