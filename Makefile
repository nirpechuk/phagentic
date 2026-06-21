# ── Config (override on the CLI: make upload PORT=/dev/cu.xxx) ──────────
BOARD  ?= esp32:esp32:esp32
PORT   ?= $(shell ls /dev/cu.usb* /dev/cu.SLAB* /dev/cu.wch* 2>/dev/null | head -1)
SKETCH := controller
VENV   := hub/.venv
PY     := $(VENV)/bin/python
UI_PORT ?= 5173

# Goal-seeking ML controller workflow (override on the CLI).
RUN  ?= runs/run-$(shell date +%Y%m%d-%H%M%S).jsonl
LOGS ?= runs/*.jsonl

# ────────────────────────────────────────────────────────────────────────
.PHONY: setup run backend dashboard ui chat upload detect test help \
        log-run fit replay probe

help:
	@echo ""
	@echo "  make backend    — headless control backend (BLE + analysis + ML + WebSocket API)"
	@echo "  make ui         — serve the PHAGENTIC web UI + open the browser"
	@echo "  make setup      — create Python venv and install deps"
	@echo "  make test       — run backend unit tests (no hardware needed)"
	@echo "  make chat       — start the ASK PHAGE assistant backend (needs ANTHROPIC_API_KEY)"
	@echo ""
	@echo "  Goal-seeking controller (see backend/GOAL_CONTROLLER.md):"
	@echo "  make log-run    — record the live state stream to a JSONL run log (RUN=path)"
	@echo "  make fit        — fit the grey-box ODE from logs → backend/sim/fitted_params.json (LOGS=glob)"
	@echo "  make replay     — offline sim-to-real check on a run log (RUN=path)"
	@echo "  make probe      — observe the live state stream (PROBE_ARGS='--model goal_blue')"
	@echo ""
	@echo "  make run        — [legacy] stream RGB to terminal (set BLE_DEVICE to override name)"
	@echo "  make dashboard  — [legacy] hub web dashboard with color + PWM sliders"
	@echo "  make upload     — compile + flash ESP32 (set PORT to override port)"
	@echo "  make detect     — list connected serial ports / boards"
	@echo ""

# Serve the static web UI (frontend/) and open it. Connects to the bioreactor
# over Web Bluetooth (the ⌁ connect button) or to the hub via ?backend=.
ui:
	@echo "PHAGENTIC UI → http://localhost:$(UI_PORT)/   (Ctrl+C to stop)"
	@cd frontend && node build.js
	@( sleep 1; (xdg-open "http://localhost:$(UI_PORT)/" || open "http://localhost:$(UI_PORT)/") >/dev/null 2>&1 & ) || true
	@cd frontend && python3 -m http.server $(UI_PORT)

setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r hub/requirements.txt -r backend/requirements.txt
	@echo "Done. Run 'make backend' to start the headless backend."

# Headless backend: owns the BLE link, oscillation analysis, the control loop,
# and the pluggable ML model. Serves the WebSocket + /config API (default :8080).
backend:
	@test -f $(PY) || (echo "Run 'make setup' first."; exit 1)
	$(PY) -m backend.app

test:
	@test -f $(PY) || (echo "Run 'make setup' first."; exit 1)
	$(PY) -m pytest backend/tests -q

# ── Goal-seeking controller workflow (no extra deps; pure-Python sim) ──────
# Record a run while the backend is up; override the path with RUN=...
log-run:
	@test -f $(PY) || (echo "Run 'make setup' first."; exit 1)
	$(PY) -m backend.tools.log_run --out $(RUN)

# Fit the grey-box ODE to logged runs → backend/sim/fitted_params.json.
# Override the input glob with LOGS='runs/a.jsonl runs/b.jsonl'.
fit:
	@test -f $(PY) || (echo "Run 'make setup' first."; exit 1)
	$(PY) -m backend.sim.fit $(LOGS)

# Offline sim-to-real check (phase slips + ODE prediction error) on one log.
# Pass the file: make replay RUN=runs/validation.jsonl
replay:
	@test -f $(PY) || (echo "Run 'make setup' first."; exit 1)
	$(PY) -m backend.tools.replay_eval $(RUN) --ode

# Observe / drive the live stream. e.g. make probe PROBE_ARGS='--set-params {"goal_blue":0.7}'
probe:
	@test -f $(PY) || (echo "Run 'make setup' first."; exit 1)
	$(PY) -m backend.tools.ws_probe $(PROBE_ARGS)

run:
	@test -f $(PY) || (echo "Run 'make setup' first."; exit 1)
	SERIAL_PORT=$(PORT) $(PY) hub/main.py

dashboard:
	@test -f $(PY) || (echo "Run 'make setup' first."; exit 1)
	SERIAL_PORT=$(PORT) $(PY) hub/dashboard.py

# ASK PHAGE assistant backend. Holds the Anthropic API key (so it never reaches the
# browser) and streams Claude's replies to the UI's chat panel. Set ANTHROPIC_API_KEY
# first; override the model with PHAGENTIC_CHAT_MODEL=claude-sonnet-4-6.
chat:
	@test -f $(PY) || (echo "Run 'make setup' first."; exit 1)
	$(PY) hub/chat_server.py

upload:
	@echo "Board: $(BOARD)   Port: $(PORT)"
	arduino-cli compile --fqbn $(BOARD) $(SKETCH)
	arduino-cli upload -p $(PORT) --fqbn $(BOARD) $(SKETCH)

detect:
	@echo "=== Serial ports ==="
	@ls /dev/cu.* 2>/dev/null || echo "  none"
	@echo ""
	@echo "=== arduino-cli boards ==="
	@arduino-cli board list
