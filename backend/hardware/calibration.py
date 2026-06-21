"""White-balance calibration + raw-RGBC → 8-bit RGB conversion.

Moved verbatim (behaviour-preserving) from hub/dashboard.py:38-76. The TCS34725
returns raw uint16 R/G/B/Clear; we subtract an IR estimate, apply per-channel
white-balance multipliers, and scale to 0-255 by the brightest channel.
"""
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing the hub layer (and BLE deps) at type-check time
    from controller import Controller

SAMPLE_RATE = 20  # Hz — sampling cadence while collecting calibration frames


def sample_wb(ctrl: "Controller", samples: int = 30, rate: int = SAMPLE_RATE) -> tuple:
    """Sample the sensor and compute ``(sr, sg, sb, white_c)``.

    No prompting — the caller is responsible for aiming the sensor at a white
    surface first. Returns identity multipliers if no data arrives.
    """
    rs, gs, bs, cs = [], [], [], []
    for _ in range(samples):
        d = ctrl.get_rgb()
        if d:
            rs.append(d["r"]); gs.append(d["g"]); bs.append(d["b"]); cs.append(d["c"])
        time.sleep(1.0 / rate)
    if not rs:
        return 1.0, 1.0, 1.0, 1.0
    r_avg   = sum(rs) / len(rs)
    g_avg   = sum(gs) / len(gs)
    b_avg   = sum(bs) / len(bs)
    white_c = sum(cs) / len(cs)
    peak    = max(r_avg, g_avg, b_avg) or 1.0
    sr = peak / r_avg if r_avg else 1.0
    sg = peak / g_avg if g_avg else 1.0
    sb = peak / b_avg if b_avg else 1.0
    return sr, sg, sb, (white_c or 1.0)


def to_rgb8(r: int, g: int, b: int, c: int, wb: tuple, white_c: float) -> tuple:
    """Raw RGBC → 8-bit (r, g, b). IR subtraction + white balance + brightness."""
    ir = max(0, (r + g + b - c) // 2)
    rf = max(0.0, (r - ir) * wb[0])
    gf = max(0.0, (g - ir) * wb[1])
    bf = max(0.0, (b - ir) * wb[2])
    peak = max(rf, gf, bf)
    if peak == 0:
        return 0, 0, 0
    brightness = min(1.0, c / white_c) if white_c else 1.0
    s = 255.0 / peak * brightness
    return int(rf * s), int(gf * s), int(bf * s)
