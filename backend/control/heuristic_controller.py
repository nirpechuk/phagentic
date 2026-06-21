"""Phase-aware heuristic scheduler — Layer 2, Phase 2 (no dependencies).

Consumes only ``CleanState`` (the firewall), so it has no sim-to-real gap. It
treats the objective as scheduling on a known oscillator: from the cleaned
phase/period/amplitude it predicts where ``goal_blue`` will be crossed and nudges
the mixer to land that crossing on the deadline. Glucose feeds the reaction when
amplitude decays; NaOH supports pH only when the oscillation is clearly stalling.

Chemistry intuition: stirring → dissolved O2 → oxidises leuco-MB to blue (and
speeds the cycle); glucose is the reductant reservoir (drives colourless,
sustains amplitude); NaOH sets pH. Higher mixer ⇒ faster phase advance + bluer.
"""
import math

from backend.estimator.state_estimator import CleanState


def _wrap_pi(x: float) -> float:
    """Wrap an angle to (-π, π]."""
    return (x + math.pi) % (2.0 * math.pi) - math.pi


class HeuristicScheduler:
    name = "heuristic"

    def __init__(self):
        # Mixing is the primary lever. Glucose/NaOH add liquid volume (→ drift),
        # so they fire ONLY to rescue a genuinely dying oscillation, never for
        # routine hue/timing steering.
        self.amp_floor = 0.15          # below this the reaction is collapsing → feed glucose
        self.band_margin = 0.05        # goal this far outside the band ⇒ amplitude/baseline problem
        self.naoh_stall_thresh = 0.8   # only support pH when clearly stalled
        # phase-correction → mixer bands (correction > 0 means "advance faster")
        self.fast_thresh = 0.25
        self.slow_thresh = -0.25

    # ── params (merged flat into GoalModel.get_params) ────────────────────────
    def get_params(self) -> dict:
        return {
            "amp_floor": self.amp_floor,
            "band_margin": self.band_margin,
            "naoh_stall_thresh": self.naoh_stall_thresh,
        }

    def set_params(self, p: dict) -> None:
        if "amp_floor" in p:
            self.amp_floor = max(0.0, min(0.9, float(p["amp_floor"])))
        if "band_margin" in p:
            self.band_margin = max(0.0, min(0.5, float(p["band_margin"])))
        if "naoh_stall_thresh" in p:
            self.naoh_stall_thresh = max(0.0, min(1.0, float(p["naoh_stall_thresh"])))

    def reset(self) -> None:
        pass  # stateless

    # ── decision ──────────────────────────────────────────────────────────────
    def decide(self, c: CleanState) -> tuple[int, bool, bool]:
        """Return (mixer_level 0..3, glucose_pulse?, naoh_pulse?)."""
        if c.goal_blue is None or c.time_remaining is None:
            return self._sustain(c)

        amp = max(c.amplitude, 1e-3)
        lo, hi = c.baseline - amp / 2.0, c.baseline + amp / 2.0
        # glucose is allowed ONLY when the oscillation is actually collapsing
        dying = c.amplitude < self.amp_floor and c.cycle_event

        # Goal outside the current oscillation band → reach for it with O2 first
        # (mixing is the lever); only feed glucose if amplitude is also collapsing.
        if c.goal_blue > hi + self.band_margin:
            return 3, dying, self._naoh(c)              # bluer: max O2 (+ fuel only if dying)
        if c.goal_blue < lo - self.band_margin:
            return 0, dying, self._naoh(c)              # more colourless: cut O2 (+ fuel only if dying)

        # Goal inside the band → pure timing. Find the phase that yields goal_blue
        # (blue(φ) = baseline − (amp/2)·cos φ) and steer to hit it at the deadline.
        x = max(-1.0, min(1.0, 2.0 * (c.baseline - c.goal_blue) / amp))
        phi_star = math.acos(x)                          # rising and falling crossings: φ*, 2π−φ*

        if c.period <= 0.0:
            # not oscillating yet: drive mid, seed fuel if stalling
            return 2, c.stall_risk > 0.3, self._naoh(c)

        omega = 2.0 * math.pi / c.period
        phi_deadline = c.phase_angle + omega * max(c.time_remaining, 0.0)
        # nearest target crossing in phase
        best_dphi = None
        for target in (phi_star, 2.0 * math.pi - phi_star):
            dphi = _wrap_pi(target - phi_deadline)
            if best_dphi is None or abs(dphi) < abs(best_dphi):
                best_dphi = dphi

        # Normalize by the phase we can still influence over the remaining time.
        span = max(omega * max(c.time_remaining, c.period), 1e-3)
        correction = best_dphi / span                    # >0 behind (speed up), <0 ahead (slow down)
        mixer = self._mixer_from_correction(correction)

        # timing is handled purely by mixing; glucose only if the reaction is dying
        return mixer, dying, self._naoh(c)

    # ── helpers ─────────────────────────────────────────────────────────────--
    def _sustain(self, c: CleanState) -> tuple[int, bool, bool]:
        """No goal set: hold a healthy oscillation (mirrors the PI baseline)."""
        glucose = (c.amplitude < self.amp_floor and c.cycle_event) or c.stall_risk > 0.6
        return 2, glucose, self._naoh(c)

    def _mixer_from_correction(self, x: float) -> int:
        if x >= self.fast_thresh:
            return 3
        if x >= 0.0:
            return 2
        if x >= self.slow_thresh:
            return 1
        return 0

    def _naoh(self, c: CleanState) -> bool:
        # Conservative pH support: only when clearly stalling, gated to one per cycle.
        return c.stall_risk > self.naoh_stall_thresh and c.cycle_event
