"""GoalModel — the pluggable Model that drives the reaction to a target hue.

Operator sets a goal (``goal_blue`` + ``ideal_time``); the model cleans the raw
state with a ``StateEstimator`` then asks a controller for a discrete decision
(mixer level + glucose/NaOH pulse). The controller is selectable at runtime —
``heuristic`` (no deps, no sim-to-real gap) or ``mpc`` (grey-box ODE planning).

``observe`` runs at 20 Hz but decisions are throttled to ~``decision_hz`` (the
reaction's period is 15-25 s, so 20 Hz decisions are pointless chatter); between
decisions the held mixer is re-emitted. Pulses are cooldown-gated so they aren't
re-fired every decision. The arbiter owns pulse expiry and clamps width 50-5000 ms.
"""
from backend.analysis.signal import clamp
from backend.control.heuristic_controller import HeuristicScheduler
from backend.control.model import Action, Model, ReactionState
from backend.estimator.state_estimator import StateEstimator

# discrete mixer level → stirrer PWM (boundaries mirrored in StateEstimator)
MIXER_PWM = {0: 0, 1: 90, 2: 160, 3: 255}


def _make_controller(name: str):
    if name == "mpc":
        from backend.control.mpc_controller import MPCController  # lazy: pulls in sim
        return MPCController()
    return HeuristicScheduler()


class GoalModel(Model):
    name = "goal_blue"

    def __init__(self, controller: str = "heuristic"):
        self.estimator = StateEstimator()
        self.controller_name = controller if controller in ("heuristic", "mpc") else "heuristic"
        self.controller = _make_controller(self.controller_name)

        # goal (None until an operator sets it)
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
        self._held_mixer = 2
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
            act.stirrer = MIXER_PWM[self._held_mixer]   # re-emit held mixer (arbiter diffs)
            return act

        self._last_decision_t = s.now
        mixer, glucose, naoh = self.controller.decide(clean)
        self._held_mixer = mixer
        act.stirrer = MIXER_PWM[mixer]

        if glucose and s.now >= self._glu_cooldown_until:
            act.glucose_pulse_ms = self.glucose_dose_ms
            self._glu_cooldown_until = s.now + self.glucose_cooldown_s
            self._glucose_fired += 1
            self._glucose_ms_total += self.glucose_dose_ms
            act.notes.append(f"GoalModel: glucose rescue feed #{self._glucose_fired} "
                             f"({self._glucose_ms_total} ms total)")
        if naoh and s.now >= self._naoh_cooldown_until:
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
            p.update(self.controller.get_params())
        return p

    def set_params(self, p: dict) -> None:
        if "controller" in p and p["controller"] in ("heuristic", "mpc") \
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
            self.controller.set_params(p)
