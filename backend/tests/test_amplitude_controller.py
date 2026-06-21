"""Relay + PID amplitude driver — oscillate blue between a peak and ~colourless."""
from backend.control.amplitude_controller import AmplitudeController
from backend.control.model import ControlDecision
from backend.estimator.state_estimator import CleanState


def _clean(**over):
    base = dict(
        t=0.0, blue_level=0.5, baseline=0.5, amplitude=0.6, phase_angle=0.0,
        phase="blue", period=20.0, period_norm=1.0, stall_risk=0.0,
        cycle_event=False, mixer_level=2, mixer_onehot=(0, 0, 1, 0),
        goal_blue=None, time_remaining=None,
    )
    base.update(over)
    return CleanState(**base)


def test_returns_pwm_decision():
    d = AmplitudeController().decide(_clean(t=0.0, blue_level=0.1))
    assert isinstance(d, ControlDecision)
    assert 0 <= d.stirrer <= 255


def test_rising_below_target_drives_stirrer_up():
    c = AmplitudeController()
    c.set_params({"target_amplitude": 0.7})
    d = c.decide(_clean(t=0.0, blue_level=0.1))     # far below target → strong drive
    assert c._rising is True
    assert d.stirrer > 0


def test_reaching_target_flips_to_falling_and_cuts_stir():
    c = AmplitudeController()
    c.set_params({"target_amplitude": 0.7, "drive_low": 0})
    c.decide(_clean(t=0.0, blue_level=0.1))
    c.decide(_clean(t=1.0, blue_level=0.70))        # at target → flip to falling
    assert c._rising is False
    d = c.decide(_clean(t=2.0, blue_level=0.65))    # falling → stirrer off (passive)
    assert d.stirrer == 0


def test_reaching_colourless_flips_back_to_rising():
    c = AmplitudeController()
    c.set_params({"target_amplitude": 0.7, "low_threshold": 0.1})
    c.decide(_clean(t=0.0, blue_level=0.7))         # starts at peak → goes falling
    assert c._rising is False
    c.decide(_clean(t=10.0, blue_level=0.10))       # at colourless → flip to rising
    assert c._rising is True


def test_full_relay_cycle_against_asymmetric_plant():
    """Up via stirrer (fast), down passive (slow): must produce repeated swings."""
    c = AmplitudeController()
    c.set_params({"target_amplitude": 0.7, "low_threshold": 0.1})
    blue, dt = 0.05, 0.5
    flips, t = 0, 0.0
    prev_rising = c._rising
    while t < 400:
        d = c.decide(_clean(t=t, blue_level=blue))
        blue += dt * (0.9 * (d.stirrer / 255.0) * (1 - blue) - 0.05 * blue)
        blue = max(0.0, min(1.0, blue))
        if c._rising != prev_rising:
            flips += 1
            prev_rising = c._rising
        t += dt
    assert flips >= 6                               # several full oscillations, not stuck


def test_max_half_s_safety_flips_a_stuck_stroke():
    c = AmplitudeController()
    c.set_params({"target_amplitude": 0.9, "max_half_s": 20.0})
    # blue never reaches 0.9 → without the safety flip the relay would wedge
    for i in range(80):
        c.decide(_clean(t=float(i), blue_level=0.5))
    assert c._rising is False                        # timed out of the rising stroke


def test_rescue_pumps_on_collapse_and_stall():
    c = AmplitudeController()
    dying = c.decide(_clean(amplitude=0.05, cycle_event=True))
    assert dying.glucose is True
    stalled = c.decide(_clean(stall_risk=0.9, cycle_event=True))
    assert stalled.naoh is True


def test_glucose_fires_when_fall_stalls_without_cycle_events():
    """Stuck high on the way to colourless (no cycle events) ⇒ feed glucose."""
    c = AmplitudeController()
    c.set_params({"target_amplitude": 0.7, "low_threshold": 0.1,
                  "stall_grace_s": 20.0, "amp_floor": 0.0})  # disable amplitude-decay path
    c.decide(_clean(t=0.0, blue_level=0.7))                  # start at peak → falling
    assert c._rising is False
    # blue stuck at 0.6 (above colourless), cycles stopped → no progress downward
    held = c.decide(_clean(t=10.0, blue_level=0.6, cycle_event=False))
    assert held.glucose is False                             # first falling sample → arms watchdog
    stuck = c.decide(_clean(t=31.0, blue_level=0.6, cycle_event=False))
    assert stuck.glucose is True                             # 21s without progress → reductant feed


def test_glucose_held_off_when_fall_is_progressing():
    """A slow-but-moving fall is not a stall — don't waste glucose on it."""
    c = AmplitudeController()
    c.set_params({"target_amplitude": 0.7, "low_threshold": 0.1,
                  "stall_grace_s": 20.0, "amp_floor": 0.0})
    c.decide(_clean(t=0.0, blue_level=0.7))                  # falling
    blue = 0.7
    for i in range(1, 60):                                   # creeps down 0.01 / step
        blue = max(0.1, blue - 0.01)
        d = c.decide(_clean(t=float(i), blue_level=blue, cycle_event=False))
        assert d.glucose is False                            # progress resets the watchdog
