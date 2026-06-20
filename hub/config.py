"""Loads the bioreactor hardware config (MOSFETs + sensor light) from config.json.

The config is the single source of truth for what's wired to the ESP32. On connect the
hub pushes the pin map to the firmware (see Controller.configure), so adding, renaming, or
moving a MOSFET is just an edit here + a hub restart — no reflash.

Note: ESP32 GPIO 34-39 are input-only and cannot be used as outputs.
"""
import json
import os

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "config.json")
_VALID_MODES = ("pwm", "digital")
# TCS34725 I2C pins are fixed in firmware (Wire.begin(21, 22)) — reflash to change.
_DEFAULT_SENSOR = {"name": "TCS34725", "sda": 21, "scl": 22}


def load_config(path: str | None = None) -> dict:
    """Read and validate config.json. Path overridable via BIOREACTOR_CONFIG env var."""
    path = path or os.environ.get("BIOREACTOR_CONFIG", _DEFAULT_PATH)
    with open(path) as f:
        cfg = json.load(f)

    seen: dict[int, str] = {}
    for m in cfg.get("mosfets", []):
        if m.get("mode") not in _VALID_MODES:
            raise ValueError(f"mosfet {m.get('name')!r}: mode must be one of {_VALID_MODES}")
        _claim_pin(seen, m["pin"], m.get("name", "mosfet"))

    light = cfg.get("sensor_light")
    if light is not None:
        _claim_pin(seen, light["pin"], "sensor_light")

    s = sensor_info(cfg)
    _claim_pin(seen, s["sda"], f"{s['name']} SDA")
    _claim_pin(seen, s["scl"], f"{s['name']} SCL")

    return cfg


def _claim_pin(seen: dict[int, str], pin: int, owner: str) -> None:
    if pin in seen:
        raise ValueError(f"pin {pin} assigned to both {seen[pin]!r} and {owner!r}")
    seen[pin] = owner


def device_name(cfg: dict) -> str:
    """BLE device name. The BLE_DEVICE env var still takes precedence."""
    return os.environ.get("BLE_DEVICE") or cfg.get("ble_device", "Bioreactor")


def sensor_info(cfg: dict) -> dict:
    """Sensor name + I2C pins for the wiring diagram. Optional `sensor` block in config.json
    overrides the defaults; the pins must match the firmware's Wire.begin()."""
    return {**_DEFAULT_SENSOR, **(cfg.get("sensor") or {})}


def pin_map(cfg: dict) -> list[dict]:
    """Flattened [{"pin", "mode"}] for every output (MOSFETs + sensor light) to register
    on the firmware. The sensor light is always PWM (brightness slider)."""
    pins = [{"pin": m["pin"], "mode": m["mode"]} for m in cfg.get("mosfets", [])]
    light = cfg.get("sensor_light")
    if light is not None:
        pins.append({"pin": light["pin"], "mode": "pwm"})
    return pins
