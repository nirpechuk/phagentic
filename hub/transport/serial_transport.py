import json
import time
from typing import Optional

import serial
import serial.tools.list_ports

from .base import Transport


class SerialTransport(Transport):
    def __init__(self, port: str, baud_rate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self._serial: Optional[serial.Serial] = None

    def connect(self) -> None:
        self._serial = serial.Serial(self.port, self.baud_rate, timeout=self.timeout)
        time.sleep(2.0)                      # ESP32 resets on DTR; wait for boot
        self._serial.reset_input_buffer()    # flush bootloader noise

    def disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    def send(self, message: dict) -> None:
        line = json.dumps(message) + "\n"
        self._serial.write(line.encode())
        self._serial.flush()

    def receive(self, timeout: float = 1.0) -> Optional[dict]:
        self._serial.timeout = timeout
        raw = self._serial.readline()
        if not raw:
            return None
        try:
            return json.loads(raw.decode().strip())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @staticmethod
    def list_ports() -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]
