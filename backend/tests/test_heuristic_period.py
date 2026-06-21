"""Period-lock behaviour of the heuristic scheduler.

When ``target_period`` is set the mixer must regulate the cycle cadence toward
it (feed-forward to the nearest discrete level + ±1 trim on the live period),
taking precedence over the goal-hue-by-deadline scheduling.
"""
from backend.control.heuristic_controller import HeuristicScheduler
from backend.estimator.state_estimator import CleanState


def _clean(**over):
    base = dict(
        t=10.0, blue_level=0.5, baseline=0.5, amplitude=0.6, phase_angle=0.0,
        phase="blue", period=20.0, period_norm=1.0, stall_risk=0.0,
        cycle_event=False, mixer_level=2, mixer_onehot=(0, 0, 1, 0),
        goal_blue=None, time_remaining=None, target_period=None,
    )
    base.update(over)
    return CleanState(**base)


def test_short_target_period_drives_high_mixer():
    h = HeuristicScheduler()
    # 16 s target ≈ level 3's natural period; live period on track → no trim.
    mixer, _, _ = h.decide(_clean(target_period=16.0, period=16.0))
    assert mixer == 3


def test_long_target_period_drives_low_mixer():
    h = HeuristicScheduler()
    mixer, _, _ = h.decide(_clean(target_period=58.0, period=58.0))
    assert mixer == 0


def test_too_slow_bumps_mixer_up():
    h = HeuristicScheduler()
    # target 32 s ≈ level 2, but live cycle is much slower → mix harder.
    base, _, _ = h.decide(_clean(target_period=32.0, period=32.0))
    slow, _, _ = h.decide(_clean(target_period=32.0, period=44.0))
    assert slow == base + 1


def test_too_fast_eases_off():
    h = HeuristicScheduler()
    base, _, _ = h.decide(_clean(target_period=32.0, period=32.0))
    fast, _, _ = h.decide(_clean(target_period=32.0, period=20.0))
    assert fast == base - 1


def test_period_lock_overrides_goal_hue_deadline():
    h = HeuristicScheduler()
    # A goal + deadline that alone would pick a timing-based mixer; the period
    # lock must win and pick the fast level regardless.
    mixer, _, _ = h.decide(_clean(
        target_period=16.0, period=16.0, goal_blue=0.9, time_remaining=120.0))
    assert mixer == 3


def test_no_target_period_keeps_deadline_scheduling():
    h = HeuristicScheduler()
    # Without a target period, an unset goal/deadline falls back to sustain (mid).
    mixer, _, _ = h.decide(_clean())
    assert mixer == 2
