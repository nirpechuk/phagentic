from backend.control.arbiter import ControlArbiter
from backend.control.model import ReactionState


def _state(**over):
    base = dict(
        t=10.0, now=1000.0, blue=0.5, rgb=(0, 0, 0), lux=0, amp=0.8,
        half_period=25.0, period=50.0, cycles=1, phase="blue",
        cycle_event=False, last_stirrer=150, last_light=255,
    )
    base.update(over)
    return ReactionState(**base)


def test_manual_command_flips_mode_and_sets_output():
    arb = ControlArbiter()
    arb.set_mode("auto")
    arb.apply_manual("stirrer", 200)
    assert arb.mode == "manual"
    desired, _ = arb.step(_state(), now=1000.0)
    assert desired["stirrer"] == 200


def test_pulse_turns_off_after_duration():
    arb = ControlArbiter()
    arb.request_pulse("glucose", 100, now=1000.0, t=5.0)
    d1, _ = arb.step(_state(), now=1000.05)   # within window
    assert d1["glucose"] == 1
    d2, _ = arb.step(_state(), now=1000.20)   # past deadline
    assert d2["glucose"] == 0
    assert arb.glucose_pulses == 1


def test_held_pump_survives_pulse_expiry():
    arb = ControlArbiter()
    arb.apply_manual("glucose", True)         # hold ON
    arb.request_pulse("glucose", 50, now=1000.0, t=0.0)
    d, _ = arb.step(_state(), now=1001.0)     # well past the pulse
    assert d["glucose"] == 1                  # still held


def test_auto_mode_runs_pi():
    arb = ControlArbiter()
    arb.set_mode("auto")
    desired, _ = arb.step(_state(half_period=25.0), now=1000.0)
    assert desired["stirrer"] == 150


def test_model_exception_is_contained():
    arb = ControlArbiter()

    class Boom:
        name = "boom"
        def observe(self, s): raise RuntimeError("kaboom")
        def get_params(self): return {}
        def reset(self): pass

    arb.mode = "ml"
    arb.ml_model = Boom()
    desired, notes = arb.step(_state(), now=1000.0)   # must not raise
    assert arb.model_error is True
    assert any("model error" in n for n in notes)
