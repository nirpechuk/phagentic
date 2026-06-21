from backend.control.model import ReactionState
from backend.control.pi_model import PIModel


def _state(**over):
    base = dict(
        t=10.0, now=1000.0, blue=0.5, rgb=(0, 0, 0), lux=0, amp=0.8,
        half_period=25.0, period=50.0, cycles=1, phase="blue",
        cycle_event=False, last_stirrer=150, last_light=255,
    )
    base.update(over)
    return ReactionState(**base)


def test_pi_holds_setpoint_at_zero_error():
    m = PIModel()  # target_half_period = 25
    act = m.observe(_state(half_period=25.0))
    assert act.stirrer == 150            # 150 - 0 - 0


def test_pi_pushes_stirrer_when_too_fast():
    m = PIModel()
    act = m.observe(_state(half_period=5.0))   # err=20 -> 150-80-0.4
    assert act.stirrer == 70


def test_pi_auto_pulses_after_two_low_amp_cycles():
    m = PIModel()
    m.amp_threshold = 0.5
    a1 = m.observe(_state(amp=0.1, cycle_event=True))
    assert a1.glucose_pulse_ms is None       # one low cycle isn't enough
    a2 = m.observe(_state(amp=0.1, cycle_event=True))
    assert a2.glucose_pulse_ms == m.glucose_dose_ms


def test_set_params_clamps():
    m = PIModel()
    m.set_params({"amp_threshold": 5.0, "glucose_dose_ms": 99999})
    assert m.get_params()["amp_threshold"] == 0.95
    assert m.get_params()["glucose_dose_ms"] == 2000
