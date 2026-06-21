"""Relay + PID amplitude driver — oscillate between a peak blue and colourless.

The stirrer is an *asymmetric* actuator: more O2 pushes blue UP (oxidise), but
nothing actively pulls it DOWN — reduction is passive (stir off → O2 depletes →
glucose reduces methylene blue → colourless). A controller tracking a single
setpoint therefore just parks there; it never cycles. To oscillate we run a
**relay** between two setpoints, with a PID shaping the active (rising) stroke:

    rising   — PID drives the stirrer so blue climbs to ``target_amplitude``;
               when reached, flip to falling.
    falling  — stirrer OFF; blue decays passively; when it drops to
               ``low_threshold`` (≈ colourless), flip back to rising.

Amplitude is held by the relay thresholds. The **period is emergent** — the
falling stroke runs at the reaction's own (slow) reduction rate, so the cadence
is whatever the chemistry allows, not a free parameter. ``max_half_s`` is a safety
flip so a stroke that can't reach its threshold (target unreachable / decay
stalled) can't wedge the relay. Glucose/NaOH only rescue a collapsing reaction.
"""
from backend.analysis.signal import clamp
from backend.control.model import ControlDecision
from backend.estimator.state_estimator import CleanState


class AmplitudeController:
    name = "amplitude"

    def __init__(self):
        self.target_amplitude = 0.7    # peak blue level to rise to (0..1)
        self.low_threshold = 0.1       # 'colourless' level to fall to before rising again
        self.reach_tol = 0.03          # flip the relay within this of the active setpoint
                                       # (the PID asymptotes to target, so strict
                                       #  equality would never trip the flip)
        # PID on blue error (0..1) → stirrer PWM (0..255); blue swings are small so
        # the proportional gain is large. Ki removes the steady offset so the rise
        # actually reaches the target; Kd off by default (noisy on a colour signal).
        self.kp = 600.0
        self.ki = 60.0
        self.kd = 0.0
        self.i_clamp = 150.0
        self.drive_low = 0             # stirrer PWM during the (passive) fall
        self.max_half_s = 120.0        # safety: force a relay flip after this long in a stroke
        # rescue gates (shared semantics with the hue heuristic)
        self.amp_floor = 0.15
        self.naoh_stall_thresh = 0.8
        self.reset()

    def reset(self) -> None:
        self._rising = True
        self._i = 0.0
        self._last_err = 0.0
        self._last_t: float | None = None
        self._phase_t0: float | None = None

    # ── params (merged flat into GoalModel.get_params) ────────────────────────
    def get_params(self) -> dict:
        return {
            "target_amplitude": self.target_amplitude,
            "low_threshold": self.low_threshold,
            "reach_tol": self.reach_tol,
            "amp_kp": self.kp,
            "amp_ki": self.ki,
            "amp_kd": self.kd,
            "drive_low": self.drive_low,
            "max_half_s": self.max_half_s,
            "amp_floor": self.amp_floor,
            "naoh_stall_thresh": self.naoh_stall_thresh,
            "rising": self._rising,
        }

    def set_params(self, p: dict) -> None:
        if "target_amplitude" in p:
            self.target_amplitude = clamp(float(p["target_amplitude"]), 0.05, 1.0)
        if "low_threshold" in p:
            self.low_threshold = clamp(float(p["low_threshold"]), 0.0, 0.9)
        if "reach_tol" in p:
            self.reach_tol = clamp(float(p["reach_tol"]), 0.0, 0.3)
        if "amp_kp" in p:
            self.kp = max(0.0, float(p["amp_kp"]))
        if "amp_ki" in p:
            self.ki = max(0.0, float(p["amp_ki"]))
        if "amp_kd" in p:
            self.kd = max(0.0, float(p["amp_kd"]))
        if "drive_low" in p:
            self.drive_low = int(max(0, min(255, int(p["drive_low"]))))
        if "max_half_s" in p:
            self.max_half_s = max(5.0, min(600.0, float(p["max_half_s"])))
        if "amp_floor" in p:
            self.amp_floor = clamp(float(p["amp_floor"]), 0.0, 0.9)
        if "naoh_stall_thresh" in p:
            self.naoh_stall_thresh = clamp(float(p["naoh_stall_thresh"]), 0.0, 1.0)
        # keep thresholds sane relative to each other
        if self.low_threshold >= self.target_amplitude:
            self.low_threshold = max(0.0, self.target_amplitude - 0.05)

    # ── decision ──────────────────────────────────────────────────────────────
    def decide(self, c: CleanState) -> ControlDecision:
        blue = c.blue_level                      # estimator-smoothed (robust to jitter)
        if self._phase_t0 is None:
            self._phase_t0 = c.t
        dt = 0.5 if self._last_t is None else clamp(c.t - self._last_t, 1e-3, 5.0)
        self._last_t = c.t
        elapsed = c.t - self._phase_t0
        timed_out = elapsed >= self.max_half_s

        glucose = c.amplitude < self.amp_floor and c.cycle_event
        naoh = c.stall_risk > self.naoh_stall_thresh and c.cycle_event

        if self._rising:
            err = self.target_amplitude - blue
            self._i = clamp(self._i + self.ki * err * dt, -self.i_clamp, self.i_clamp)
            deriv = self.kd * (err - self._last_err) / dt
            self._last_err = err
            raw = self.kp * err + self._i + deriv
            out = clamp(raw, 0.0, 255.0)
            if raw != out:                       # back-calculation anti-windup
                self._i = clamp(self._i - (raw - out), -self.i_clamp, self.i_clamp)
            if blue >= self.target_amplitude - self.reach_tol or timed_out:
                self._enter_falling(c.t)
            return ControlDecision(round(out), glucose, naoh)

        # falling: passive decay toward colourless
        if blue <= self.low_threshold + self.reach_tol or timed_out:
            self._enter_rising(c.t)
        return ControlDecision(self.drive_low, glucose, naoh)

    def _enter_falling(self, t: float) -> None:
        self._rising = False
        self._phase_t0 = t
        self._i = 0.0
        self._last_err = 0.0

    def _enter_rising(self, t: float) -> None:
        self._rising = True
        self._phase_t0 = t
        self._i = 0.0
        self._last_err = 0.0
