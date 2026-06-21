"""Oscillation analysis — robust extrema detection on the blue signal.

Feed one ``(t, blue)`` sample per tick; reads amplitude, half-period, period,
cycle count and phase off the stream of peaks/troughs.

Robustness (this is what every period controller ultimately regulates on):
  * **Hysteresis** — an extreme is only confirmed once the signal retraces by a
    fraction of the current amplitude (floored by an absolute deadband) from the
    running peak/trough, so sensor jitter near a peak can't manufacture spurious
    extrema.
  * **Median window** — half-period / period are the *median* of the last few
    inter-extreme spacings, so a single mistimed extreme doesn't spike the
    estimate. ``period`` is reported as ``2 × half_period`` for consistency.
"""
from dataclasses import dataclass
from statistics import median

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
    def __init__(self, hysteresis_frac: float = 0.15, min_deadband: float = 0.06,
                 blue_alpha: float = 0.2):
        # Confirm an extreme after the signal retraces by max(min_deadband,
        # hysteresis_frac · amplitude) from the running peak/trough. ``blue_alpha``
        # is a light EMA applied before peak-finding so sensor noise (the raw blue
        # is unsmoothed) can't cross the deadband — its lag hits peaks and troughs
        # equally, so it does not bias the period.
        self.hysteresis_frac = hysteresis_frac
        self.min_deadband = min_deadband
        self.blue_alpha = blue_alpha
        self.reset()

    def reset(self) -> None:
        self._blue_ema: float | None = None
        self._seeking = 0            # +1 looking for a max, -1 for a min, 0 = undecided
        self._run_max = self._run_max_t = None   # running peak candidate (value, time)
        self._run_min = self._run_min_t = None   # running trough candidate
        self._last_max = 0.5
        self._last_min = 0.5
        self._ext_t: list[float] = []  # times of recent confirmed extrema (window of 6)
        self.amp = 0.0
        self.period = 0.0
        self.half_period = 0.0
        self.cycles = 0
        self.phase = "colorless"
        self.last_extreme_t = 0.0

    def _deadband(self) -> float:
        return max(self.min_deadband, self.hysteresis_frac * self.amp)

    def update(self, t: float, raw_blue: float) -> Reading:
        cycle_event = False
        # De-noise before peak-finding; detect on the smoothed value.
        if self._blue_ema is None:
            self._blue_ema = raw_blue
        else:
            self._blue_ema += self.blue_alpha * (raw_blue - self._blue_ema)
        blue = self._blue_ema
        self.phase = "blue" if blue >= 0.5 else "colorless"

        if self._run_max is None:                # first sample seeds both trackers
            self._run_max = self._run_min = blue
            self._run_max_t = self._run_min_t = t
            return self._reading(raw_blue, cycle_event)

        # Track the running extreme(s) for whichever direction(s) are in play.
        if self._seeking >= 0 and blue > self._run_max:
            self._run_max, self._run_max_t = blue, t
        if self._seeking <= 0 and blue < self._run_min:
            self._run_min, self._run_min_t = blue, t

        band = self._deadband()
        if self._seeking >= 0 and blue <= self._run_max - band:
            # fell far enough below the running peak → confirm a maximum
            cycle_event = self._confirm("max", self._run_max, self._run_max_t)
            self._seeking = -1
            self._run_min, self._run_min_t = blue, t
        elif self._seeking <= 0 and blue >= self._run_min + band:
            # rose far enough above the running trough → confirm a minimum
            cycle_event = self._confirm("min", self._run_min, self._run_min_t)
            self._seeking = 1
            self._run_max, self._run_max_t = blue, t

        return self._reading(raw_blue, cycle_event)

    def _confirm(self, kind: str, value: float, t: float) -> bool:
        """Record a confirmed peak/trough; recompute amp + median timings."""
        if kind == "max":
            self._last_max = value
        else:
            self._last_min = value
        self.amp = clamp(self._last_max - self._last_min, 0.0, 1.0)

        cycle_event = False
        if self._ext_t:
            spacings = [b - a for a, b in zip(self._ext_t, self._ext_t[1:])]
            spacings.append(t - self._ext_t[-1])
            self.half_period = median(spacings)
            self.period = 2.0 * self.half_period
            if kind == "min":               # a full blue→colourless→blue cycle closed
                self.cycles += 1
                cycle_event = True
        self._ext_t.append(t)
        if len(self._ext_t) > 6:
            self._ext_t.pop(0)
        self.last_extreme_t = t
        return cycle_event

    def _reading(self, blue: float, cycle_event: bool) -> Reading:
        return Reading(
            blue=blue,
            amp=self.amp, half_period=self.half_period, period=self.period,
            cycles=self.cycles, phase=self.phase, cycle_event=cycle_event,
            last_extreme_t=self.last_extreme_t,
        )
