# ── Config (override on the CLI: make upload PORT=/dev/cu.xxx) ──────────
BOARD  ?= esp32:esp32:esp32
PORT   ?= $(shell ls /dev/cu.usb* /dev/cu.SLAB* /dev/cu.wch* 2>/dev/null | head -1)
SKETCH := controller
VENV   := hub/.venv
PY     := $(VENV)/bin/python
UI_PORT ?= 5173

# ────────────────────────────────────────────────────────────────────────
.PHONY: setup run dashboard ui upload detect help

help:
	@echo ""
	@echo "  make ui         — serve the PHAGENTIC web UI + open the browser"
	@echo "  make setup      — create Python venv and install deps"
	@echo "  make run        — stream RGB to terminal (set BLE_DEVICE to override name)"
	@echo "  make dashboard  — open web dashboard with color + PWM sliders"
	@echo "  make upload     — compile + flash ESP32 (set PORT to override port)"
	@echo "  make detect     — list connected serial ports / boards"
	@echo ""

# Serve the static web UI (frontend/) and open it. Connects to the bioreactor
# over Web Bluetooth (the ⌁ connect button) or to the hub via ?backend=.
ui:
	@echo "PHAGENTIC UI → http://localhost:$(UI_PORT)/   (Ctrl+C to stop)"
	@( sleep 1; (xdg-open "http://localhost:$(UI_PORT)/" || open "http://localhost:$(UI_PORT)/") >/dev/null 2>&1 & ) || true
	@cd frontend && python3 -m http.server $(UI_PORT)

setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r hub/requirements.txt
	@echo "Done. Run 'make run' to start the hub."

run:
	@test -f $(PY) || (echo "Run 'make setup' first."; exit 1)
	SERIAL_PORT=$(PORT) $(PY) hub/main.py

dashboard:
	@test -f $(PY) || (echo "Run 'make setup' first."; exit 1)
	SERIAL_PORT=$(PORT) $(PY) hub/dashboard.py

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
