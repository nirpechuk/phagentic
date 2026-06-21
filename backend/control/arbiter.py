"""Mode arbitration + pump-pulse management.

One controller owns the actuators at a time:
  manual — models ignored; actuators are whatever the latest manual commands set.
  auto   — the built-in PIModel drives.
  ml     — the selected pluggable model drives.

The arbiter holds the single source of truth for desired actuator state
(``_desired``), merges each tick's model Action into it, and owns the pulse
timer so "pump stuck on" safety lives in exactly one place. Model exceptions are
caught here so a bad model never kills the loop or sticks an actuator on.
"""
import logging

from backend.control.model import Action, Model, ReactionState
from backend.control.pi_model import PIModel
from backend.control.registry import make_model
from backend.hardware.roles import DIGITAL_ROLES

log = logging.getLogger("backend.arbiter")

MODES = ("manual", "auto", "ml")


class ControlArbiter:
    def __init__(self, flip_to_manual_on_command: bool = True):
        self.mode = "manual"
        self.auto_model: Model = PIModel()
        self.ml_model: Model | None = None
        self.ml_model_name: str | None = None
        self.flip_to_manual_on_command = flip_to_manual_on_command
        # Single source of truth, applied (diffed) by the DeviceWorker each tick.
        self._desired = {"stirrer": 0, "light": 255, "glucose": 0, "naoh": 0}
        self._pulse_until: dict[str, float] = {}   # role → monotonic deadline
        self._held: dict[str, bool] = {}           # role → held-on (digital)
        self.glucose_pulses = 0
        self.last_pulse_t = None
        self.model_error = False

    # ── configuration ──────────────────────────────────────────────────────
    def active_model(self) -> Model | None:
        if self.mode == "auto":
            return self.auto_model
        if self.mode == "ml":
            return self.ml_model
        return None

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"bad mode {mode!r}")
        self.mode = mode
        self.model_error = False
        m = self.active_model()
        if m:
            m.reset()

    def set_ml_model(self, name: str) -> None:
        self.ml_model = make_model(name)
        self.ml_model_name = name
        self.model_error = False

    def set_model_params(self, params: dict) -> None:
        # Tune the active model; in manual, tune the PI baseline so it's ready.
        (self.active_model() or self.auto_model).set_params(params)

    def model_params(self) -> dict:
        return (self.active_model() or self.auto_model).get_params()

    def model_name(self) -> str:
        m = self.active_model()
        return m.name if m else "manual"

    def reset_models(self) -> None:
        self.auto_model.reset()
        if self.ml_model:
            self.ml_model.reset()
        self._pulse_until.clear()
        self.glucose_pulses = 0
        self.last_pulse_t = None

    # ── manual commands ─────────────────────────────────────────────────────
    def apply_manual(self, role: str, value) -> None:
        if role not in self._desired:
            return
        if role in DIGITAL_ROLES:
            on = bool(value)
            self._held[role] = on
            self._desired[role] = 1 if on else 0
            self._pulse_until.pop(role, None)
        else:
            self._desired[role] = int(max(0, min(255, int(value))))
        if self.flip_to_manual_on_command:
            self.mode = "manual"

    def request_pulse(self, role: str, ms: int, now: float, t: float = 0.0) -> None:
        if role in DIGITAL_ROLES:
            self._start_pulse(role, ms, now, t)

    def _start_pulse(self, role: str, ms: int, now: float, t: float) -> None:
        ms = max(50, min(5000, int(ms)))
        self._desired[role] = 1
        self._pulse_until[role] = now + ms / 1000.0
        if role == "glucose":
            self.glucose_pulses += 1
            self.last_pulse_t = round(max(0.0, t), 1)

    # ── per-tick resolution ──────────────────────────────────────────────────
    def step(self, state: ReactionState, now: float) -> tuple[dict, list]:
        notes: list = []
        model = self.active_model()
        if model is not None:
            try:
                act = model.observe(state)
                self.model_error = False
            except Exception as e:                      # never let a model kill the loop
                log.exception("model.observe failed")
                self.model_error = True
                notes.append(f"model error ({type(e).__name__}) — holding outputs")
                act = Action()                          # hold everything
            self._merge(act, now, state.t)
            notes.extend(act.notes)
        # Pulse expiry runs in every mode (incl. manual one-shots).
        for role in DIGITAL_ROLES:
            deadline = self._pulse_until.get(role)
            if deadline is None:
                continue
            if now >= deadline:
                self._pulse_until.pop(role, None)
                if not self._held.get(role):
                    self._desired[role] = 0
            else:
                self._desired[role] = 1
        return dict(self._desired), notes

    def _merge(self, act: Action, now: float, t: float) -> None:
        if act.stirrer is not None:
            self._desired["stirrer"] = int(max(0, min(255, act.stirrer)))
        if act.light is not None:
            self._desired["light"] = int(max(0, min(255, act.light)))
        if act.glucose_hold is not None:
            self._held["glucose"] = act.glucose_hold
            self._desired["glucose"] = 1 if act.glucose_hold else 0
        if act.naoh_hold is not None:
            self._held["naoh"] = act.naoh_hold
            self._desired["naoh"] = 1 if act.naoh_hold else 0
        if act.glucose_pulse_ms:
            self._start_pulse("glucose", act.glucose_pulse_ms, now, t)
        if act.naoh_pulse_ms:
            self._start_pulse("naoh", act.naoh_pulse_ms, now, t)

    # ── views for the state snapshot ─────────────────────────────────────────
    @property
    def desired(self) -> dict:
        return dict(self._desired)
