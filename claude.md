# Bioreactor

ESP32 firmware + Python hub communicating over serial with newline-delimited JSON.

## Structure

- `controller/controller.ino` — Arduino firmware. Generic pin API; the pin registry is empty at boot and populated at runtime by the hub's `configure` command (no reflash to change pins). PWM pins use `ledcAttach`/`ledcWrite`, digital use `pinMode`/`digitalWrite`. Libraries: `ArduinoJson`, `Adafruit TCS34725`.
- `hub/config.json` — Single source of truth for wiring: list of MOSFETs (`name`, `pin`, `mode` = `pwm`/`digital`) plus optional `sensor_light` (`pin`, always PWM). Edit + restart the hub to add/rename/move a device.
- `hub/config.py` — Loads/validates `config.json`. `load_config`, `device_name` (env `BLE_DEVICE` wins), `pin_map` (flattened pin list for `configure`).
- `hub/controller.py` — Transport-agnostic ESP32 API (`ping`, `configure`, `set_pwm`, `set_digital`, `get_analog`, `get_rgb`).
- `hub/transport/ble_transport.py` — BLE transport (Nordic UART Service). Runs a `bleak` async loop in a daemon thread; exposes a synchronous `Transport` interface. Scans by device name, buffers incoming notifications, reassembles newline-delimited JSON.
- `hub/transport/serial_transport.py` — Legacy serial transport (kept for wired flashing/debug). 2 s boot wait on connect.
- `hub/main.py` — Terminal RGB stream: pushes config, turns sensor light on, white-balance calibration, then prints live color swatch + values at 20 Hz.
- `hub/dashboard.py` — Web dashboard (Flask, port 8080): live color swatch via SSE + controls built dynamically from `config.json` (slider per PWM MOSFET, on/off toggle per digital MOSFET, brightness slider for the sensor light). Same calibration flow as `main.py`.

## Protocol

Newline-delimited JSON over BLE Nordic UART Service (NUS). One command in, one reply out. Commands: `ping`, `configure` (pins: `[{pin, mode}]`; registers output pins, replacing the prior registry, replies `{status:ok, count:N}`), `set_pwm` (pin, value 0–255), `set_digital` (pin, value 0/1), `get_analog` (pin), `get_rgb` (returns raw uint16 r/g/b/c from TCS34725). The hub sends `configure` on connect; pins must be registered before `set_pwm`/`set_digital`. Unknown pin → `{"status":"error","msg":"unknown_pin"}`; PWM command on a digital pin → `not_pwm`.

BLE device name: `Bioreactor`. NUS RX `6E400002…` (host→device), TX `6E400003…` (device→host, notify). MTU set to 512 on firmware side.

## Hardware

- Output pins (MOSFETs, sensor light) are assigned in `hub/config.json`, not fixed in firmware. PWM is 5 kHz, 8-bit. GPIO 34–39 are input-only and can't be outputs.
- TCS34725 RGB sensor — SDA=21, SCL=22. 2.4 ms integration, 4× gain. Raw RGBC are uint16; normalize with IR correction (`IR=(R+G+B−C)/2`) then white-balance scale factors. The sensor LED pin wired to a GPIO is driven as the `sensor_light` PWM output.

## Commands

```
make setup      # create venv, install deps
make run        # terminal RGB stream
make dashboard  # web dashboard
make upload     # compile + flash ESP32
make detect     # list serial ports
```

Set `BLE_DEVICE` env var to override the BLE device name (default: from `config.json`, else `Bioreactor`). Set `BIOREACTOR_CONFIG` to point at a different config file. USB is still required for `make upload`.
