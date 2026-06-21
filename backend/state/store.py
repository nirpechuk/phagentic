"""Thread-safe shared state between the DeviceWorker (writer) and the WebSocket
broadcast task (reader).

The DeviceWorker calls ``update(**fields)`` each tick and ``push_narr`` for
narration. The single broadcast loop calls ``snapshot`` and ``drain_narr``. A
plain lock-guarded dict is plenty at 20 Hz and keeps the contract obvious.
"""
import threading


class StateStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict = {
            "t": 0.0, "blue": 0.5, "rgb": [228, 226, 214], "lux": 0,
            "amp": 0.0, "period": 0.0, "half_period": 0.0, "phase": "colorless",
            "blue_est": 0.5, "amp_est": 0.0, "baseline_est": 0.5, "phase_est": "colorless",
            "cycles": 0, "stall_risk": 0.0,
            "stirrer_out": 0, "light_out": 255,
            "glucose_active": False, "naoh_active": False,
            "glucose_pulses": 0, "last_pulse_t": None,
            "mode": "manual", "model_name": "manual", "model_params": {},
            "models": [], "ble": "disconnected", "model_error": False,
        }
        self._narr: list[dict] = []   # buffered narration, drained by broadcaster

    def update(self, **fields) -> None:
        with self._lock:
            self._state.update(fields)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def push_narr(self, txt: str, kind: str = "info") -> None:
        with self._lock:
            self._narr.append({"txt": txt, "kind": kind})
            if len(self._narr) > 200:
                self._narr = self._narr[-200:]

    def drain_narr(self) -> list[dict]:
        with self._lock:
            out, self._narr = self._narr, []
            return out
