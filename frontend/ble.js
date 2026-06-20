// PHAGENTIC — direct Web Bluetooth link to the ESP32 bioreactor.
//
// This lets the browser talk to the hardware with NO Python hub running. It is a
// faithful port of the hub's transport + controller (hub/transport/ble_transport.py,
// hub/controller.py): the same Nordic UART Service, the same newline-delimited
// JSON request/reply protocol, and the same colour math (hub.dashboard.to_rgb8).
//
// Protocol commands: ping · configure · set_pwm · set_digital · get_analog · get_rgb.
// Web Bluetooth requires HTTPS or localhost and a user gesture to connect.
(function () {
  "use strict";

  // Nordic UART Service (NUS) — must match controller/controller.ino.
  var NUS = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
  var RX  = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"; // host → device (write)
  var TX  = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"; // device → host (notify)

  function BLE() {
    this.device = null;
    this.server = null;
    this.rx = null;
    this.tx = null;
    this.connected = false;
    this.deviceName = "Bioreactor";
    this.onSample = null;  // ({r,g,b,lux,raw}) => void   (white-balanced 0-255 + lux)
    this.onStatus = null;  // (connected:boolean) => void
    this.onLog = null;     // (msg:string) => void
    this.wb = [1, 1, 1];
    this.whiteC = 400;
    this._buf = "";
    this._waiters = [];
    this._chain = Promise.resolve();
    this._enc = new TextEncoder();
    this._dec = new TextDecoder();
    this._streaming = false;
  }

  BLE.prototype.supported = function () { return !!(navigator.bluetooth && navigator.bluetooth.requestDevice); };
  BLE.prototype._log = function (m) { if (this.onLog) this.onLog(m); };

  // Pick a device via the browser chooser (needs a user gesture), then attach.
  BLE.prototype.connect = async function (name) {
    if (!this.supported()) throw new Error("Web Bluetooth not available (use Chrome over https/localhost)");
    this.deviceName = name || this.deviceName;
    this._log("Requesting device…");
    var dev = await navigator.bluetooth.requestDevice({
      filters: [{ name: this.deviceName }, { namePrefix: this.deviceName }],
      optionalServices: [NUS],
    });
    return this._attach(dev);
  };

  // Devices the user has already granted this origin — lets us reconnect with no
  // chooser on later visits (Chrome's navigator.bluetooth.getDevices()).
  BLE.prototype.listKnown = async function () {
    if (!(navigator.bluetooth && navigator.bluetooth.getDevices)) return [];
    try { return await navigator.bluetooth.getDevices(); } catch (e) { return []; }
  };

  // Reconnect to a previously-granted device without prompting. Resolves false if
  // none is known/in range.
  BLE.prototype.reconnect = async function (name) {
    var want = name || this.deviceName;
    var known = await this.listKnown();
    if (!known.length) return false;
    var dev = known.filter(function (d) { return !want || d.name === want; })[0] || known[0];
    if (!dev) return false;
    this._log("Reconnecting to " + (dev.name || "device") + "…");
    await this._attach(dev);
    return true;
  };

  // Shared GATT setup for a chosen/known device.
  BLE.prototype._attach = async function (dev) {
    this.device = dev;
    dev.addEventListener("gattserverdisconnected", () => this._onDisconnect());
    this._log("Connecting GATT…");
    this.server = await dev.gatt.connect();
    var svc = await this.server.getPrimaryService(NUS);
    this.rx = await svc.getCharacteristic(RX);
    this.tx = await svc.getCharacteristic(TX);
    await this.tx.startNotifications();
    this.tx.addEventListener("characteristicvaluechanged", (e) => this._onNotify(e.target.value));
    this.connected = true;
    if (this.onStatus) this.onStatus(true);
    this._log("Connected to " + (dev.name || this.deviceName));
    return true;
  };

  BLE.prototype._onDisconnect = function () {
    this.connected = false;
    this._streaming = false;
    this._waiters.forEach(function (w) { clearTimeout(w.timer); w.reject(new Error("disconnected")); });
    this._waiters = [];
    if (this.onStatus) this.onStatus(false);
    this._log("Disconnected");
  };

  BLE.prototype.disconnect = function () {
    this._streaming = false;
    if (this.device && this.device.gatt && this.device.gatt.connected) this.device.gatt.disconnect();
  };

  BLE.prototype._onNotify = function (dataview) {
    this._buf += this._dec.decode(dataview);
    var i;
    while ((i = this._buf.indexOf("\n")) >= 0) {
      var line = this._buf.slice(0, i).trim();
      this._buf = this._buf.slice(i + 1);
      if (!line) continue;
      var msg = null;
      try { msg = JSON.parse(line); } catch (e) { continue; }
      var w = this._waiters.shift();
      if (w) { clearTimeout(w.timer); w.resolve(msg); }
    }
  };

  // One command in, one reply out — serialized so replies match requests (FIFO).
  BLE.prototype.send = function (obj) {
    var self = this;
    this._chain = this._chain.then(function () { return self._raw(obj); }, function () { return self._raw(obj); });
    return this._chain;
  };
  BLE.prototype._raw = function (obj) {
    var self = this;
    if (!this.connected || !this.rx) return Promise.reject(new Error("not connected"));
    return new Promise(function (resolve, reject) {
      var w = { resolve: resolve, reject: reject, timer: setTimeout(function () {
        var idx = self._waiters.indexOf(w); if (idx >= 0) self._waiters.splice(idx, 1);
        reject(new Error("timeout: " + obj.cmd));
      }, 2000) };
      self._waiters.push(w);
      self.rx.writeValueWithResponse(self._enc.encode(JSON.stringify(obj) + "\n")).catch(function (e) {
        clearTimeout(w.timer); var idx = self._waiters.indexOf(w); if (idx >= 0) self._waiters.splice(idx, 1); reject(e);
      });
    });
  };

  // ---- controller API (mirrors hub/controller.py) ---------------------------
  BLE.prototype.ping = function () { return this.send({ cmd: "ping" }).then(function (r) { return r && r.status === "pong"; }); };
  BLE.prototype.configure = function (pins) { return this.send({ cmd: "configure", pins: pins }); };
  BLE.prototype.setPwm = function (pin, value) { return this.send({ cmd: "set_pwm", pin: pin, value: value | 0 }); };
  BLE.prototype.setDigital = function (pin, value) { return this.send({ cmd: "set_digital", pin: pin, value: value ? 1 : 0 }); };
  BLE.prototype.getAnalog = function (pin) { return this.send({ cmd: "get_analog", pin: pin }).then(function (r) { return r ? r.value : null; }); };
  BLE.prototype.getRgb = function () {
    return this.send({ cmd: "get_rgb" }).then(function (r) {
      return (r && r.status === "ok") ? { r: r.r, g: r.g, b: r.b, c: r.c } : null;
    });
  };

  // hub.dashboard.to_rgb8 — raw RGBC (uint16) → white-balanced 0-255 swatch.
  BLE.prototype.toRgb8 = function (r, g, b, c) {
    var ir = Math.max(0, (r + g + b - c) / 2);
    var rf = Math.max(0, (r - ir) * this.wb[0]);
    var gf = Math.max(0, (g - ir) * this.wb[1]);
    var bf = Math.max(0, (b - ir) * this.wb[2]);
    var peak = Math.max(rf, gf, bf);
    if (peak === 0) return [0, 0, 0];
    var brightness = Math.min(1, c / this.whiteC);
    var s = 255 / peak * brightness;
    return [Math.round(rf * s), Math.round(gf * s), Math.round(bf * s)];
  };

  // White-balance against whatever the sensor currently sees (aim at white first).
  BLE.prototype.calibrate = async function (samples) {
    samples = samples || 24;
    var rs = 0, gs = 0, bs = 0, cs = 0, n = 0;
    for (var i = 0; i < samples; i++) {
      var d = await this.getRgb();
      if (d) { rs += d.r; gs += d.g; bs += d.b; cs += d.c; n++; }
    }
    if (!n) return null;
    var ra = rs / n, ga = gs / n, ba = bs / n;
    var peak = Math.max(ra, ga, ba);
    this.wb = [peak / ra, peak / ga, peak / ba];
    this.whiteC = cs / n;
    this._log("Calibrated  wb=" + this.wb.map(function (x) { return x.toFixed(2); }).join("/"));
    return { wb: this.wb, white_c: this.whiteC };
  };

  // Poll get_rgb continuously and emit white-balanced samples to onSample.
  BLE.prototype.startStream = function (rateHz) {
    var self = this;
    if (this._streaming) return;
    this._streaming = true;
    var step = 1000 / (rateHz || 20);
    (function loop() {
      if (!self._streaming || !self.connected) { self._streaming = false; return; }
      var t0 = Date.now();
      self.getRgb().then(function (d) {
        if (d && self.onSample) {
          var rgb = self.toRgb8(d.r, d.g, d.b, d.c);
          self.onSample({ r: rgb[0], g: rgb[1], b: rgb[2], lux: d.c, raw: d });
        }
      }).catch(function () {}).then(function () {
        if (!self._streaming) return;
        setTimeout(loop, Math.max(0, step - (Date.now() - t0)));
      });
    })();
  };
  BLE.prototype.stopStream = function () { this._streaming = false; };

  window.PhagenticBLE = new BLE();
})();
