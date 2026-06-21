from backend.control.goal_model import MIXER_PWM, GoalModel
from backend.control.model import ReactionState


def _state(t=10.0, now=10.0, **over):
    base = dict(
        t=t, now=now, blue=0.5, rgb=(0, 0, 0), lux=0, amp=0.6,
        half_period=10.0, period=20.0, cycles=1, phase="blue",
        cycle_event=False, last_stirrer=160, last_light=255,
    )
    base.update(over)
    return ReactionState(**base)


def test_stirrer_is_always_a_valid_mixer_pwm():
    m = GoalModel()
    m.set_params({"goal_blue": 0.7, "ideal_time": 120})
    act = m.observe(_state(now=100.0))
    assert act.stirrer in MIXER_PWM.values()


def test_decision_rate_gate_holds_mixer_between_decisions():
    m = GoalModel()
    m.decision_hz = 2.0          # one decision per 0.5 s
    m.observe(_state(now=100.0))                  # first decision
    held = m._held_mixer
    # 50 ms later: should NOT re-decide, just re-emit the held mixer
    act = m.observe(_state(now=100.05))
    assert act.stirrer == MIXER_PWM[held]
    assert act.glucose_pulse_ms is None


def test_glucose_pulse_is_cooldown_gated():
    m = GoalModel()
    m.decision_hz = 20.0
    m.glucose_cooldown_s = 8.0
    # force the controller to always request glucose
    m.controller.decide = lambda c: (2, True, False)
    a1 = m.observe(_state(now=200.0, cycle_event=True))
    assert a1.glucose_pulse_ms == m.glucose_dose_ms
    a2 = m.observe(_state(now=200.1, cycle_event=True))   # within cooldown
    assert a2.glucose_pulse_ms is None


def test_no_goal_sustains_without_crashing():
    m = GoalModel()
    act = m.observe(_state(now=100.0))   # no goal set
    assert act.stirrer in MIXER_PWM.values()


def test_set_params_controller_switch_and_clamps():
    m = GoalModel()
    assert m.controller_name == "heuristic"
    m.set_params({"controller": "mpc"})
    assert m.controller_name == "mpc"
    m.set_params({"goal_blue": 5.0, "glucose_dose_ms": 99999})
    assert m.get_params()["goal_blue"] == 1.0
    assert m.get_params()["glucose_dose_ms"] == 5000


def test_time_to_goal_is_relative_to_latest_t():
    m = GoalModel()
    m.observe(_state(t=30.0, now=100.0))     # establishes latest_t = 30
    m.set_params({"time_to_goal": 90.0})
    assert m.ideal_time == 120.0
