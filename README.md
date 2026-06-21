# PHAGENTIC

A closed-loop controller for the **Blue Bottle** oscillating reaction. PHAGENTIC
watches the live colour of the solution (blue ⇄ colorless), estimates the
oscillation state — amplitude, period, phase, stall risk — and drives the
stirrer and glucose pump to hold the rhythm.

The **brains run headless in Python.** A backend process owns the device link,
the oscillation analysis, the control loop, and a **pluggable ML model** that
drives the reaction. The web UI is a thin client: it renders the state the
backend streams and sends commands back, over a single WebSocket. This means the
control loop keeps running with no browser open, and you can drop in a real
model (sklearn / torch / an RL policy) without touching the rest of the system.

```
phagentic/
├── backend/              # headless control backend  ← the live system
│   ├── app.py            #   entrypoint: wires everything, serves uvicorn (python -m backend.app)
│   ├── server.py         #   FastAPI: /ws (state out + commands in) + GET /config
│   ├── hardware/         #   device.py (DeviceWorker loop), roles.py, calibration.py, _hublink.py
│   ├── analysis/         #   detector.py (oscillation extrema), signal.py
│   ├── control/          #   model.py (Model interface), pi_model.py, arbiter.py, registry.py
│   ├── state/            #   store.py (shared snapshot), commands.py, events.py
│   ├── protocol/         #   messages.py (WebSocket message vocabulary)
│   ├── tools/ws_probe.py #   headless WebSocket probe (verify without a browser)
│   └── tests/            #   unit tests (no hardware needed)
├── frontend/             # the web UI — a thin WebSocket client
│   ├── index.html        #   built console (build.js assembles it from src/)
│   ├── api.js            #   WebSocket bridge to the backend
│   ├── logic.js          #   UI component (rendering + command sending; no analysis)
│   ├── runtime.js        #   vendored React-based template renderer
│   └── src/              #   shell.html + widgets/*.html (built by build.js)
├── hub/                  # DEPRECATED. Its device layer (controller/transport/config) is
│                         #   reused by backend/; dashboard.py + main.py are legacy tools.
├── controller/           # ESP32 firmware (generic pin API; pins configured at runtime)
├── experiment.md         # the Blue Bottle experiment
└── Makefile              # make backend / ui / setup / test / upload
```

## Architecture

<img width="1245" height="764" alt="Architecture" src="https://github.com/user-attachments/assets/34d81900-0187-47e0-bde2-d6daf9978507" />

## WebSocket protocol (`ws://<host>:8080/ws`)

Every frame is JSON `{"type": ...}`.

| Direction | Messages |
|---|---|
| server → client | `state` (full snapshot + `narr_new[]`), `config` (layout/roles/models), `ack`, `calibration` |
| client → server | `set_actuator {role,value}`, `pulse_actuator {role,ms}`, `set_mode {mode}`, `set_model {name}`, `set_model_params {params}`, `recalibrate`, `reload_config`, `reset_run`, `ping` |

`role` ∈ `stirrer` · `light` (PWM 0–255) and `glucose` · `naoh` (digital pumps).
Roles resolve to physical pins from `hub/config.json` by name match, so pins can
move in config without code changes.

### What the UI sees and controls

- **Sees:** live solution colour (RGB swatch + lux), normalized blue intensity,
  oscillation waveform, amplitude, period/half-period, phase, cycle count, stall risk.
- **Controls:** Stirrer (PWM), Glucose pump (auto trigger + manual pulse, dose
  ms), NaOH pump (manual pulse), Sensor light (brightness), manual/auto/ml mode,
  model params, sensor recalibration, live config reload.

## Run it locally

```bash
make setup        # one-time: venv + deps (hub/.venv) for backend + hub
make backend      # headless backend on http://localhost:8080  (ws://localhost:8080/ws)
make ui           # web UI on http://localhost:5173  (UI_PORT=8000 to override)
```

Then open **http://localhost:5173/**. The UI connects to the backend over the
WebSocket and shows the hardware status in the header (**`⬡ HARDWARE`** when the
ESP32 is connected, **`◌ NO DEVICE`** when the backend is up but the device
isn't, **`◌ OFFLINE`** when the backend is unreachable — it auto-reconnects).

> First load needs internet (the renderer pulls React from a CDN).

Hardware: power on the bioreactor (ESP32 flashed with `controller/`, advertising
as `Bioreactor`). The backend scans for it on start and re-pushes the pin map +
re-asserts outputs on every reconnect.

### Verify without a browser

```bash
make test                                   # unit tests (detector, PI model, arbiter)
python -m backend.tools.ws_probe            # observe the live state stream
python -m backend.tools.ws_probe --mode auto
python -m backend.tools.ws_probe --set stirrer 200
```

### URL params (frontend)

- `?backend=ws://host:8080/ws` (or `http://host:8080`) — point the UI at a
  specific backend. Defaults to `ws://<page-host>:8080/ws`.
- `?view=console` — skip the landing page and open the console directly.

## Legacy: the `hub/` dashboard

`hub/` is deprecated as a UI but its device layer (`controller.py`, `transport/`,
`config.py`) is the reused, single source of truth for the wire protocol — the
backend imports it directly. The old wired tools still run if you need them:

```bash
make dashboard    # legacy Flask dashboard (hub/dashboard.py, :8080)
make run          # legacy terminal RGB stream (hub/main.py)
```

## Configuration

`hub/config.json` is the single source of truth for wiring: MOSFETs
(`name`, `pin`, `mode` = `pwm`/`digital`) plus optional `sensor_light`. Edit it
and either restart the backend or send `reload_config` from the UI. Set
`BLE_DEVICE` to override the device name, `BIOREACTOR_CONFIG` to point at a
different config file, and `PORT` to change the backend port.
