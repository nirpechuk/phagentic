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
from backend.control.amplitude_controller import AmplitudeController
from backend.control.model import ControlDecision
from backend.estimator.state_estimator import MIXER_PWM, CleanState
from backend.sim.bluebottle_ode import DEFAULT_PARAMS, STIR_LEVEL, initial_state, rk4_step
from backend.sim.fit import FIT_WINDOW_S, FITTED_PATH, simulate
from backend.sim.rollout import blue_at, rollout

# Reaction-rate constants the online learner tracks within a session: k_ox (sets
# the rise rate / blue ceiling under stir) and k_red (the passive fall rate). These
# are the two most identifiable, roughly-orthogonal levers from on/off data and the
# ones that drift as the reaction weakens. k_aer/k_cons (the fast, barely-observable
# O2 transient) and the sensor map are deliberately NOT adapted — including more
# correlated, weakly-observed params just makes closed-loop identification wander.
ONLINE_ADAPT_KEYS = ("k_ox", "k_red")


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


class MPCAmplitudeController(AmplitudeController):
    """Oscillate blue between a target peak and ~colourless, with the *rising*
    stroke planned by the fitted grey-box ODE instead of a PID.

    Reuses ``AmplitudeController``'s relay verbatim — the two-stroke state machine,
    the ``target_amplitude``/``low_threshold`` flips, the safety timeout, and the
    glucose stall-rescue on the (passive) fall. Only the rise changes: rather than
    a PID chasing the blue error, it keeps a latent ODE state (synced to the
    observed blue each tick, like ``MPCController``), rolls every discrete mixer
    level forward over a short horizon, and holds the level whose predicted blue
    lands closest to ``target_amplitude`` — so the climb hits the target peak as
    accurately as the model allows, then the relay cuts the stirrer and lets it
    fade. The ODE has no limit cycle; the relay supplies the oscillation, the model
    supplies the aim. (Falls back to the inherited PID rise if the ODE is missing.)

    **Online learning** (``online_learn``, **on by default** — set false to stop):
    it buffers the recent observed-blue / applied-mixer history and, every ``online_period_s``,
    runs a light coordinate-descent refit of the drift-prone rate constants
    (``ONLINE_ADAPT_KEYS``) on that window — the same horizon objective as the
    offline fitter. Guarded so it can't run away: only the fast rates adapt (sensor
    map fixed), each stays within ``online_band`` of the offline baseline, updates
    are EMA-smoothed, adaptation is skipped on poorly-exciting windows, and the
    params revert toward baseline whenever they'd predict the window worse than it.
    This tracks within-session weakening hands-off; ``make fit`` remains the way to
    re-anchor the baseline across sessions.
    """
    name = "mpc"

    def __init__(self, params: dict | None = None, horizon_s: float = 30.0,
                 dt: float = 0.5, observer_gain: float = 0.25,
                 switch_penalty: float = 0.002):
        self.p = params or load_fitted_params()
        # The offline-fitted (or default) params — the trusted anchor. Online
        # adaptation is bounded to a band around this and reverts to it if it ever
        # predicts worse, so a bad window can't walk the model away permanently.
        self._baseline_p = dict(self.p)
        self.horizon_s = horizon_s
        self.dt = dt
        self.observer_gain = observer_gain
        self.switch_penalty = switch_penalty
        # ── online learning (ON by default for MPC — adapts the ODE live so the
        # oscillator works without an offline fit; the guardrails below keep it safe
        # even from the hand-set defaults baseline). Set online_learn:false to stop. ─
        self.online_learn = True       # live parameter tracking
        self.online_rate = 0.3         # EMA step toward the local fit each adapt
        self.online_window_s = 90.0    # rolling history used for each refit
        self.online_period_s = 30.0    # min seconds between refits
        self.online_band = 0.4         # adapted keys stay within ±this of baseline
        self.online_min_span = 0.12    # need this much blue variation to adapt
        super().__init__()   # sets relay/PID params and calls self.reset()

    def reset(self) -> None:
        super().reset()
        self._y = initial_state(self.p)
        self._obs_t: float | None = None
        # online-learning buffer of recent (t, observed-blue, applied-mixer); the
        # learned params persist across a run reset (same chemical batch), only the
        # rolling history clears.
        self._buf: list = []
        self._last_adapt_t = -1e9

    def get_params(self) -> dict:
        p = super().get_params()
        p["mpc_horizon_s"] = self.horizon_s
        p["online_learn"] = self.online_learn
        p["online_rate"] = self.online_rate
        # live (possibly-adapted) rate constants, so drift is visible in telemetry
        for k in ONLINE_ADAPT_KEYS:
            p[k] = round(self.p[k], 5)
        return p

    def set_params(self, p: dict) -> None:
        super().set_params(p)
        if "mpc_horizon_s" in p:
            self.horizon_s = max(5.0, min(180.0, float(p["mpc_horizon_s"])))
        if "online_learn" in p:
            self.online_learn = bool(p["online_learn"])
        if "online_rate" in p:
            self.online_rate = clamp(float(p["online_rate"]), 0.0, 1.0)
        if "online_window_s" in p:
            self.online_window_s = max(20.0, min(600.0, float(p["online_window_s"])))
        if "online_period_s" in p:
            self.online_period_s = max(5.0, min(300.0, float(p["online_period_s"])))

    def decide(self, c: CleanState) -> ControlDecision:
        self._record(c)
        self._maybe_adapt(c.t)
        return super().decide(c)     # relay + model-planned rise, using self.p

    # ── online learning: guarded sliding-window refit ──────────────────────────
    def _record(self, c: CleanState) -> None:
        self._buf.append((c.t, c.blue_level, c.mixer_level))
        cutoff = c.t - self.online_window_s
        while self._buf and self._buf[0][0] < cutoff:
            self._buf.pop(0)

    def _clamp_key(self, k: str, v: float) -> float:
        base = self._baseline_p[k]
        return clamp(v, base * (1.0 - self.online_band), base * (1.0 + self.online_band))

    def _window_sse(self, p: dict, frames: list, obs: list) -> float:
        # Same windowed objective as the offline fitter: re-sync M to the observed
        # blue every FIT_WINDOW_S, score horizon prediction (pumps treated as off —
        # they're rare rescues, and reseeding absorbs the unmodelled kick).
        pred = simulate(frames, p, reseed_s=FIT_WINDOW_S, obs=obs)
        return sum((a - b) ** 2 for a, b in zip(pred, obs))

    def _maybe_adapt(self, t: float) -> None:
        if not self.online_learn or (t - self._last_adapt_t) < self.online_period_s:
            return
        if len(self._buf) < 30:
            return
        obs = [b for _, b, _ in self._buf]
        mixers = {m for _, _, m in self._buf}
        # excitation guard: a flat or single-action window can't identify the rates,
        # so adapting on it would just chase noise. Require real swing AND both a
        # driven (stir-on) and a passive (stir-off) phase — the harness provides both.
        if (max(obs) - min(obs)) < self.online_min_span \
                or not (any(m >= 1 for m in mixers) and 0 in mixers):
            self._last_adapt_t = t
            return
        self._last_adapt_t = t

        frames = [{"t": bt, "blue": bb, "mixer": bm, "glucose_edge": False, "naoh_edge": False}
                  for bt, bb, bm in self._buf]
        # light coordinate descent from the current params toward this window
        cur = dict(self.p)
        best = self._window_sse(cur, frames, obs)
        for k in ONLINE_ADAPT_KEYS:
            for f in (0.85, 0.93, 1.07, 1.18):
                trial = dict(cur)
                trial[k] = self._clamp_key(k, cur[k] * f)
                s = self._window_sse(trial, frames, obs)
                if s < best:
                    best, cur = s, trial
        # safety revert: never keep params that predict this window worse than the
        # trusted baseline — fall the adapted keys back toward baseline instead.
        if best > self._window_sse(self._baseline_p, frames, obs):
            cur = {**cur, **{k: self._baseline_p[k] for k in ONLINE_ADAPT_KEYS}}
        # EMA the live params toward the local fit so tracking is gradual (drift is
        # a minutes-scale process); clamp to the trust band.
        r = self.online_rate
        for k in ONLINE_ADAPT_KEYS:
            self.p[k] = self._clamp_key(k, (1.0 - r) * self.p[k] + r * cur[k])

    # ── observer: keep the latent ODE state synced to reality ──────────────────
    def _observe(self, c: CleanState) -> None:
        if self._obs_t is not None:
            dt_real = clamp(c.t - self._obs_t, 0.0, 5.0)
            if dt_real > 0.0:
                stir = STIR_LEVEL[c.mixer_level]   # the action actually applied
                steps = max(1, int(dt_real / self.dt))
                for _ in range(steps):
                    self._y = rk4_step(self._y, dt_real / steps, stir, self.p)
        self._obs_t = c.t
        m_obs = clamp((c.blue_level - self.p["blue_offset"]) / max(self.p["blue_gain"], 1e-3),
                      0.0, 1.0)
        self._y[0] += self.observer_gain * (m_obs - self._y[0])

    # ── model-planned rise ─────────────────────────────────────────────────────
    def _rise_stirrer(self, c: CleanState, dt: float, blue: float) -> float:
        self._observe(c)

        def predict(mixer: int) -> float:
            _, traj = rollout(self._y, mixer, False, False, self.p, self.horizon_s, self.dt)
            return blue_at(traj, self.horizon_s)

        best = min(
            range(4),
            key=lambda mx: (predict(mx) - self.target_amplitude) ** 2
            + self.switch_penalty * (mx != c.mixer_level),
        )
        return MIXER_PWM[best]
