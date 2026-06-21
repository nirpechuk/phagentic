#!/usr/bin/env python3
"""Offline sim-to-real check: feed a logged run through the StateEstimator (and
optionally the ODE) and report whether the cleaned signal tracks reality.

This validates the firewall independent of any controller: the cleaned phase
must not slip relative to real cycle events, and (with --ode) the one-cycle-ahead
ODE prediction error tells you whether MPC is safe to deploy.

  python -m backend.tools.replay_eval runs/run1.jsonl
  python -m backend.tools.replay_eval runs/run1.jsonl --ode
"""
import argparse
import json
import math

from backend.control.model import ReactionState
from backend.estimator.state_estimator import StateEstimator


def load_frames(path: str) -> list:
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and json.loads(line).get("type") == "state":
                out.append(json.loads(line))
    return out


def frame_to_state(m: dict, prev_cycles: int) -> tuple[ReactionState, int]:
    cycles = int(m.get("cycles", 0))
    s = ReactionState(
        t=float(m["t"]), now=float(m["t"]), blue=float(m["blue"]),
        rgb=tuple(m.get("rgb", (0, 0, 0))), lux=int(m.get("lux", 0)),
        amp=float(m.get("amp", 0.0)), half_period=float(m.get("half_period", 0.0)),
        period=float(m.get("period", 0.0)), cycles=cycles,
        phase=m.get("phase", "colorless"), cycle_event=cycles > prev_cycles,
        last_stirrer=int(m.get("stirrer_out", 0)), last_light=int(m.get("light_out", 0)),
    )
    return s, cycles


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log")
    ap.add_argument("--ode", action="store_true", help="also report ODE one-cycle prediction error")
    args = ap.parse_args()

    frames = load_frames(args.log)
    if len(frames) < 10:
        raise SystemExit("need >10 state frames")

    est = StateEstimator()
    prev_cycles = int(frames[0].get("cycles", 0))
    phase_slips = 0
    last_phase = 0.0
    cleaned = []
    for m in frames:
        s, prev_cycles = frame_to_state(m, prev_cycles)
        c = est.update(s)
        cleaned.append(c)
        # a slip = phase jumps backward by more than a small margin without a cycle_event
        if not s.cycle_event and c.phase_angle < last_phase - 0.5 and last_phase < 2 * math.pi - 0.5:
            phase_slips += 1
        last_phase = c.phase_angle

    periods = [c.period for c in cleaned if c.period > 0]
    amps = [c.amplitude for c in cleaned if c.amplitude > 0]
    print(f"frames:        {len(frames)}")
    print(f"phase slips:   {phase_slips}  (want ~0)")
    print(f"period:        mean={_mean(periods):.1f}s  n={len(periods)}")
    print(f"amplitude:     mean={_mean(amps):.3f}")
    print(f"stall_risk:    max={max(c.stall_risk for c in cleaned):.2f}")

    if args.ode:
        from backend.sim.fit import load_run, simulate
        from backend.sim.bluebottle_ode import DEFAULT_PARAMS
        from backend.control.mpc_controller import load_fitted_params
        run = load_run(args.log)
        p = load_fitted_params()
        pred = simulate(run, p)
        target = [fr["blue"] for fr in run]
        rmse = math.sqrt(_mean([(a - b) ** 2 for a, b in zip(pred, target)]))
        which = "fitted" if p != DEFAULT_PARAMS else "DEFAULT (unfitted!)"
        print(f"ODE blue RMSE: {rmse:.3f}  using {which} params"
              f"{'  — gate MPC on this' if rmse > 0.1 else ''}")


def _mean(xs: list) -> float:
    return sum(xs) / len(xs) if xs else 0.0


if __name__ == "__main__":
    main()
