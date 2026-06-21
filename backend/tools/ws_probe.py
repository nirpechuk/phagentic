#!/usr/bin/env python3
"""Headless WebSocket probe for the backend — no browser needed.

Connects, prints the config + a few state frames, optionally sends one command,
then exits. Useful for verifying the backend without the UI or hardware.

  python -m backend.tools.ws_probe                      # just observe
  python -m backend.tools.ws_probe --set stirrer 200    # manual set then observe
  python -m backend.tools.ws_probe --mode auto          # switch mode then observe
  python -m backend.tools.ws_probe --model goal_blue     # select a model then observe
  python -m backend.tools.ws_probe --set-params '{"goal_blue":0.7,"ideal_time":120}'
  python -m backend.tools.ws_probe --url ws://host:8080/ws --frames 10
"""
import argparse
import asyncio
import json

import websockets


async def run(url: str, frames: int, command: dict | None) -> None:
    async with websockets.connect(url) as ws:
        if command:
            await ws.send(json.dumps(command))
            print("→ sent", command)
        seen = 0
        while seen < frames:
            msg = json.loads(await ws.recv())
            typ = msg.get("type")
            if typ == "config":
                print("config:", json.dumps({k: msg[k] for k in ("roles", "models") if k in msg}))
            elif typ == "ack":
                print("ack:", msg.get("ok"), msg.get("msg", ""))
            elif typ == "state":
                seen += 1
                print(f"state[{seen}] ble={msg['ble']} mode={msg['mode']} model={msg['model_name']} "
                      f"blue={msg['blue']:.3f} rgb={msg['rgb']} amp={msg['amp']:.3f} "
                      f"halfP={msg['half_period']} stirrer={msg['stirrer_out']}")
                for n in msg.get("narr_new", []):
                    print("   narr:", n["kind"], n["txt"])
            else:
                print(typ, msg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8080/ws")
    ap.add_argument("--frames", type=int, default=5)
    ap.add_argument("--set", nargs=2, metavar=("ROLE", "VALUE"))
    ap.add_argument("--pulse", nargs=2, metavar=("ROLE", "MS"))
    ap.add_argument("--mode")
    ap.add_argument("--model", metavar="NAME")
    ap.add_argument("--set-params", dest="set_params", metavar="JSON",
                    help='model params as JSON, e.g. \'{"goal_blue":0.7,"ideal_time":120}\'')
    args = ap.parse_args()

    command = None
    if args.set:
        role, val = args.set
        try:
            val = int(val)
        except ValueError:
            val = val.lower() in ("1", "true", "on")
        command = {"type": "set_actuator", "role": role, "value": val}
    elif args.pulse:
        command = {"type": "pulse_actuator", "role": args.pulse[0], "ms": int(args.pulse[1])}
    elif args.mode:
        command = {"type": "set_mode", "mode": args.mode}
    elif args.model:
        command = {"type": "set_model", "name": args.model}
    elif args.set_params:
        command = {"type": "set_model_params", "params": json.loads(args.set_params)}

    asyncio.run(run(args.url, args.frames, command))


if __name__ == "__main__":
    main()
