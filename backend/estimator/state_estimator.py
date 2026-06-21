"""StateEstimator — deterministic cleaner from ``ReactionState`` → ``CleanState``.

The raw blue signal is published unsmoothed (``(b-r)/200``, BLE jitter, dropouts)
and the detector's ``amp``/``period`` step at extrema. A controller fed that
directly would be brittle and would not match a simulator. So we run a light
EMA on blue, a continuous phase accumulator (advanced by ``2π·dt/period`` and
snapped to 0 at each detected trough), and a slow baseline, emitting a small,
dimensionless state. No learning — a filter has no sim-to-real gap.
"""
from dataclasses import dataclass, field
import math

from backend.analysis.signal import clamp
from backend.control.model import ReactionState

# Stirrer PWM → discrete mixer level (off/low/mid/high). Boundaries are the
# midpoints of the PWM table used by GoalModel ({0:0, 1:90, 2:160, 3:255}).
_MIXER_BOUNDS = (45, 125, 207)


def mixer_level_of(pwm: int) -> int:
    """Map a stirrer PWM 0-255 to a discrete mixer level 0..3."""
    for lvl, bound in enumerate(_MIXER_BOUNDS):
        if pwm < bound:
            return lvl
    return 3


@dataclass
class CleanState:
    """Normalized, dimensionless state handed to a controller.

    ``goal_blue`` / ``time_remaining`` are filled by the owning ``GoalModel``
    (``None`` until an operator sets a goal)."""
    t: float                      # seconds since run start (run clock)
    blue_level: float             # EMA-smoothed blue, 0..1
    baseline: float               # slow midline of the oscillation, 0..1
    amplitude: float              # smoothed peak-to-peak amplitude, 0..1
    phase_angle: float            # radians 0..2π; 0 = trough (colourless), π = peak (blue)
    phase: str                    # 'blue' | 'colorless' (passthrough)
    period: float                 # seconds; 0 until known
    period_norm: float            # period / nominal_period
    stall_risk: float             # 0..1 — time since last observed cycle / horizon
    cycle_event: bool             # passthrough: a full cycle just completed
    mixer_level: int              # 0..3, derived from last applied stirrer PWM
    mixer_onehot: tuple           # (off, low, mid, high) ∈ {0,1}
    goal_blue: float | None = None
    time_remaining: float | None = None


class StateEstimator:
    def __init__(
        self,
        blue_alpha: float = 0.35,      # EMA on blue: kills BLE jitter, negligible lag at 20 Hz
        amp_alpha: float = 0.3,
        baseline_alpha: float = 0.01,  # slow midline tracker
        nominal_period: float = 20.0,
        stall_horizon: float = 90.0,   # matches device.py stall_risk horizon
    ):
        self.blue_alpha = blue_alpha
        self.amp_alpha = amp_alpha
        self.baseline_alpha = baseline_alpha
        self.nominal_period = nominal_period
        self.stall_horizon = stall_horizon
        self.reset()

    def reset(self) -> None:
        self._blue_ema: float | None = None
        self._baseline: float | None = None
        self._amp_ema: float = 0.0
        self._phase: float = 0.0
        self._prev_t: float | None = None
        self._last_extreme_t: float | None = None

    def update(self, s: ReactionState) -> CleanState:
        # dt on the run clock; guard resets/dropouts (negative or large jumps).
        if self._prev_t is None:
            dt = 0.05
        else:
            dt = s.t - self._prev_t
            if dt <= 0.0 or dt > 2.0:
                dt = 0.05
        self._prev_t = s.t

        # EMA-smoothed blue + slow baseline (seed on first sample).
        if self._blue_ema is None:
            self._blue_ema = s.blue
            self._baseline = s.blue
            self._last_extreme_t = s.t
        else:
            self._blue_ema += self.blue_alpha * (s.blue - self._blue_ema)
            self._baseline += self.baseline_alpha * (self._blue_ema - self._baseline)

        # Amplitude EMA — only fold in real detector readings (>0).
        if s.amp > 0.0:
            self._amp_ema += self.amp_alpha * (s.amp - self._amp_ema)

        # Continuous phase: advance by the oscillator's angular rate, snap to a
        # trough on each detected cycle so it can never drift past reality.
        if s.period > 0.0:
            self._phase += (2.0 * math.pi / s.period) * dt
        if s.cycle_event:
            self._phase = 0.0
            self._last_extreme_t = s.t
        self._phase %= 2.0 * math.pi

        if self._last_extreme_t is None:
            self._last_extreme_t = s.t
        stall = clamp((s.t - self._last_extreme_t) / self.stall_horizon, 0.0, 1.0)

        level = mixer_level_of(s.last_stirrer)
        onehot = tuple(1 if i == level else 0 for i in range(4))

        return CleanState(
            t=s.t,
            blue_level=clamp(self._blue_ema, 0.0, 1.0),
            baseline=clamp(self._baseline, 0.0, 1.0),
            amplitude=clamp(self._amp_ema, 0.0, 1.0),
            phase_angle=self._phase,
            phase=s.phase,
            period=s.period,
            period_norm=(s.period / self.nominal_period) if s.period > 0 else 0.0,
            stall_risk=stall,
            cycle_event=s.cycle_event,
            mixer_level=level,
            mixer_onehot=onehot,
        )
