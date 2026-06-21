import math
import random

from backend.control.model import ReactionState
from backend.estimator.state_estimator import StateEstimator, mixer_level_of


def _state(t, blue, **over):
    base = dict(
        t=t, now=t, blue=blue, rgb=(0, 0, 0), lux=0, amp=0.6,
        half_period=10.0, period=20.0, cycles=0, phase="blue",
        cycle_event=False, last_stirrer=160, last_light=255,
    )
    base.update(over)
    return ReactionState(**base)


def test_mixer_level_mapping():
    assert mixer_level_of(0) == 0
    assert mixer_level_of(90) == 1
    assert mixer_level_of(160) == 2
    assert mixer_level_of(255) == 3


def test_ema_smooths_noisy_blue():
    est = StateEstimator(blue_alpha=0.3)
    rng = random.Random(1)
    last = None
    for i in range(200):
        clean_blue = 0.5 - 0.3 * math.cos(2 * math.pi * i / 80)
        noisy = clean_blue + rng.gauss(0, 0.05)
        c = est.update(_state(i * 0.05, max(0.0, min(1.0, noisy))))
        last = c
    # smoothed blue stays inside the true signal band despite ±0.05 noise
    assert 0.1 < last.blue_level < 0.9


def test_phase_resets_to_trough_on_cycle_event():
    est = StateEstimator()
    for i in range(10):
        est.update(_state(i * 0.5, 0.5))   # advance phase
    c = est.update(_state(5.5, 0.5, cycle_event=True))
    assert c.phase_angle == 0.0            # snapped to trough


def test_phase_advances_with_period():
    est = StateEstimator()
    c = None
    # step at a realistic ~20 Hz for one quarter period (5 s of a 20 s period)
    for i in range(101):
        c = est.update(_state(i * 0.05, 0.5, period=20.0))
    assert math.isclose(c.phase_angle, 2 * math.pi * 5.0 / 20.0, rel_tol=0.15)


def test_stall_risk_grows_without_cycles():
    est = StateEstimator(stall_horizon=90.0)
    est.update(_state(0.0, 0.5, cycle_event=True))
    c = est.update(_state(45.0, 0.5))
    assert math.isclose(c.stall_risk, 0.5, abs_tol=0.05)


def test_dropout_does_not_blow_up_phase():
    est = StateEstimator()
    est.update(_state(0.0, 0.5))
    c = est.update(_state(100.0, 0.5, period=20.0))   # 100s gap (dropout)
    assert 0.0 <= c.phase_angle <= 2 * math.pi        # clamped dt, no explosion
