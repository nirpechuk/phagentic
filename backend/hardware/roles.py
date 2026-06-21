"""Resolve logical roles (stirrer/glucose/naoh/light) to physical pins.

Port of frontend/logic.js pinsFromConfig (:98-105): match config MOSFET names so
the control loop follows the actual wiring even when pins move in config.json.
The sensor light is always the PWM light role.
"""
import re

ROLES = ("stirrer", "glucose", "naoh", "light")
DIGITAL_ROLES = ("glucose", "naoh")  # pumps: hard ON/OFF + momentary pulses
PWM_ROLES = ("stirrer", "light")


class RoleMap:
    def __init__(self, cfg: dict):
        self.load(cfg)

    def load(self, cfg: dict) -> None:
        pins: dict[str, int] = {}
        modes: dict[str, str] = {}
        names = {
            "stirrer": "Stirrer", "glucose": "Glucose Pump",
            "naoh": "NaOH Pump", "light": "Sensor Light",
        }
        for m in cfg.get("mosfets", []):
            n = (m.get("name") or "").lower()
            role = None
            if "stir" in n:
                role = "stirrer"
            elif "gluc" in n:
                role = "glucose"
            elif re.search(r"na.?oh|chlor", n):
                role = "naoh"
            if role:
                pins[role] = m["pin"]
                modes[role] = m.get("mode", "digital" if role in DIGITAL_ROLES else "pwm")
                names[role] = m.get("name", names[role])
        light = cfg.get("sensor_light")
        if light and light.get("pin") is not None:
            pins["light"] = light["pin"]
            modes["light"] = "pwm"
            if light.get("name"):
                names["light"] = light["name"]
        self.pins = pins
        self.modes = modes
        self.names = names

    def pin_of(self, role: str):
        return self.pins.get(role)

    def mode_of(self, role: str) -> str:
        return self.modes.get(role, "digital" if role in DIGITAL_ROLES else "pwm")

    def has(self, role: str) -> bool:
        return role in self.pins
