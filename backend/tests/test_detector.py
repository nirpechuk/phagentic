import math

from backend.analysis.detector import Detector


def test_detector_tracks_cycles_and_period():
    """A clean sine on the blue signal should yield a stable cycle count and a
    period close to the synthetic one."""
    det = Detector()
    P = 10.0            # seconds per oscillation
    dt = 0.05
    last = None
    t = 0.0
    while t <= 60.0:
        blue = 0.5 + 0.4 * math.sin(2 * math.pi * t / P)
        last = det.update(t, blue)
        t += dt

    assert last.cycles >= 4                 # ~6 full cycles in 60 s
    assert abs(last.period - P) < 1.5       # period recovered within tolerance
    assert abs(last.half_period - P / 2) < 1.5
    assert last.amp > 0.6                   # peak-to-trough ~0.8


def test_detector_reset_clears_state():
    det = Detector()
    for i in range(50):
        det.update(i * 0.1, 0.5 + 0.3 * math.sin(i * 0.3))
    det.reset()
    assert det.cycles == 0 and det.amp == 0.0 and det.period == 0.0
