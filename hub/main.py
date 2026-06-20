#!/usr/bin/env python3
"""Streams RGB from a TCS34725 sensor and prints a live color swatch to the terminal."""
import sys
import time

import config
from controller import Controller
from transport.ble_transport import BLETransport

SAMPLE_RATE = 20   # Hz


def calibrate(ctrl: Controller, samples: int = 30) -> tuple[float, float, float, float]:
    """Point sensor at white; returns (sr, sg, sb, white_c) where white_c is the clear
    channel value for white — used as the 100% brightness reference."""
    print("Point sensor at a white surface, then press Enter to calibrate white balance...")
    input()
    rs, gs, bs, cs = [], [], [], []
    for _ in range(samples):
        d = ctrl.get_rgb()
        if d:
            rs.append(d["r"]); gs.append(d["g"]); bs.append(d["b"]); cs.append(d["c"])
        time.sleep(1.0 / SAMPLE_RATE)
    if not rs:
        print("No sensor data — skipping calibration.")
        return 1.0, 1.0, 1.0, 1.0
    r_avg   = sum(rs) / len(rs)
    g_avg   = sum(gs) / len(gs)
    b_avg   = sum(bs) / len(bs)
    white_c = sum(cs) / len(cs)
    peak    = max(r_avg, g_avg, b_avg)
    sr, sg, sb = peak / r_avg, peak / g_avg, peak / b_avg
    print(f"  R×{sr:.2f}  G×{sg:.2f}  B×{sb:.2f}  white_c={white_c:.0f}\n")
    return sr, sg, sb, white_c


def to_rgb8(
    r: int, g: int, b: int, c: int,
    wb: tuple[float, float, float], white_c: float,
) -> tuple[int, int, int]:
    ir         = max(0, (r + g + b - c) // 2)
    rf         = max(0.0, (r - ir) * wb[0])
    gf         = max(0.0, (g - ir) * wb[1])
    bf         = max(0.0, (b - ir) * wb[2])
    peak       = max(rf, gf, bf)
    if peak == 0:
        return 0, 0, 0
    brightness = min(1.0, c / white_c)   # 1.0 = white-level light, 0.0 = dark
    s          = 255.0 / peak * brightness
    return int(rf * s), int(gf * s), int(bf * s)


def main() -> None:
    cfg = config.load_config()
    transport = BLETransport(config.device_name(cfg))
    with Controller(transport) as ctrl:
        print("Pinging...", end=" ", flush=True)
        if not ctrl.ping():
            print("no response. Is the firmware flashed?")
            sys.exit(1)
        print("OK")

        pins = config.pin_map(cfg)
        print(f"Configuring {len(pins)} pin(s)... ", end="", flush=True)
        print(ctrl.configure(pins).get("status", "no response"), "\n")

        light = cfg.get("sensor_light")
        if light:                               # light on so the sensor sees lit conditions
            ctrl.set_pwm(light["pin"], 255)

        *wb, white_c = calibrate(ctrl)
        print("Streaming RGB from TCS34725. Ctrl+C to stop.\n")

        step = 1.0 / SAMPLE_RATE
        try:
            while True:
                t0   = time.monotonic()
                data = ctrl.get_rgb()
                if data is None:
                    print("\rSensor error — check wiring or reflash.      ", end="", flush=True)
                else:
                    r, g, b = to_rgb8(data["r"], data["g"], data["b"], data["c"], tuple(wb), white_c)
                    swatch  = f"\033[48;2;{r};{g};{b}m      \033[0m"
                    print(f"\rR:{r:3d}  G:{g:3d}  B:{b:3d}  lux:{data['c']:5d}  {swatch}", end="", flush=True)
                elapsed = time.monotonic() - t0
                time.sleep(max(0.0, step - elapsed))
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
