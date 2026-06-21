from backend.control.goal_model import MIXER_PWM, GoalModel
from backend.control.model import ControlDecision, ReactionState


def _state(t=10.0, now=10.0, **over):
    base = dict(
        t=t, now=now, blue=0.5, rgb=(0, 0, 0), lux=0, amp=0.6,
        half_period=10.0, period=20.0, cycles=1, phase="blue",
        cycle_event=False, last_stirrer=160, last_light=255,
    )
    base.update(over)
    return ReactionState(**base)


def test_default_controller_is_amplitude():
    m = GoalModel()
    assert m.controller_name == "amplitude"
    act = m.observe(_state(now=100.0))
    assert 0 <= act.stirrer <= 255          # continuous PWM


def test_heuristic_emits_discrete_mixer_pwm():
    m = GoalModel("heuristic")
    m.set_params({"goal_blue": 0.7, "ideal_time": 120})
    act = m.observe(_state(now=100.0))
    assert act.stirrer in MIXER_PWM.values()


def test_decision_rate_gate_holds_output_between_decisions():
    m = GoalModel()
    m.decision_hz = 2.0          # one decision per 0.5 s
    m.observe(_state(now=100.0))                  # first decision
    held = m._held_stirrer
    # 50 ms later: should NOT re-decide, just re-emit the held output
    act = m.observe(_state(now=100.05))
    assert act.stirrer == held
    assert act.glucose_pulse_ms is None


def test_glucose_pulse_is_cooldown_gated():
    m = GoalModel()
    m.decision_hz = 20.0
    m.glucose_cooldown_s = 8.0
    # force the controller to always request glucose
    m.controller.decide = lambda c: ControlDecision(160, True, False)
    a1 = m.observe(_state(now=200.0, cycle_event=True))
    assert a1.glucose_pulse_ms == m.glucose_dose_ms
    a2 = m.observe(_state(now=200.1, cycle_event=True))   # within cooldown
    assert a2.glucose_pulse_ms is None


def test_no_goal_runs_without_crashing():
    m = GoalModel()
    act = m.observe(_state(now=100.0))   # period controller needs no hue goal
    assert 0 <= act.stirrer <= 255


def test_set_params_controller_switch_and_clamps():
    m = GoalModel()
    assert m.controller_name == "amplitude"
    m.set_params({"controller": "heuristic"})
    assert m.controller_name == "heuristic"
    m.set_params({"goal_blue": 5.0, "glucose_dose_ms": 99999})
    assert m.get_params()["goal_blue"] == 1.0
    assert m.get_params()["glucose_dose_ms"] == 5000


def test_target_amplitude_is_forwarded_to_the_controller():
    m = GoalModel()                       # amplitude controller
    m.set_params({"target_amplitude": 0.55})
    assert m.get_params()["target_amplitude"] == 0.55


def test_time_to_goal_is_relative_to_latest_t():
    m = GoalModel("heuristic")
    m.observe(_state(t=30.0, now=100.0))     # establishes latest_t = 30
    m.set_params({"time_to_goal": 90.0})
    assert m.ideal_time == 120.0
