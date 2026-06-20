# ── Config (override on the CLI: make upload PORT=/dev/cu.xxx) ──────────
BOARD  ?= esp32:esp32:esp32
PORT   ?= $(shell ls /dev/cu.usb* /dev/cu.SLAB* /dev/cu.wch* 2>/dev/null | head -1)
SKETCH := controller
VENV   := hub/.venv
PY     := $(VENV)/bin/python

# ────────────────────────────────────────────────────────────────────────
.PHONY: setup run dashboard upload detect help

help:
	@echo ""
	@echo "  make setup      — create Python venv and install deps"
	@echo "  make run        — stream RGB to terminal (set BLE_DEVICE to override name)"
	@echo "  make dashboard  — open web dashboard with color + PWM sliders"
	@echo "  make upload     — compile + flash ESP32 (set PORT to override port)"
	@echo "  make detect     — list connected serial ports / boards"
	@echo ""

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
