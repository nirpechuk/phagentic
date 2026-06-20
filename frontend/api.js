// PHAGENTIC — bridge to the existing Python hub (hub/dashboard.py), unchanged.
//
// The hub is a Flask server (default port 8080) that talks to the ESP32
// bioreactor over BLE. The frontend adapts to it exactly as it is:
//
//   GET  /stream   Server-Sent Events, ~20 Hz:  { r, g, b, lux }
//                  (white-balanced 0-255 swatch colour + clear-channel lux)
//   GET  /config   { mosfets:[{name,pin,mode}], sensor_light:{pin}, sensor:{...} }
//   POST /set      { cmd:"set_pwm"|"set_digital", pin:int, value:int }
//   POST /recalibrate
//   POST /reload_config
//
// All oscillation analysis and the auto control loop live in the UI; the hub
// stays a thin sensor + actuator relay. When the hub is unreachable the UI runs
// a built-in simulation so the console is never blank.
(function () {
  "use strict";

  function resolveBase() {
    if (window.PHAGENTIC_BACKEND) return window.PHAGENTIC_BACKEND.replace(/\/$/, "");
    var override = new URLSearchParams(location.search).get("backend");
    if (override) return override.replace(/\/$/, "");
    // Served from the hub itself -> same origin. Opened as a file -> default to
    // the hub's default address.
    if (location.protocol === "file:" || !location.host) return "http://localhost:8080";
    return location.origin;
  }

  function Backend() {
    this.base = resolveBase();
    this.es = null;
    this.connected = false;
    this.config = null;
    this.onSensor = null; // ({r,g,b,lux}) => void
    this.onConfig = null; // (layout) => void
    this.onStatus = null; // (connected:boolean) => void
    this._retry = null;
    this._closed = false;
  }

  Backend.prototype.connect = function () {
    this._closed = false;
    this._fetchConfig();
    var self = this;
    try {
      this.es = new EventSource(this.base + "/stream");
    } catch (e) {
      this._scheduleRetry();
      return;
    }
    this.es.onopen = function () {
      if (!self.connected) {
        self.connected = true;
        if (self.onStatus) self.onStatus(true);
      }
    };
    this.es.onmessage = function (ev) {
      var d;
      try { d = JSON.parse(ev.data); } catch (e) { return; }
      // First successful message also confirms connection (onopen is not always fired first).
      if (!self.connected) {
        self.connected = true;
        if (self.onStatus) self.onStatus(true);
      }
      if (self.onSensor) self.onSensor(d);
    };
    this.es.onerror = function () {
      // EventSource auto-reconnects, but surface the drop to the UI so it can
      // fall back to simulation in the meantime.
      if (self.connected) {
        self.connected = false;
        if (self.onStatus) self.onStatus(false);
      }
      if (self._closed) { try { self.es.close(); } catch (e) {} }
    };
  };

  Backend.prototype._fetchConfig = function () {
    var self = this;
    fetch(this.base + "/config")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (cfg) { if (cfg) { self.config = cfg; if (self.onConfig) self.onConfig(cfg); } })
      .catch(function () {});
  };

  Backend.prototype._scheduleRetry = function () {
    if (this._retry || this._closed) return;
    var self = this;
    this._retry = setTimeout(function () { self._retry = null; self.connect(); }, 2000);
  };

  // Actuator command -> POST /set. cmd: "set_pwm" | "set_digital".
  Backend.prototype.set = function (cmd, pin, value) {
    if (!this.connected || pin == null) return false;
    fetch(this.base + "/set", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cmd: cmd, pin: pin, value: value }),
    }).catch(function () {});
    return true;
  };

  Backend.prototype.recalibrate = function () {
    return fetch(this.base + "/recalibrate", { method: "POST" }).then(function (r) { return r.json(); });
  };

  // Re-read config.json on the hub and re-push the pin map (apply wiring changes live).
  Backend.prototype.reloadConfig = function () {
    var self = this;
    return fetch(this.base + "/reload_config", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (cfg) { if (cfg && cfg.mosfets) { self.config = cfg; if (self.onConfig) self.onConfig(cfg); } return cfg; });
  };

  Backend.prototype.close = function () {
    this._closed = true;
    if (this._retry) { clearTimeout(this._retry); this._retry = null; }
    if (this.es) { try { this.es.close(); } catch (e) {} }
    this.connected = false;
  };

  window.PhagenticBackend = new Backend();
})();
