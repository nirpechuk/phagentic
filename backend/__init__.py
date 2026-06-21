"""Headless bioreactor backend.

Owns the ESP32 link, oscillation analysis, the control loop, and a pluggable ML
model. Streams full reaction state to (and accepts commands from) thin clients
over a WebSocket. Run with: ``python -m backend.app`` from the repo root.
"""
