"""Receding-horizon MPC over the 16 discrete actions — Layer 2, Phase 3.

The ODE has latent states (O2, glucose, pH) that a single blue reading can't
observe, so the controller keeps its own latent state, integrates it forward each
decision using the *actually applied* mixer level (from CleanState.mixer_level),
and nudges M toward the observed blue (a poor-man's observer). To decide, it
enumerates mixer{0..3} × glucose{0,1} × naoh{0,1}, rolls each held action forward,
and picks the one whose blue at the deadline is closest to the goal.

Trust gate: MPC is only as good as the fitted ODE. Deploy it only after
backend/sim/fit.py reports a good fit; otherwise use the heuristic controller.
"""
import json
import os

from backend.analysis.signal import clamp
from backend.control.model import ControlDecision
from backend.estimator.state_estimator import MIXER_PWM, CleanState
from backend.sim.bluebottle_ode import DEFAULT_PARAMS, STIR_LEVEL, initial_state, rk4_step
from backend.sim.fit import FITTED_PATH
from backend.sim.rollout import blue_at, rollout


def load_fitted_params() -> dict:
    """Fitted params if present (improves transfer), else hand-set defaults."""
    if os.path.exists(FITTED_PATH):
        try:
            with open(FITTED_PATH) as f:
                p = json.load(f)
            return {**DEFAULT_PARAMS, **p}
        except Exception:
            pass
    return dict(DEFAULT_PARAMS)


class MPCController:
    name = "mpc"

    def __init__(self, params: dict | None = None, horizon_s: float = 45.0,
                 dt: float = 0.5, observer_gain: float = 0.25,
                 switch_penalty: float = 0.002, goal_tol: float = 0.05,
                 glucose_penalty: float = 0.06, naoh_penalty: float = 0.15):
        self.p = params or load_fitted_params()
        self.horizon_s = horizon_s
        self.dt = dt
        self.observer_gain = observer_gain
        self.switch_penalty = switch_penalty
        # Mixing is the primary lever. Pumps add liquid volume (→ dilution/drift),
        # so they're only used when mixing alone can't get within goal_tol of the
        # target, and they carry a heavy cost (NaOH heaviest — pH rarely needs help).
        self.goal_tol = goal_tol
        self.glucose_penalty = glucose_penalty
        self.naoh_penalty = naoh_penalty
        self.reset()

    def reset(self) -> None:
        self._y = initial_state(self.p)
        self._last_t: float | None = None

    def get_params(self) -> dict:
        return {
            "mpc_horizon_s": self.horizon_s,
            "mpc_goal_tol": self.goal_tol,
            "mpc_glucose_penalty": self.glucose_penalty,
            "mpc_naoh_penalty": self.naoh_penalty,
        }

    def set_params(self, p: dict) -> None:
        if "mpc_horizon_s" in p:
            self.horizon_s = max(5.0, min(180.0, float(p["mpc_horizon_s"])))
        if "mpc_goal_tol" in p:
            self.goal_tol = max(0.0, min(0.5, float(p["mpc_goal_tol"])))
        if "mpc_glucose_penalty" in p:
            self.glucose_penalty = max(0.0, float(p["mpc_glucose_penalty"]))
        if "mpc_naoh_penalty" in p:
            self.naoh_penalty = max(0.0, float(p["mpc_naoh_penalty"]))

    # ── observer: keep the latent state synced to reality ─────────────────────
    def _observe(self, c: CleanState) -> None:
        if self._last_t is not None:
            dt_real = clamp(c.t - self._last_t, 0.0, 5.0)
            if dt_real > 0.0:
                stir = STIR_LEVEL[c.mixer_level]   # the action actually applied
                steps = max(1, int(dt_real / self.dt))
                for _ in range(steps):
                    self._y = rk4_step(self._y, dt_real / steps, stir, self.p)
        self._last_t = c.t
        # correct M from the observed (cleaned) blue: invert blue_of
        m_obs = clamp((c.blue_level - self.p["blue_offset"]) / max(self.p["blue_gain"], 1e-3),
                      0.0, 1.0)
        self._y[0] += self.observer_gain * (m_obs - self._y[0])

    # ── decision ──────────────────────────────────────────────────────────────
    def decide(self, c: CleanState) -> ControlDecision:
        self._observe(c)

        if c.goal_blue is None or c.time_remaining is None:
            # no goal: sustain — mid mixer, feed only if amplitude is collapsing
            return ControlDecision(MIXER_PWM[2], c.amplitude < 0.15 and c.cycle_event, False)

        # blue at the deadline (clamped into the horizon)
        t_target = clamp(c.time_remaining, 0.0, self.horizon_s)
        t_eval = t_target if t_target > 0 else self.horizon_s

        def predict(mixer: int, glucose: bool, naoh: bool) -> float:
            _, traj = rollout(self._y, mixer, glucose, naoh, self.p, self.horizon_s, self.dt)
            return blue_at(traj, t_eval)

        # Stage 1 — mixing is the primary lever: best mixer-only action.
        best_mix = min(
            range(4),
            key=lambda mx: (predict(mx, False, False) - c.goal_blue) ** 2
            + self.switch_penalty * (mx != c.mixer_level),
        )
        if abs(predict(best_mix, False, False) - c.goal_blue) <= self.goal_tol:
            return ControlDecision(MIXER_PWM[best_mix], False, False)  # mixing alone suffices

        # Stage 2 — mixing can't reach the goal: allow pumps, but pay for the volume.
        best_cost = None
        best_action = (best_mix, False, False)
        for mixer in range(4):
            for glucose in (False, True):
                for naoh in (False, True):
                    b = predict(mixer, glucose, naoh)
                    cost = (b - c.goal_blue) ** 2
                    cost += self.switch_penalty * (mixer != c.mixer_level)
                    cost += self.glucose_penalty * glucose + self.naoh_penalty * naoh
                    if best_cost is None or cost < best_cost:
                        best_cost, best_action = cost, (mixer, glucose, naoh)
        mixer, glucose, naoh = best_action
        return ControlDecision(MIXER_PWM[mixer], glucose, naoh)
