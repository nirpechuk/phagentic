"""The pluggable control-model interface.

A Model observes the derived reaction state and emits an Action — desired
actuator setpoints and/or pump-pulse intents. The baseline PIModel lives in
pi_model.py; real models (sklearn / torch / an RL policy) implement the same
contract and register themselves in registry.py. The analysis layer produces
ReactionState independently of which model is active, so models are swappable
without touching the rest of the loop.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import NamedTuple


class ControlDecision(NamedTuple):
    """What a GoalModel *controller* returns each decision tick.

    The actuator is a continuous PWM, so controllers speak PWM directly:
    discrete-mixer controllers (hue heuristic, MPC) emit one of the four
    ``MIXER_PWM`` values; the period controller emits a continuous level."""
    stirrer: int           # stirrer PWM 0..255
    glucose: bool          # request a glucose rescue pulse this tick
    naoh: bool             # request a NaOH (pH) pulse this tick


@dataclass(frozen=True)
class ReactionState:
    """Everything a model may observe. Mode-independent, built each tick from
    the sensor reading + Detector output."""
    t: float                      # seconds since run start
    now: float                    # monotonic clock (for pulse timing)
    blue: float                   # 0..1
    rgb: tuple                    # white-balanced (r, g, b), 0-255
    lux: int                      # raw clear channel
    amp: float
    half_period: float
    period: float
    cycles: int
    phase: str                    # 'blue' | 'colorless'
    cycle_event: bool             # True on the tick a cycle completed
    last_stirrer: int             # last stirrer PWM applied
    last_light: int               # last sensor-light PWM applied


@dataclass
class Action:
    """A model's desired effect. ``None`` for a field means 'leave as-is' so a
    model that only drives the stirrer need not know about pumps. Pulses are
    intents (ms) — the arbiter owns the timer that turns the pump back off."""
    stirrer: int | None = None             # PWM 0..255
    light: int | None = None               # PWM 0..255
    glucose_pulse_ms: int | None = None
    naoh_pulse_ms: int | None = None
    glucose_hold: bool | None = None       # held on/off (overrides pulses)
    naoh_hold: bool | None = None
    notes: list = field(default_factory=list)  # narration strings → streamed to UI


class Model(ABC):
    name: str = "base"

    @abstractmethod
    def observe(self, state: ReactionState) -> Action:
        ...

    def get_params(self) -> dict:
        """Current tunable params — sent to the UI so it can render controls."""
        return {}

    def set_params(self, params: dict) -> None:
        """Apply param changes from the UI. Validate/clamp here."""
        pass

    def reset(self) -> None:
        """Called on run reset / mode (re)entry. Clear integrators, history, etc."""
        pass
