"""Small numeric helpers for turning sensor colour into the oscillation signal."""


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def blue_from_rgb(r: int, g: int, b: int, c: int = 0) -> float:
    """Normalised 'blueness' 0..1 of the Blue Bottle reaction.

    Port of frontend/logic.js:154 — ``(b - r)`` is ~0 when colourless and large
    when blue; divide by 200 and clamp. ``c`` (clear channel) is accepted for
    signature parity with the sensor but unused, matching the original.
    """
    return clamp((b - r) / 200.0, 0.0, 1.0)
