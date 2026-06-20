import asyncio
import json
import queue
import threading
from typing import Optional

from bleak import BleakClient, BleakScanner

from .base import Transport

# Nordic UART Service (NUS) UUIDs
_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # host → device (write)
_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # device → host (notify)


class BLETransport(Transport):
    def __init__(self, device_name: str = "Bioreactor"):
        self._name   = device_name
        self._loop   = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._client: Optional[BleakClient] = None
        self._queue:  queue.Queue           = queue.Queue()
        self._buf     = ""

    def _sync(self, coro, timeout: float = 30.0):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    def connect(self) -> None:
        self._sync(self._async_connect())

    def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            self._sync(self._client.disconnect())
        self._client = None

    def send(self, message: dict) -> None:
        data = (json.dumps(message) + "\n").encode()
        self._sync(self._client.write_gatt_char(_RX_UUID, data, response=True), timeout=5.0)

    def receive(self, timeout: float = 1.0) -> Optional[dict]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def _async_connect(self) -> None:
        print(f"Scanning for '{self._name}'...", end=" ", flush=True)
        device = await BleakScanner.find_device_by_name(self._name, timeout=10.0)
        if device is None:
            raise RuntimeError(f"BLE device '{self._name}' not found — is the ESP32 powered on?")
        self._client = BleakClient(device, disconnected_callback=self._on_disconnect)
        await self._client.connect()
        await self._client.start_notify(_TX_UUID, self._on_notify)

    def _on_notify(self, sender, data: bytearray) -> None:
        self._buf += data.decode("utf-8", errors="replace")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                try:
                    self._queue.put(json.loads(line))
                except json.JSONDecodeError:
                    pass

    def _on_disconnect(self, client: BleakClient) -> None:
        self._client = None
