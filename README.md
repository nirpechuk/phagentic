# PHAGENTIC

A closed-loop controller for the **Blue Bottle** oscillating reaction. PHAGENTIC
watches the live colour of the solution (blue ⇄ colorless), estimates the
oscillation state — amplitude, period, phase, stall risk — and drives the
stirrer and glucose pump to hold the rhythm.

```
phagentic/
├── frontend/          # the web UI (this is the product UI)
│   ├── index.html     # the console — template + control logic
│   ├── runtime.js     # vendored React-based template renderer
│   ├── api.js         # bridge to the Python hub (SSE + REST)
│   └── ble.js         # direct Web Bluetooth link to the ESP32 (no hub)
├── hub/               # Python hub: BLE/serial ↔ ESP32  (UNCHANGED)
├── controller/        # ESP32 firmware                  (UNCHANGED)
├── experiment.md      # the Blue Bottle experiment
├── run.sh             # one-shot: serve the UI + open the browser
└── Makefile           # make ui / setup / run / dashboard / upload
```

## Two ways to reach the hardware

The UI can talk to the bioreactor **either** through the Python hub **or**
directly over Bluetooth from the browser — both untouched-backend paths:

1. **Via the hub** (`api.js`) — Flask SSE/REST, below. Good when the hub is
   already running or the browser has no BLE.
2. **Direct Web Bluetooth** (`ble.js`) — click **`⌁ connect`** in the header.
   The browser pairs with the `Bioreactor` over the Nordic UART Service and runs
   the hub's exact protocol (`ping` · `configure` · `set_pwm` · `set_digital` ·
   `get_analog` · `get_rgb`) itself — **no Python needed**. It configures the
   pins, turns on the sensor light, and polls `get_rgb` at 20 Hz. Requires Chrome
   over **https or localhost** and a click to grant the device.

The header shows the active source: **`⌁ BLUETOOTH`**, **`⬡ HARDWARE`** (hub),
or **`◌ SIMULATION`** (built-in, no hardware).

The `hub/` and `controller/` are the existing backend and are **not modified by
the UI** — the frontend adapts to the hub's existing HTTP surface.

## How the UI connects to the hub

The hub (`hub/dashboard.py`, Flask, port **8080**) already exposes everything the
UI needs, so the frontend talks to it directly:

| Hub endpoint | Used by the UI for |
|---|---|
| `GET /stream` (SSE) | live sensor colour `{r,g,b,lux}` at ~20 Hz |
| `GET /config` | device/pin layout → resolves Stirrer / Glucose / NaOH / Light pins |
| `POST /set` `{cmd,pin,value}` | every actuator command (PWM + digital) |
| `POST /recalibrate` | white-balance the sensor from the UI |
| `POST /reload_config` | re-read `config.json` on the hub |

All oscillation analysis and the auto control loop (PI on the stirrer + glucose
pulse on amplitude decay) run **in the browser**; the hub stays a thin sensor +
actuator relay. The header shows the data source: **`⬡ HARDWARE`** when the hub
is reachable, **`◌ SIMULATION`** when it isn't (a built-in Blue Bottle
simulation keeps the console live with no hardware attached).

### What the UI sees and controls

- **Sees:** live solution colour (RGB swatch + lux), normalized blue intensity,
  oscillation waveform, amplitude, period/half-period, phase, cycle count, stall risk.
- **Controls:** Stirrer (PWM), Glucose pump (auto trigger + manual `⟢ PULSE`,
  dose ms), NaOH/Chloride pump (manual pulse), Sensor light (brightness),
  auto/manual policy, target half-period solver, sensor recalibration.

## Run it locally

Pick whichever is handiest — all three serve `frontend/` on
`http://localhost:5173` and open it:

```bash
./run.sh          # bash launcher (does everything; ./run.sh 8000 for another port)
# or
make ui           # same thing via the Makefile (UI_PORT=8000 to override)
# or
cd frontend && python3 -m http.server 5173
```

Then open **http://localhost:5173/**. With no hardware connected it runs a
built-in simulation, so the console is never blank.

### Connect over Bluetooth (no hub needed)

The browser talks straight to the ESP32 over Bluetooth — the Python hub does not
need to be running.

1. Power on the bioreactor (ESP32 flashed with `controller/`, advertising as
   `Bioreactor`).
2. Open the UI in **Chrome or Edge** at `http://localhost:5173/`
   (Web Bluetooth needs Chrome/Edge over **https or localhost** — `localhost`
   counts, so the local server is fine; Firefox/Safari are not supported).
3. Click **`⌁ connect`** in the header (or **⚙ settings → Connect**) and pick
   `Bioreactor`. The header switches to **`⌁ BLUETOOTH`** and streams the live
   colour at 20 Hz. The first connect needs one click to grant the device;
   after that it reconnects automatically.

> First load needs internet (the renderer pulls React from a CDN).

### Connect via the Python hub (alternative)

```bash
make setup && make dashboard          # hub on http://localhost:8080
make ui                               # UI on http://localhost:5173
# open http://localhost:5173/?backend=http://localhost:8080
```

URL params:

- `?backend=http://host:8080` — point the UI at a specific hub (otherwise it uses
  the page's own origin, falling back to `localhost:8080` for `file://`).
- `?view=console` — skip the landing page and open the console directly.
