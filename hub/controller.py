from typing import Optional

from transport.base import Transport


class Controller:
    """High-level ESP32 API. Transport-agnostic — pass any Transport subclass."""

    def __init__(self, transport: Transport):
        self.transport = transport

    def connect(self) -> None:
        self.transport.connect()

    def disconnect(self) -> None:
        self.transport.disconnect()

    def ping(self) -> bool:
        self.transport.send({"cmd": "ping"})
        resp = self.transport.receive()
        return resp is not None and resp.get("status") == "pong"

    def configure(self, pins: list[dict]) -> dict:
        """Register output pins on the device, replacing any prior registry.
        pins: [{"pin": int, "mode": "pwm"|"digital"}]"""
        self.transport.send({"cmd": "configure", "pins": pins})
        return self.transport.receive() or {}

    def set_pwm(self, pin: int, value: int) -> dict:
        """Set PWM duty cycle on a pin. value: 0-255."""
        self.transport.send({"cmd": "set_pwm", "pin": pin, "value": value})
        return self.transport.receive() or {}

    def set_digital(self, pin: int, value: bool) -> dict:
        self.transport.send({"cmd": "set_digital", "pin": pin, "value": int(value)})
        return self.transport.receive() or {}

    def get_analog(self, pin: int) -> Optional[int]:
        self.transport.send({"cmd": "get_analog", "pin": pin})
        resp = self.transport.receive()
        return resp.get("value") if resp else None

    def get_rgb(self) -> Optional[dict]:
        """Returns raw RGBC dict from TCS34725, or None on failure."""
        self.transport.send({"cmd": "get_rgb"})
        resp = self.transport.receive()
        if resp and resp.get("status") == "ok":
            return {"r": resp["r"], "g": resp["g"], "b": resp["b"], "c": resp["c"]}
        return None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()
