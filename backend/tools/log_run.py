#!/usr/bin/env python3
"""Record the backend state stream to a JSONL file — for ODE fitting / eval.

Reuses the existing WebSocket (read-only; just observes), writing one state
frame per line. Each frame already carries everything the ODE fitter needs:
t, blue, rgb, lux, amp, period, half_period, phase, cycles, stall_risk,
stirrer_out, light_out, glucose_active, naoh_active, glucose_pulses.

  python -m backend.tools.log_run --out runs/run1.jsonl
  python -m backend.tools.log_run --out runs/run1.jsonl --seconds 300

Capture a varied set for fitting: a fixed-mixer free-run at each level, a
glucose-pulse recovery run, a NaOH-perturbation run, and a held-out validation
run with a mixed schedule. Use the frame's own `t` as the time base (broadcast
is not perfectly uniform).
"""
import argparse
import asyncio
import json
import os
import time

import websockets


async def run(url: str, out: str, seconds: float | None, max_frames: int | None) -> None:
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    n = 0
    start = time.monotonic()
    async with websockets.connect(url) as ws:
        with open(out, "w") as f:
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("type") != "state":
                    continue
                f.write(json.dumps(msg) + "\n")
                f.flush()
                n += 1
                if n % 50 == 0:
                    print(f"  {n} frames (t={msg.get('t')})")
                if max_frames and n >= max_frames:
                    break
                if seconds and (time.monotonic() - start) >= seconds:
                    break
    print(f"wrote {n} frames → {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="ws://localhost:8080/ws")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--frames", type=int, default=None)
    args = ap.parse_args()
    asyncio.run(run(args.url, args.out, args.seconds, args.frames))


if __name__ == "__main__":
    main()
