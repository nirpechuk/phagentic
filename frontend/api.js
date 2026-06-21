// PHAGENTIC — bridge to the headless backend (backend/, FastAPI on :8080).
//
// The backend now owns the device link, oscillation analysis, the control loop
// and the pluggable ML model. The UI is a thin client: it renders the state the
// backend streams and sends commands back, both over ONE WebSocket.
//
//   ws://<host>:8080/ws
//     server → client:  {type:"state", ...full snapshot..., narr_new:[]}
//                        {type:"config", mosfets, sensor_light, roles, models}
//                        {type:"ack", ref, ok, msg}
//                        {type:"calibration", status, wb, white_c}
//     client → server:  set_actuator {role,value} · pulse_actuator {role,ms}
//                        set_mode {mode} · set_model {name} · set_model_params {params}
//                        recalibrate · reload_config · reset_run · ping
//
// When the socket drops the UI shows "offline" and auto-reconnects; there is no
// in-browser simulation any more — all the brains live in the backend.
(function () {
  "use strict";

  function resolveWs() {
    var raw = null;
    if (window.PHAGENTIC_BACKEND) raw = window.PHAGENTIC_BACKEND;
    else {
      var q = new URLSearchParams(location.search).get("backend");
      if (q) raw = q;
    }
    if (raw) {
      // Accept http(s):// or ws(s):// or bare host; normalise to a ws URL + /ws.
      raw = raw.replace(/\/$/, "");
      if (/^https?:/.test(raw)) raw = raw.replace(/^http/, "ws");
      if (!/^wss?:/.test(raw)) raw = "ws://" + raw;
      if (!/\/ws$/.test(raw)) raw = raw + "/ws";
      return raw;
    }
    // Default: the backend's default address (UI is usually served from :5173).
    var host = location.hostname || "localhost";
    return "ws://" + host + ":8080/ws";
  }

  function Backend() {
    this.url = resolveWs();
    this.ws = null;
    this.connected = false;
    this.config = null;
    this.onState = null;   // (snapshot) => void
    this.onConfig = null;  // (layout) => void
    this.onStatus = null;  // (connected:boolean) => void
    this._closed = false;
    this._retry = null;
    this._calibWaiters = [];
  }

  Backend.prototype.connect = function () {
    this._closed = false;
    var self = this;
    try {
      this.ws = new WebSocket(this.url);
    } catch (e) {
      this._scheduleRetry();
      return;
    }
    this.ws.onopen = function () {
      self.connected = true;
      if (self.onStatus) self.onStatus(true);
    };
    this.ws.onmessage = function (ev) {
      var m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      switch (m.type) {
        case "state":  if (self.onState) self.onState(m); break;
        case "config": self.config = m; if (self.onConfig) self.onConfig(m); break;
        case "calibration":
          self._calibWaiters.splice(0).forEach(function (r) { r(m); });
          break;
        // "ack" is currently advisory — ignored.
      }
    };
    this.ws.onerror = function () { /* close handler drives reconnect */ };
    this.ws.onclose = function () {
      if (self.connected) { self.connected = false; if (self.onStatus) self.onStatus(false); }
      self.ws = null;
      if (!self._closed) self._scheduleRetry();
    };
  };

  Backend.prototype._scheduleRetry = function () {
    if (this._retry || this._closed) return;
    var self = this;
    this._retry = setTimeout(function () { self._retry = null; self.connect(); }, 1500);
  };

  Backend.prototype._send = function (obj) {
    if (!this.ws || this.ws.readyState !== 1) return false;
    try { this.ws.send(JSON.stringify(obj)); return true; } catch (e) { return false; }
  };

  // role ∈ stirrer|light|glucose|naoh.  PWM roles take 0-255; pumps take bool.
  Backend.prototype.setActuator = function (role, value) { return this._send({ type: "set_actuator", role: role, value: value }); };
  Backend.prototype.pulseActuator = function (role, ms) { return this._send({ type: "pulse_actuator", role: role, ms: ms }); };
  Backend.prototype.setMode = function (mode) { return this._send({ type: "set_mode", mode: mode }); };
  Backend.prototype.setModel = function (name) { return this._send({ type: "set_model", name: name }); };
  Backend.prototype.setModelParams = function (params) { return this._send({ type: "set_model_params", params: params }); };
  Backend.prototype.reloadConfig = function () { return this._send({ type: "reload_config" }); };
  Backend.prototype.resetRun = function () { return this._send({ type: "reset_run" }); };

  // Resolves with the {status, wb, white_c} calibration reply.
  Backend.prototype.recalibrate = function () {
    var self = this;
    return new Promise(function (resolve) {
      self._calibWaiters.push(resolve);
      if (!self._send({ type: "recalibrate" })) resolve({ status: "error" });
      setTimeout(function () {
        var i = self._calibWaiters.indexOf(resolve);
        if (i >= 0) { self._calibWaiters.splice(i, 1); resolve({ status: "timeout" }); }
      }, 16000);
    });
  };

  Backend.prototype.close = function () {
    this._closed = true;
    if (this._retry) { clearTimeout(this._retry); this._retry = null; }
    if (this.ws) { try { this.ws.close(); } catch (e) {} }
    this.connected = false;
  };

  window.PhagenticBackend = new Backend();
})();
