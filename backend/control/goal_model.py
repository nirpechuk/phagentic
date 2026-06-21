"""GoalModel — the pluggable Model wrapping a selectable controller.

Cleans the raw state with a ``StateEstimator`` then asks a controller for a
decision (stirrer PWM + glucose/NaOH pulse intents). The controller is selectable
at runtime:

  ``amplitude`` — relay + PID that oscillates blue between a target peak and ~0
                  (the stirrer only drives blue up, so down is a passive fall).
  ``heuristic`` — phase-aware hue scheduler (reach a target blue by a deadline).
  ``mpc``       — grey-box ODE planning for the hue objective.

The operator's *hue* goal (``goal_blue`` + ``ideal_time``) lives here because it is
shared by the hue controllers and needs run-clock bookkeeping; controller-specific
knobs (e.g. ``target_amplitude``, PID gains) are owned by the controller and reached
by forwarding ``set_params``.

``observe`` runs at 20 Hz but decisions are throttled to ~``decision_hz`` (the
reaction's period is 15-25 s, so 20 Hz decisions are pointless chatter); between
decisions the held stirrer is re-emitted. Pulses are cooldown-gated so they aren't
re-fired every decision. The arbiter owns pulse expiry and clamps width 50-5000 ms.
"""
from backend.analysis.signal import clamp
from backend.control.amplitude_controller import AmplitudeController
from backend.control.heuristic_controller import HeuristicScheduler
from backend.control.model import Action, Model, ReactionState
from backend.estimator.state_estimator import MIXER_PWM, StateEstimator  # noqa: F401 (MIXER_PWM re-exported)

CONTROLLERS = ("amplitude", "heuristic", "mpc")


def _make_controller(name: str):
    if name == "mpc":
        from backend.control.mpc_controller import MPCController  # lazy: pulls in sim
        return MPCController()
    if name == "heuristic":
        return HeuristicScheduler()
    return AmplitudeController()


class GoalModel(Model):
    name = "goal_blue"

    def __init__(self, controller: str = "amplitude"):
        self.estimator = StateEstimator()
        self.controller_name = controller if controller in CONTROLLERS else "amplitude"
        self.controller = _make_controller(self.controller_name)

        # hue goal (None until an operator sets one; used by the hue controllers)
        self.goal_blue: float | None = None
        self.ideal_time: float | None = None      # absolute seconds since run start

        # tunables — pumps are deliberately small + slow: every pulse adds liquid
        # volume (dilution/drift), so doses are short and cooldowns long. Mixing
        # is the main lever; these are rescue feeds, not steering.
        self.decision_hz = 2.0
        self.glucose_dose_ms = 300
        self.naoh_dose_ms = 250
        self.glucose_cooldown_s = 25.0     # ≳ one oscillation cycle between feeds
        self.naoh_cooldown_s = 60.0        # pH help is rare

        self._latest_t = 0.0
        self.reset()

    def reset(self) -> None:
        self.estimator.reset()
        self.controller.reset()
        self._last_decision_t = -1e9
        self._held_stirrer = MIXER_PWM[2]
        self._glu_cooldown_until = 0.0
        self._naoh_cooldown_until = 0.0
        # running volume bookkeeping (ms of pump-on time ≈ added liquid volume)
        self._glucose_fired = 0
        self._naoh_fired = 0
        self._glucose_ms_total = 0
        self._naoh_ms_total = 0

    # ── main hook ─────────────────────────────────────────────────────────────
    def observe(self, s: ReactionState) -> Action:
        self._latest_t = s.t
        clean = self.estimator.update(s)
        clean.goal_blue = self.goal_blue
        clean.time_remaining = (self.ideal_time - s.t) if self.ideal_time is not None else None

        act = Action()
        due = (s.now - self._last_decision_t) >= (1.0 / self.decision_hz)
        if not due:
            act.stirrer = self._held_stirrer            # re-emit held output (arbiter diffs)
            return act

        self._last_decision_t = s.now
        dec = self.controller.decide(clean)
        self._held_stirrer = dec.stirrer
        act.stirrer = dec.stirrer

        if dec.glucose and s.now >= self._glu_cooldown_until:
            act.glucose_pulse_ms = self.glucose_dose_ms
            self._glu_cooldown_until = s.now + self.glucose_cooldown_s
            self._glucose_fired += 1
            self._glucose_ms_total += self.glucose_dose_ms
            act.notes.append(f"GoalModel: glucose rescue feed #{self._glucose_fired} "
                             f"({self._glucose_ms_total} ms total)")
        if dec.naoh and s.now >= self._naoh_cooldown_until:
            act.naoh_pulse_ms = self.naoh_dose_ms
            self._naoh_cooldown_until = s.now + self.naoh_cooldown_s
            self._naoh_fired += 1
            self._naoh_ms_total += self.naoh_dose_ms
            act.notes.append(f"GoalModel: NaOH pH support #{self._naoh_fired} "
                             f"({self._naoh_ms_total} ms total)")
        return act

    # ── params (flat dict; echoed to UI each tick) ────────────────────────────
    def get_params(self) -> dict:
        p = {
            "controller": self.controller_name,
            "goal_blue": self.goal_blue,
            "ideal_time": self.ideal_time,
            "decision_hz": self.decision_hz,
            "glucose_dose_ms": self.glucose_dose_ms,
            "naoh_dose_ms": self.naoh_dose_ms,
            # volume telemetry (pump-on ms ≈ added liquid → watch for drift)
            "glucose_fired": self._glucose_fired,
            "naoh_fired": self._naoh_fired,
            "glucose_ms_total": self._glucose_ms_total,
            "naoh_ms_total": self._naoh_ms_total,
        }
        if hasattr(self.controller, "get_params"):
            p.update(self.controller.get_params())     # controller-owned knobs (target_amplitude, gains, …)
        return p

    def set_params(self, p: dict) -> None:
        if "controller" in p and p["controller"] in CONTROLLERS \
                and p["controller"] != self.controller_name:
            self.controller_name = p["controller"]
            self.controller = _make_controller(self.controller_name)
        if "goal_blue" in p:
            v = p["goal_blue"]
            self.goal_blue = None if v is None else clamp(float(v), 0.0, 1.0)
        if "ideal_time" in p and p["ideal_time"] is not None:
            self.ideal_time = max(0.0, float(p["ideal_time"]))
        if "time_to_goal" in p and p["time_to_goal"] is not None:
            # relative convenience: N seconds from now → absolute run time
            self.ideal_time = self._latest_t + max(0.0, float(p["time_to_goal"]))
        if "decision_hz" in p:
            self.decision_hz = max(0.2, min(20.0, float(p["decision_hz"])))
        if "glucose_dose_ms" in p:
            self.glucose_dose_ms = max(50, min(5000, int(p["glucose_dose_ms"])))
        if "naoh_dose_ms" in p:
            self.naoh_dose_ms = max(50, min(5000, int(p["naoh_dose_ms"])))
        if hasattr(self.controller, "set_params"):
            self.controller.set_params(p)               # controller-owned knobs
