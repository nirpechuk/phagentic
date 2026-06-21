"""DeviceWorker — the only thread that touches the Controller.

Runs a fixed-rate loop: handle reload/recalibrate events → drain commands →
read sensor → analyse → arbiter decides → apply (diffed) → publish state. Also
supervises BLE reconnect (re-pushing the pin map + re-asserting outputs, since
firmware loses its pin registry on reset) and drives actuators to a safe state
on shutdown. Mirrors the loop/queue/event pattern of hub/dashboard.py.
"""
import logging
import time

from backend.analysis.detector import Detector
from backend.analysis.signal import blue_from_rgb, clamp
from backend.control.arbiter import ControlArbiter
from backend.control.model import ReactionState
from backend.control.registry import list_models
from backend.hardware import calibration
from backend.hardware._hublink import BLETransport, Controller, config
from backend.hardware.roles import RoleMap
from backend.state.commands import (
    CommandQueue, PULSE_ACTUATOR, RESET_RUN, SET_ACTUATOR, SET_MODE,
    SET_MODEL, SET_MODEL_PARAMS,
)
from backend.state.events import DeviceEvents
from backend.state.store import StateStore

log = logging.getLogger("backend.device")


class DeviceWorker:
    def __init__(
        self,
        cfg: dict,
        store: StateStore,
        commands: CommandQueue,
        events: DeviceEvents,
        arbiter: ControlArbiter,
        detector: Detector,
        roles: RoleMap,
        loop_hz: int = 20,
        reconnect_interval: float = 2.0,
    ):
        self.cfg = cfg
        self.store = store
        self.commands = commands
        self.events = events
        self.arbiter = arbiter
        self.detector = detector
        self.roles = roles
        self.step = 1.0 / loop_hz
        self.reconnect_interval = reconnect_interval

        self.transport = BLETransport(config.device_name(cfg))
        self.ctrl = Controller(self.transport)
        self._connected = False
        self._t0: float | None = None
        self._wb = (1.0, 1.0, 1.0)
        self._white_c = 1.0
        self._last_applied: dict[str, int] = {}

    # ── public layout (served by GET /config) ────────────────────────────────
    def layout(self) -> dict:
        return {
            "mosfets": self.cfg.get("mosfets", []),
            "sensor_light": self.cfg.get("sensor_light"),
            "sensor": config.sensor_info(self.cfg),
            "roles": {r: {"pin": self.roles.pin_of(r), "mode": self.roles.mode_of(r),
                          "name": self.roles.names.get(r)}
                      for r in self.roles.pins},
            "models": list_models(),
        }

    # ── main loop ─────────────────────────────────────────────────────────────
    def run(self) -> None:
        self.store.update(models=list_models())
        try:
            while not self.events.shutdown_req.is_set():
                t_start = time.monotonic()
                # Mode/model/manual-setpoint commands don't need the device, so
                # drain them every loop — even while reconnecting — rather than
                # starving them behind the BLE link.
                self._drain_commands()
                self._publish_meta()
                if not self._connected:
                    self._try_reconnect()
                    if not self._connected:
                        continue   # _try_reconnect already paced itself
                if not self._service_once():
                    continue
                time.sleep(max(0.0, self.step - (time.monotonic() - t_start)))
        finally:
            self._safe_shutdown()
            self.events.shutdown_done.set()

    def _service_once(self) -> bool:
        """One tick. Returns False if it bailed early (disconnect/no data)."""
        try:
            self._handle_events()
            raw = self.ctrl.get_rgb()
        except Exception:
            log.warning("device I/O failed — marking disconnected", exc_info=True)
            self._mark_disconnected()
            return False

        if raw is None:
            if not self.transport.is_connected():
                self._mark_disconnected()
            return False

        now = time.monotonic()
        t = now - (self._t0 or now)
        r8, g8, b8 = calibration.to_rgb8(raw["r"], raw["g"], raw["b"], raw["c"],
                                         self._wb, self._white_c)
        blue = blue_from_rgb(r8, g8, b8, raw["c"])
        reading = self.detector.update(t, blue)

        state = ReactionState(
            t=t, now=now, blue=blue, rgb=(r8, g8, b8), lux=raw["c"],
            amp=reading.amp, half_period=reading.half_period, period=reading.period,
            cycles=reading.cycles, phase=reading.phase, cycle_event=reading.cycle_event,
            last_stirrer=self._last_applied.get("stirrer", self.arbiter.desired["stirrer"]),
            last_light=self._last_applied.get("light", self.arbiter.desired["light"]),
        )
        desired, notes = self.arbiter.step(state, now)
        self._apply(desired)
        for n in notes:
            self.store.push_narr(n, "warn")

        stall = clamp((t - reading.last_extreme_t) / 90.0, 0.0, 1.0)
        self.store.update(
            t=round(t, 2), blue=round(blue, 4), rgb=[r8, g8, b8], lux=raw["c"],
            amp=round(reading.amp, 4), period=round(reading.period, 2),
            half_period=round(reading.half_period, 2), phase=reading.phase,
            cycles=reading.cycles, stall_risk=round(stall, 3),
            stirrer_out=desired["stirrer"], light_out=desired["light"],
            glucose_active=bool(desired["glucose"]), naoh_active=bool(desired["naoh"]),
            glucose_pulses=self.arbiter.glucose_pulses, last_pulse_t=self.arbiter.last_pulse_t,
            mode=self.arbiter.mode, model_name=self.arbiter.model_name(),
            model_params=self.arbiter.model_params(), model_error=self.arbiter.model_error,
            ble="connected",
        )
        return True

    def _publish_meta(self) -> None:
        """Mirror arbiter/mode state to the store every loop so mode, model and
        desired outputs reach the UI immediately — even while reconnecting."""
        d = self.arbiter.desired
        self.store.update(
            mode=self.arbiter.mode, model_name=self.arbiter.model_name(),
            model_params=self.arbiter.model_params(), model_error=self.arbiter.model_error,
            stirrer_out=d["stirrer"], light_out=d["light"],
            glucose_active=bool(d["glucose"]), naoh_active=bool(d["naoh"]),
            glucose_pulses=self.arbiter.glucose_pulses, last_pulse_t=self.arbiter.last_pulse_t,
        )

    # ── events (reload / recalibrate) ─────────────────────────────────────────
    def _handle_events(self) -> None:
        if self.events.reload_req.is_set():
            self.events.reload_req.clear()
            try:
                self.cfg = config.load_config()
                self.roles.load(self.cfg)
                self.ctrl.configure(config.pin_map(self.cfg))
                light = self.cfg.get("sensor_light")
                if light:
                    self.ctrl.set_pwm(light["pin"], self.arbiter.desired["light"])
                self._last_applied.clear()   # force re-assert against new wiring
                self.store.update(models=list_models())
                self.store.push_narr("Config reloaded.", "info")
            except Exception as e:
                self.store.push_narr(f"Config reload failed: {e}", "warn")
            self.events.reload_done.set()

        if self.events.recalib_req.is_set():
            self.events.recalib_req.clear()
            self.store.push_narr("Recalibrating white balance…", "dim")
            *wb, white_c = calibration.sample_wb(self.ctrl)
            self._wb, self._white_c = tuple(wb), white_c
            self.events.wb, self.events.white_c = self._wb, white_c
            self.store.push_narr("White balance updated.", "win")
            self.events.recalib_done.set()

    # ── commands ──────────────────────────────────────────────────────────────
    def _drain_commands(self) -> None:
        now = time.monotonic()
        t = now - (self._t0 or now)
        for cmd in self.commands.drain():
            p = cmd.payload
            try:
                if cmd.type == SET_ACTUATOR:
                    self.arbiter.apply_manual(p["role"], p["value"])
                elif cmd.type == PULSE_ACTUATOR:
                    self.arbiter.request_pulse(p["role"], int(p.get("ms", 500)), now, t)
                elif cmd.type == SET_MODE:
                    self.arbiter.set_mode(p["mode"])
                    self.store.push_narr(f"Mode → {p['mode']}.", "info")
                elif cmd.type == SET_MODEL:
                    self.arbiter.set_ml_model(p["name"])
                    self.store.push_narr(f"Model → {p['name']}.", "info")
                elif cmd.type == SET_MODEL_PARAMS:
                    self.arbiter.set_model_params(p.get("params", {}))
                elif cmd.type == RESET_RUN:
                    self.detector.reset()
                    self.arbiter.reset_models()
                    self._t0 = now
                    self.store.push_narr("Run reset.", "info")
            except Exception as e:
                log.warning("command %s failed: %s", cmd.type, e)
                self.store.push_narr(f"Command {cmd.type} failed: {e}", "warn")

    # ── actuator application (diffed) ─────────────────────────────────────────
    def _apply(self, desired: dict) -> None:
        for role, value in desired.items():
            pin = self.roles.pin_of(role)
            if pin is None or self._last_applied.get(role) == value:
                continue
            try:
                if self.roles.mode_of(role) == "digital":
                    self.ctrl.set_digital(pin, bool(value))
                else:
                    self.ctrl.set_pwm(pin, int(value))
                self._last_applied[role] = value
            except Exception:
                log.warning("apply %s failed — marking disconnected", role, exc_info=True)
                self._mark_disconnected()
                return

    # ── connection lifecycle ──────────────────────────────────────────────────
    def _try_reconnect(self) -> None:
        self.store.update(ble="reconnecting")
        name = config.device_name(self.cfg)
        try:
            if not self.transport.is_connected():
                log.info("connecting to BLE device %r…", name)
                self.ctrl.connect()
            if not self.ctrl.ping():
                raise RuntimeError("no ping reply")
            pins = config.pin_map(self.cfg)
            self.ctrl.configure(pins)
            light = self.cfg.get("sensor_light")
            if light:
                self.ctrl.set_pwm(light["pin"], self.arbiter.desired["light"])
            self._last_applied.clear()        # re-assert every output on (re)connect
            self.detector.reset()             # avoid a giant period across the gap
            self._t0 = time.monotonic()
            self._connected = True
            self.store.update(ble="connected")
            self.store.push_narr("BLE connected — streaming.", "win")
            log.info("BLE connected to %r — configured %d pin(s), streaming at %d Hz",
                     name, len(pins), round(1.0 / self.step))
        except Exception as e:
            self._connected = False
            self.store.update(ble="disconnected")
            log.warning("BLE connect to %r failed: %s — retrying in %.0fs "
                        "(is the ESP32 powered on and not already connected elsewhere?)",
                        name, e, self.reconnect_interval)
            time.sleep(self.reconnect_interval)

    def _mark_disconnected(self) -> None:
        if self._connected:
            log.warning("BLE link lost — will attempt to reconnect")
            self.store.push_narr("BLE link lost — reconnecting…", "warn")
        self._connected = False
        self._last_applied.clear()
        self.store.update(ble="disconnected")

    # ── shutdown safety ───────────────────────────────────────────────────────
    def _safe_shutdown(self) -> None:
        """Drive actuators to a safe state, then disconnect — on this thread,
        which owns the transport. Runs even if the loop crashed."""
        try:
            if self.transport.is_connected():
                for role in ("stirrer", "glucose", "naoh"):
                    pin = self.roles.pin_of(role)
                    if pin is None:
                        continue
                    if self.roles.mode_of(role) == "digital":
                        self.ctrl.set_digital(pin, False)
                    else:
                        self.ctrl.set_pwm(pin, 0)
                self.ctrl.disconnect()
                log.info("actuators zeroed, BLE disconnected")
        except Exception:
            log.warning("safe shutdown incomplete", exc_info=True)
