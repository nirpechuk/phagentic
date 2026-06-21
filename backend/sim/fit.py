"""Fit the grey-box ODE to logged real runs (offline tooling).

Reads run logs (JSONL of state frames, as produced by backend/tools/log_run.py),
replays the logged actuator trace through the ODE, and minimizes squared error
between predicted and (smoothed) logged blue via multiplicative coordinate
descent. Pure Python, no dependencies — the 4-state ODE makes this cheap enough
that numpy/scipy buy nothing.

  python -m backend.sim.fit runs/*.jsonl --out backend/sim/fitted_params.json

Validate on a held-out run before trusting MPC. If the fit is poor (period off
by >~15% or amplitude off by >~20%), stay on the heuristic controller.
"""
import argparse
import glob
import json

from backend.analysis.signal import clamp
from backend.estimator.state_estimator import mixer_level_of
from backend.sim.bluebottle_ode import (
    DEFAULT_PARAMS, FIT_KEYS, STIR_LEVEL, apply_pulse, blue_of, initial_state, rk4_step,
)

FITTED_PATH = "backend/sim/fitted_params.json"


def load_run(path: str) -> list:
    """Load a JSONL run → list of dicts {t, blue, mixer, glucose_edge, naoh_edge}."""
    frames = []
    prev_g = prev_n = False
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = json.loads(line)
            if m.get("type") != "state":
                continue
            g = bool(m.get("glucose_active"))
            n = bool(m.get("naoh_active"))
            frames.append({
                "t": float(m["t"]),
                "blue": float(m["blue"]),
                "mixer": mixer_level_of(int(m.get("stirrer_out", 0))),
                "glucose_edge": g and not prev_g,   # rising edge = a pulse fired
                "naoh_edge": n and not prev_n,
            })
            prev_g, prev_n = g, n
    return frames


def simulate(frames: list, p: dict) -> list:
    """Replay the logged actuator trace through the ODE → predicted blue per frame."""
    y = initial_state(p)
    pred = []
    prev_t = frames[0]["t"] if frames else 0.0
    for fr in frames:
        dt = clamp(fr["t"] - prev_t, 0.0, 2.0)
        prev_t = fr["t"]
        if fr["glucose_edge"] or fr["naoh_edge"]:
            y = apply_pulse(y, fr["glucose_edge"], fr["naoh_edge"], p)
        # sub-step for stability
        steps = max(1, int(dt / 0.1))
        stir = STIR_LEVEL[fr["mixer"]]
        for _ in range(steps):
            y = rk4_step(y, dt / steps if steps else dt, stir, p)
        pred.append(blue_of(y[0], p))
    return pred


def _smooth(xs: list, alpha: float = 0.35) -> list:
    out, e = [], None
    for x in xs:
        e = x if e is None else e + alpha * (x - e)
        out.append(e)
    return out


def sse(runs: list, p: dict) -> float:
    total = 0.0
    for frames in runs:
        target = _smooth([fr["blue"] for fr in frames])
        pred = simulate(frames, p)
        total += sum((a - b) ** 2 for a, b in zip(pred, target))
    return total


def fit_coordinate_descent(runs: list, p0: dict, rounds: int = 6) -> dict:
    """Multiplicative coordinate descent over FIT_KEYS — robust, no deps."""
    p = dict(p0)
    best = sse(runs, p)
    for _ in range(rounds):
        for k in FIT_KEYS:
            for factor in (0.5, 0.7, 0.85, 1.18, 1.43, 2.0):
                trial = dict(p)
                trial[k] = p[k] * factor
                s = sse(runs, trial)
                if s < best:
                    best, p = s, trial
    return p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+", help="JSONL run logs (globs ok)")
    ap.add_argument("--out", default=FITTED_PATH)
    args = ap.parse_args()

    paths = [g for pat in args.logs for g in glob.glob(pat)]
    runs = [load_run(p) for p in paths]
    runs = [r for r in runs if len(r) > 10]
    if not runs:
        raise SystemExit("no usable runs (need >10 state frames each)")
    print(f"fitting on {len(runs)} run(s), {sum(len(r) for r in runs)} frames")

    p0 = dict(DEFAULT_PARAMS)
    print(f"initial SSE: {sse(runs, p0):.4f}")
    p = fit_coordinate_descent(runs, p0)
    print(f"fitted SSE:  {sse(runs, p):.4f}")

    with open(args.out, "w") as f:
        json.dump(p, f, indent=2)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
