# Bioreactor

Closed-loop controller for the Blue Bottle oscillating reaction. The **brains run headless in Python** (`backend/`): a backend process owns the ESP32 link, the oscillation analysis, the control loop, and a pluggable ML model, and serves a WebSocket API. The web UI (`frontend/`) is a thin client — it renders streamed state and sends commands. ESP32 firmware is `controller/`. The `hub/` is deprecated as a UI but its device layer is reused by the backend.

## Structure

### `backend/` — the live headless system (run: `python -m backend.app`, port 8080)

- `backend/app.py` — entrypoint. Loads config, builds the pieces, starts the DeviceWorker thread, serves uvicorn. Registers a shutdown hook that drives actuators safe.
- `backend/server.py` — FastAPI app. `/ws` WebSocket (broadcasts full state ~15 Hz, accepts commands) + `GET /config` (hardware layout + roles + model list). Inbound handlers validate then enqueue/set-event; they never touch the device.
- `backend/hardware/device.py` — `DeviceWorker`: the **only** thread that touches the Controller. 20 Hz loop: handle reload/recalibrate events → drain commands → `get_rgb` → analyse → arbiter decides → apply (diffed) → publish to StateStore. Supervises BLE reconnect (re-pushes pin map + re-asserts outputs) and zeroes actuators on shutdown.
- `backend/hardware/roles.py` — `RoleMap`: resolves logical roles (`stirrer`/`glucose`/`naoh`/`light`) to pins by config name match (ported from the old browser logic).
- `backend/hardware/calibration.py` — `sample_wb` + `to_rgb8` colour math (moved from `hub/dashboard.py`).
- `backend/hardware/_hublink.py` — adds `hub/` to `sys.path` and re-exports `Controller`, `BLETransport`, `config` (zero edits to `hub/`).
- `backend/analysis/detector.py` — `Detector`: extrema detection on the blue signal → amplitude, half/period, cycle count, phase (ported from the browser).
- `backend/control/model.py` — the pluggable `Model` interface: `observe(ReactionState) -> Action`, plus `get_params`/`set_params`/`reset`.
- `backend/control/pi_model.py` — `PIModel` baseline (PI on stirrer + auto glucose pulse). `arbiter.py` — mode machine (manual/auto/ml) + pump-pulse timer + Action→actuator merge; contains model exceptions. `registry.py` — name→Model factory for `ml` mode.
- `backend/state/` — `store.py` (thread-safe shared snapshot), `commands.py` (queue), `events.py` (recalibrate/reload/shutdown event pairs).
- `backend/protocol/messages.py` — WebSocket message-type constants for both directions.
- `backend/tools/ws_probe.py` — headless WebSocket probe; `backend/tests/` — unit tests (no hardware).

### `frontend/` — thin WebSocket client

- `frontend/api.js` — `PhagenticBackend`: WebSocket bridge (`ws://host:8080/ws`). Routes `state`/`config`/`calibration` to callbacks; exposes `setActuator`/`pulseActuator`/`setMode`/`setModelParams`/`reloadConfig`/`resetRun`/`recalibrate`. Auto-reconnects.
- `frontend/logic.js` — UI component. `applyState(msg)` mirrors backend state into render state + builds the waveform/narration locally; all controls send WS commands. No analysis, control, or simulation runs in the browser.
- `frontend/build.js` assembles `index.html` from `src/shell.html` + `src/widgets/*.html` (run `node build.js` / `make ui`). `runtime.js` is the vendored React renderer.

### `controller/` + `hub/` (reused device layer)

- `controller/controller.ino` — Arduino firmware. Generic pin API; the pin registry is empty at boot and populated at runtime by the `configure` command (no reflash to change pins). PWM pins use `ledcAttach`/`ledcWrite`, digital use `pinMode`/`digitalWrite`. Libraries: `ArduinoJson`, `Adafruit TCS34725`.
- `hub/config.json` — Single source of truth for wiring: list of MOSFETs (`name`, `pin`, `mode` = `pwm`/`digital`) plus optional `sensor_light` (`pin`, always PWM). Edit + restart the backend (or send `reload_config`) to add/rename/move a device.
- `hub/config.py` — Loads/validates `config.json`. `load_config`, `device_name` (env `BLE_DEVICE` wins), `pin_map`, `sensor_info`.
- `hub/controller.py` — Transport-agnostic ESP32 API (`ping`, `configure`, `set_pwm`, `set_digital`, `get_analog`, `get_rgb`). Synchronous; reused by the backend.
- `hub/transport/ble_transport.py` — BLE transport (Nordic UART Service). Runs a `bleak` async loop in a daemon thread; exposes a synchronous `Transport`. Scans by device name, reassembles newline-delimited JSON.
- `hub/transport/serial_transport.py` — Legacy serial transport (wired flashing/debug). `hub/dashboard.py` + `hub/main.py` — **deprecated** legacy tools (Flask SSE dashboard / terminal RGB stream); still runnable via `make dashboard` / `make run`.

## Protocol

Two protocols. **Backend ↔ ESP32** (device link): newline-delimited JSON over BLE Nordic UART Service (NUS). One command in, one reply out. Commands: `ping`, `configure` (pins: `[{pin, mode}]`; registers output pins, replacing the prior registry, replies `{status:ok, count:N}`), `set_pwm` (pin, value 0–255), `set_digital` (pin, value 0/1), `get_analog` (pin), `get_rgb` (returns raw uint16 r/g/b/c from TCS34725). The backend sends `configure` on connect and re-pushes it on every BLE reconnect (firmware loses its pin registry on reset); pins must be registered before `set_pwm`/`set_digital`. Unknown pin → `{"status":"error","msg":"unknown_pin"}`; PWM command on a digital pin → `not_pwm`.

BLE device name: `Bioreactor`. NUS RX `6E400002…` (host→device), TX `6E400003…` (device→host, notify). MTU set to 512 on firmware side.

**Frontend ↔ backend** (`ws://host:8080/ws`): JSON frames `{"type": ...}`. Server→client: `state` (full snapshot + `narr_new[]`), `config`, `ack`, `calibration`. Client→server: `set_actuator {role,value}`, `pulse_actuator {role,ms}`, `set_mode {mode}` (manual/auto/ml), `set_model {name}`, `set_model_params {params}`, `recalibrate`, `reload_config`, `reset_run`, `ping`. Roles (`stirrer`/`light` PWM, `glucose`/`naoh` digital) resolve to pins from `config.json`. `GET /config` (REST) returns the layout for initial load.

## Hardware

- Output pins (MOSFETs, sensor light) are assigned in `hub/config.json`, not fixed in firmware. PWM is 5 kHz, 8-bit. GPIO 34–39 are input-only and can't be outputs.
- TCS34725 RGB sensor — SDA=21, SCL=22. 2.4 ms integration, 4× gain. Raw RGBC are uint16; normalize with IR correction (`IR=(R+G+B−C)/2`) then white-balance scale factors. The sensor LED pin wired to a GPIO is driven as the `sensor_light` PWM output.

## Commands

```
make setup      # create venv, install deps (backend + hub)
make backend    # headless control backend (BLE + analysis + ML + WebSocket API, :8080)
make ui         # build + serve the web UI (:5173)
make test       # backend unit tests (no hardware)
make upload     # compile + flash ESP32
make detect     # list serial ports
make dashboard  # [legacy] hub Flask dashboard
make run        # [legacy] terminal RGB stream
```

Headless verification without a browser: `python -m backend.tools.ws_probe` (observe the state stream; `--mode`, `--set ROLE VALUE`, `--pulse ROLE MS`).

Set `BLE_DEVICE` to override the BLE device name (default: from `config.json`, else `Bioreactor`). Set `BIOREACTOR_CONFIG` to point at a different config file, and `PORT` to change the backend port. USB is still required for `make upload`.
