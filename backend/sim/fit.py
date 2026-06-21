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
    DEFAULT_PARAMS, FIT_KEYS, STIR_LEVEL, apply_pulse, blue_of, rk4_step,
)

FITTED_PATH = "backend/sim/fitted_params.json"

# Re-seed the latent M from the observed blue every this-many seconds when fitting.
# This is the metric the MPC actually relies on — it re-syncs M to the observed
# blue every decision and only plans this far ahead (MPCController.horizon_s) — so
# the fit measures *horizon* prediction error, not open-loop drift over the whole
# run. Open-loop replay is dominated by the long clear stretches and rewards a
# collapsed blue ceiling; horizon replay keeps the rise/fall/ceiling honest.
FIT_WINDOW_S = 45.0


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


def simulate(frames: list, p: dict, reseed_s: float | None = None,
             obs: list | None = None) -> list:
    """Replay the logged actuator trace through the ODE → predicted blue per frame.

    Latent M is seeded from the observed blue (invert the sensor map) rather than
    the generic M0, which would inject a startup transient — badly on short runs.
    With ``reseed_s`` set, M is re-synced to the observed blue at the start of every
    window of that many seconds, so the result measures *horizon* prediction error
    (what the MPC relies on) instead of open-loop drift; see ``FIT_WINDOW_S``.
    ``obs`` is the per-frame blue used for (re)seeding (defaults to each frame's own
    blue — pass the smoothed target to match the fit objective).

    Crucially the reseed corrects **only M**, carrying O/G/P forward exactly as the
    live MPC observer does (it nudges M from blue and never touches the unobservable
    reservoirs). Resetting O/G/P to defaults each window — which an earlier version
    did — biased the fit (it systematically under-predicted blue and pulled k_red to
    the floor), because mid-trajectory the reservoirs are nowhere near their initial
    values. Only the very first seed sets O/G/P (from defaults)."""
    if not frames:
        return []
    src = obs if obs is not None else [fr["blue"] for fr in frames]

    def m_of(i: int) -> float:
        return clamp((src[i] - p["blue_offset"]) / max(p["blue_gain"], 1e-3), 0.0, 1.0)

    y = [m_of(0), p["O0"], p["G0"], p["P0"]]
    win_t0 = prev_t = frames[0]["t"]
    pred = []
    for i, fr in enumerate(frames):
        if reseed_s is not None and fr["t"] - win_t0 >= reseed_s:
            y[0] = m_of(i)          # re-sync only the observable M; carry O/G/P
            win_t0 = fr["t"]
        dt = clamp(fr["t"] - prev_t, 0.0, 2.0)
        prev_t = fr["t"]
        if fr["glucose_edge"] or fr["naoh_edge"]:
            y = apply_pulse(y, fr["glucose_edge"], fr["naoh_edge"], p)
        # sub-step for stability
        steps = max(1, int(dt / 0.1))
        stir = STIR_LEVEL[fr["mixer"]]
        for _ in range(steps):
            y = rk4_step(y, dt / steps, stir, p)
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
        pred = simulate(frames, p, reseed_s=FIT_WINDOW_S, obs=target)
        total += sum((a - b) ** 2 for a, b in zip(pred, target))
    return total


# Multiplicative steps spanning coarse (×0.5 / ×1.9) to fine (×0.94 / ×1.06). The
# fine steps matter: with only coarse factors the descent stalls in a local minimum
# well short of the achievable fit (≈0.10 vs ≈0.07 horizon RMSE on the harness run).
_FACTORS = (0.5, 0.65, 0.78, 0.88, 0.94, 1.06, 1.13, 1.28, 1.5, 1.9)


def fit_coordinate_descent(runs: list, p0: dict, max_rounds: int = 20) -> dict:
    """Multiplicative coordinate descent over FIT_KEYS — robust, no deps. Runs to
    convergence (a full round with no accepted step) or ``max_rounds``."""
    p = dict(p0)
    best = sse(runs, p)
    for _ in range(max_rounds):
        improved = False
        for k in FIT_KEYS:
            for factor in _FACTORS:
                trial = dict(p)
                trial[k] = p[k] * factor
                s = sse(runs, trial)
                if s < best - 1e-9:
                    best, p, improved = s, trial, True
        if not improved:
            break
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
