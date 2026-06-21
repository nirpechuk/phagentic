"""Oscillation analysis — extrema detection on the blue signal.

Direct port of frontend/logic.js detect() (:186-199) plus the bits of resetProc
that seed its state. Feed one (t, blue) sample per tick; reads amplitude,
half-period, period, cycle count and phase off the stream of peaks/troughs.
"""
from dataclasses import dataclass

from backend.analysis.signal import clamp


@dataclass
class Reading:
    """One detector output. ``cycle_event`` is True only on the tick a new full
    cycle completes (a trough), so a controller can act once per cycle."""
    blue: float
    amp: float
    half_period: float
    period: float
    cycles: int
    phase: str            # 'blue' | 'colorless'
    cycle_event: bool
    last_extreme_t: float


class Detector:
    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._prev_blue = 0.5
        self._dir = 0                 # current slope sign: -1, 0, +1
        self._last_max = 0.5
        self._last_min = 0.5
        self._ext_t: list[float] = []  # times of recent extrema (window of 6)
        self.amp = 0.0
        self.period = 0.0
        self.half_period = 0.0
        self.cycles = 0
        self.phase = "colorless"
        self.last_extreme_t = 0.0

    def update(self, t: float, blue: float) -> Reading:
        cycle_event = False
        self.phase = "blue" if blue >= 0.5 else "colorless"
        d = blue - self._prev_blue
        nd = 1 if d > 1e-3 else (-1 if d < -1e-3 else self._dir)
        if self._dir == 0:
            self._dir = nd
        elif nd != 0 and nd != self._dir:
            kind = "max" if self._dir > 0 else "min"
            if kind == "max":
                self._last_max = self._prev_blue
            else:
                self._last_min = self._prev_blue
            self.amp = clamp(self._last_max - self._last_min, 0.0, 1.0)
            if self._ext_t:
                self.half_period = t - self._ext_t[-1]
                if len(self._ext_t) >= 2:
                    self.period = t - self._ext_t[-2]
                if kind == "min":
                    self.cycles += 1
                    cycle_event = True
            self._ext_t.append(t)
            if len(self._ext_t) > 6:
                self._ext_t.pop(0)
            self.last_extreme_t = t
            self._dir = nd
        self._prev_blue = blue
        return Reading(
            blue=blue, amp=self.amp, half_period=self.half_period,
            period=self.period, cycles=self.cycles, phase=self.phase,
            cycle_event=cycle_event, last_extreme_t=self.last_extreme_t,
        )
