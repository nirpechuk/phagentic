"""Grey-box ODE of the Blue Bottle (methylene-blue) redox oscillator.

4 normalized states:
  M ∈ [0,1] oxidised (blue) fraction — observable: blue ≈ blue_offset + blue_gain·M
  O          dissolved O2
  G          glucose / reductant reservoir (slow)
  P          hydroxide / pH factor (very slow; set by NaOH)

  dM/dt = k_ox·O·(1−M)  −  k_red·G·P·M
  dO/dt = k_aer·stir·(O_sat − O)  −  k_cons·O·(1−M)
  dG/dt = −k_gc·(1−M)·G
  dP/dt = −k_pd·P

Pulses are impulses (instantaneous adds to G / P) injected at the decision tick.
``stir`` ∈ [0,1] is the mixer level mapped from {off,low,mid,high}. Pure Python
RK4 — the system is 4-dimensional, numpy buys nothing. Constants are fit targets.
"""
from backend.analysis.signal import clamp

# mixer level 0..3 → normalized stirring intensity
STIR_LEVEL = {0: 0.0, 1: 0.34, 2: 0.67, 3: 1.0}

# Hand-set to the *measured* timescales of this reactor (grounded in runs/, not
# textbook guesses): under full stir blue rises 0→~0.67 in ~12 s; stir off it
# fades to ~0.03 (clear) in ~35 s — i.e. the fall is ~3× slower than the rise,
# which is the whole point of the on/off harness. O2 is kept stir-limited
# (k_aer < k_cons) so mixer level is a real control lever: steady blue is
# ~0.03 / 0.61 / 0.68 / 0.69 at mixer off/low/mid/high. The fitter refines these.
DEFAULT_PARAMS = {
    "k_ox": 0.6, "k_red": 0.11, "k_aer": 0.35, "k_cons": 0.9, "O_sat": 1.0,
    "k_gc": 0.008, "k_pd": 0.003, "dose_g": 0.6, "dose_n": 0.5,
    "blue_gain": 0.78, "blue_offset": 0.03, "noise_sd": 0.02,
    # initial latent state (used by MPC observer + sim resets)
    "M0": 0.4, "O0": 0.3, "G0": 1.0, "P0": 1.0,
}

# Parameters the fitter is allowed to vary (initial latent state is fixed).
FIT_KEYS = ("k_ox", "k_red", "k_aer", "k_cons", "O_sat", "k_gc", "k_pd",
            "dose_g", "dose_n", "blue_gain", "blue_offset")


def initial_state(p: dict) -> list:
    return [p["M0"], p["O0"], p["G0"], p["P0"]]


def deriv(y: list, stir: float, p: dict) -> list:
    M, O, G, P = y
    dM = p["k_ox"] * O * (1.0 - M) - p["k_red"] * G * P * M
    dO = p["k_aer"] * stir * (p["O_sat"] - O) - p["k_cons"] * O * (1.0 - M)
    dG = -p["k_gc"] * (1.0 - M) * G
    dP = -p["k_pd"] * P
    return [dM, dO, dG, dP]


def rk4_step(y: list, dt: float, stir: float, p: dict) -> list:
    k1 = deriv(y, stir, p)
    k2 = deriv([y[i] + 0.5 * dt * k1[i] for i in range(4)], stir, p)
    k3 = deriv([y[i] + 0.5 * dt * k2[i] for i in range(4)], stir, p)
    k4 = deriv([y[i] + dt * k3[i] for i in range(4)], stir, p)
    out = [y[i] + dt / 6.0 * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]) for i in range(4)]
    # keep states physical
    out[0] = clamp(out[0], 0.0, 1.0)   # M
    out[1] = max(0.0, out[1])          # O
    out[2] = max(0.0, out[2])          # G
    out[3] = max(0.0, out[3])          # P
    return out


def apply_pulse(y: list, glucose: bool, naoh: bool, p: dict) -> list:
    M, O, G, P = y
    if glucose:
        G += p["dose_g"]
    if naoh:
        P += p["dose_n"]
    return [M, O, G, P]


def blue_of(M: float, p: dict) -> float:
    """Noiseless sensor map M → blue (matches ReactionState.blue units)."""
    return clamp(p["blue_offset"] + p["blue_gain"] * M, 0.0, 1.0)


def sensor_model(M: float, p: dict, rng) -> float:
    """Noisy sensor map for sim training/domain-randomization. ``rng`` is a
    ``random.Random``; emulate shot noise + 8-bit-ish quantization."""
    b = blue_of(M, p) + rng.gauss(0.0, p.get("noise_sd", 0.02))
    return round(clamp(b, 0.0, 1.0) * 255.0) / 255.0
