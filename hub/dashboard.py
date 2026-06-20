#!/usr/bin/env python3
"""Web dashboard: live RGB swatch + controls for the MOSFETs and sensor light in config.json."""
import json
import queue
import sys
import threading
import time
import webbrowser

from flask import Flask, Response, jsonify, request

import config
from controller import Controller
from transport.ble_transport import BLETransport

SAMPLE_RATE = 20
HTTP_PORT   = 8080

app = Flask(__name__)

_latest   = {"r": 0, "g": 0, "b": 0, "c": 0}
_cmd_queue: queue.Queue = queue.Queue()   # (cmd, pin, value) tuples from /set
_ctrl: Controller | None = None
_cfg: dict = {}
_wb      = (1.0, 1.0, 1.0)
_white_c = 1.0

# Actions requested from the web UI are executed by the sensor thread (which owns _ctrl),
# so transport access stays single-threaded. Each pairs a request flag with a done event.
_recalib_req  = threading.Event()
_recalib_done = threading.Event()
_reload_req   = threading.Event()
_reload_done  = threading.Event()


# ── Colour math ───────────────────────────────────────────────────────────────

def sample_wb(ctrl: Controller, samples: int = 30) -> tuple:
    """Sample the sensor and compute (sr, sg, sb, white_c). No prompting — the caller is
    responsible for aiming the sensor at a white surface first."""
    rs, gs, bs, cs = [], [], [], []
    for _ in range(samples):
        d = ctrl.get_rgb()
        if d:
            rs.append(d["r"]); gs.append(d["g"]); bs.append(d["b"]); cs.append(d["c"])
        time.sleep(1.0 / SAMPLE_RATE)
    if not rs:
        print("No sensor data — skipping calibration.")
        return 1.0, 1.0, 1.0, 1.0
    r_avg   = sum(rs) / len(rs)
    g_avg   = sum(gs) / len(gs)
    b_avg   = sum(bs) / len(bs)
    white_c = sum(cs) / len(cs)
    peak    = max(r_avg, g_avg, b_avg)
    sr, sg, sb = peak / r_avg, peak / g_avg, peak / b_avg
    print(f"  R×{sr:.2f}  G×{sg:.2f}  B×{sb:.2f}  white_c={white_c:.0f}\n")
    return sr, sg, sb, white_c


def calibrate(ctrl: Controller, samples: int = 30) -> tuple:
    print("Point sensor at a white surface, then press Enter to calibrate white balance...")
    input()
    return sample_wb(ctrl, samples)


def to_rgb8(r: int, g: int, b: int, c: int, wb: tuple, white_c: float) -> tuple:
    ir         = max(0, (r + g + b - c) // 2)
    rf         = max(0.0, (r - ir) * wb[0])
    gf         = max(0.0, (g - ir) * wb[1])
    bf         = max(0.0, (b - ir) * wb[2])
    peak       = max(rf, gf, bf)
    if peak == 0:
        return 0, 0, 0
    brightness = min(1.0, c / white_c)
    s          = 255.0 / peak * brightness
    return int(rf * s), int(gf * s), int(bf * s)


# ── Sensor polling thread ─────────────────────────────────────────────────────

def _sensor_loop() -> None:
    global _cfg, _wb, _white_c
    step = 1.0 / SAMPLE_RATE
    while True:
        t0 = time.monotonic()
        # Apply config reload requested from the web UI (re-push pin map, relight sensor).
        if _reload_req.is_set():
            _reload_req.clear()
            res = _ctrl.configure(config.pin_map(_cfg))
            print("Config reloaded:", res.get("status", "no response"))
            light = _cfg.get("sensor_light")
            if light:
                _ctrl.set_pwm(light["pin"], 255)
            _reload_done.set()
        # Recalibrate white balance requested from the web UI.
        if _recalib_req.is_set():
            _recalib_req.clear()
            print("Recalibrating white balance...")
            *wb, white_c = sample_wb(_ctrl)
            _wb, _white_c = tuple(wb), white_c
            _recalib_done.set()
        # Drain control commands — keep only the latest per pin to skip stale slider events
        pending: dict[int, tuple[str, int]] = {}
        while True:
            try:
                cmd, pin, value = _cmd_queue.get_nowait()
                pending[pin] = (cmd, value)
            except queue.Empty:
                break
        for pin, (cmd, value) in pending.items():
            if cmd == "set_digital":
                _ctrl.set_digital(pin, bool(value))
            else:
                _ctrl.set_pwm(pin, value)
        # Sensor read
        data = _ctrl.get_rgb()
        if data:
            _latest.update(data)
        time.sleep(max(0.0, step - (time.monotonic() - t0)))


# ── Flask routes ──────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Bioreactor Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: monospace; background: #111; color: #ccc; padding: 2.5rem; }
    h2 { font-size: 0.85rem; letter-spacing: 0.15em; color: #555; margin-bottom: 2rem; }
    #swatch {
      width: 260px; height: 260px; border-radius: 8px;
      border: 1px solid #2a2a2a; margin-bottom: 1rem;
      transition: background 80ms linear;
    }
    #vals { font-size: 1rem; color: #666; margin-bottom: 2.5rem; }
    #vals span { color: #ccc; }
    .ctrl { margin-bottom: 1.4rem; }
    .ctrl-label { font-size: 0.8rem; letter-spacing: 0.08em; color: #555; margin-bottom: 0.5rem; }
    .ctrl-label em { color: #ccc; font-style: normal; }
    input[type=range] {
      display: block; width: 300px;
      accent-color: #4af; cursor: pointer;
    }
    button.toggle {
      font-family: monospace; font-size: 0.8rem; letter-spacing: 0.08em;
      background: #222; color: #ccc; border: 1px solid #2a2a2a;
      padding: 0.45rem 1.4rem; border-radius: 4px; cursor: pointer;
    }
    button.toggle.on { background: #4af; color: #111; border-color: #4af; }
    h3 { font-size: 0.75rem; letter-spacing: 0.12em; color: #444; margin: 2rem 0 1.2rem; }
    button.action {
      font-family: monospace; font-size: 0.75rem; letter-spacing: 0.1em;
      background: #1b1b1b; color: #9bd; border: 1px solid #2a2a2a;
      padding: 0.5rem 1.2rem; border-radius: 4px; cursor: pointer;
    }
    button.action:hover:enabled { border-color: #4af; }
    button.action:disabled { color: #555; cursor: default; border-color: #222; }
    .status { font-size: 0.75rem; color: #666; margin-left: 0.8rem; }
    .cols { display: flex; gap: 3.5rem; align-items: flex-start; flex-wrap: wrap; }
    .col { min-width: 320px; }
    #diagram svg { width: 571px; max-width: 100%; height: auto; display: block; }
  </style>
</head>
<body>
  <h2>BIOREACTOR DASHBOARD</h2>

  <div class="cols">
    <div class="col">
      <div id="swatch"></div>
      <div id="vals">R:<span id="vr">–</span>  G:<span id="vg">–</span>  B:<span id="vb">–</span>  lux:<span id="vlux">–</span></div>
      <div id="light"></div>
      <div style="margin-bottom:2.5rem">
        <button id="recal" class="action" title="Aim the sensor at white first">Recalibrate sensor</button>
        <span id="recal-status" class="status"></span>
      </div>

      <h3 id="actuators-h" style="display:none">ACTUATORS</h3>
      <div id="mosfets"></div>
    </div>

    <div class="col">
      <h3 style="margin-top:0">WIRING</h3>
      <div id="diagram"></div>
      <div style="margin-top:1.5rem">
        <button id="reload" class="action" title="Re-read config.json and re-push to the device">Update config</button>
        <span id="reload-status" class="status"></span>
      </div>
    </div>
  </div>

  <script>
    const es = new EventSource('/stream');
    es.onmessage = e => {
      const d = JSON.parse(e.data);
      document.getElementById('swatch').style.background = `rgb(${d.r},${d.g},${d.b})`;
      document.getElementById('vr').textContent   = String(d.r).padStart(3);
      document.getElementById('vg').textContent   = String(d.g).padStart(3);
      document.getElementById('vb').textContent   = String(d.b).padStart(3);
      document.getElementById('vlux').textContent = d.lux;
    };

    function send(cmd, pin, value) {
      fetch('/set', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cmd, pin, value})
      });
    }

    function pwmControl(name, pin) {
      const wrap = document.createElement('div'); wrap.className = 'ctrl';
      const label = document.createElement('div'); label.className = 'ctrl-label';
      const em = document.createElement('em'); em.textContent = '0';
      label.append(name + '  ', em);
      const slider = document.createElement('input');
      slider.type = 'range'; slider.min = 0; slider.max = 255; slider.value = 0;
      slider.oninput = () => { em.textContent = slider.value; send('set_pwm', pin, +slider.value); };
      wrap.append(label, slider);
      return wrap;
    }

    function digitalControl(name, pin) {
      const wrap = document.createElement('div'); wrap.className = 'ctrl';
      const label = document.createElement('div'); label.className = 'ctrl-label';
      label.textContent = name;
      const btn = document.createElement('button'); btn.className = 'toggle'; btn.textContent = 'OFF';
      let on = false;
      btn.onclick = () => {
        on = !on;
        btn.textContent = on ? 'ON' : 'OFF';
        btn.classList.toggle('on', on);
        send('set_digital', pin, on ? 1 : 0);
      };
      wrap.append(label, btn);
      return wrap;
    }

    function renderControls(cfg) {
      const light = document.getElementById('light');
      const m = document.getElementById('mosfets');
      light.innerHTML = ''; m.innerHTML = '';
      if (cfg.sensor_light) light.append(pwmControl('Light', cfg.sensor_light.pin));
      document.getElementById('actuators-h').style.display = cfg.mosfets.length ? '' : 'none';
      for (const d of cfg.mosfets)
        m.append(d.mode === 'digital' ? digitalControl(d.name, d.pin) : pwmControl(d.name, d.pin));
    }

    // Config-driven wiring diagram: ESP32 chip on the left, one wire per pin out to each
    // device box on the right. Rebuilt whenever the config is (re)loaded.
    const esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    function renderDiagram(cfg) {
      const pins = [];
      for (const d of cfg.mosfets)
        pins.push({pin: d.pin, color: d.mode === 'digital' ? '#fa4' : '#4af', device: d.name, sub: 'GPIO ' + d.pin + ' · ' + d.mode});
      if (cfg.sensor_light)
        pins.push({pin: cfg.sensor_light.pin, color: '#fd4', device: 'Sensor LED', sub: 'GPIO ' + cfg.sensor_light.pin + ' · pwm'});
      const s = cfg.sensor || {name: 'Sensor', sda: 21, scl: 22};
      pins.push({pin: s.sda, color: '#6c6', device: s.name, sub: 'I²C', tag: 'SDA'});
      pins.push({pin: s.scl, color: '#6c6', device: s.name, sub: 'I²C', tag: 'SCL'});

      const rowH = 52, startY = 10, titleH = 28, chipX = 16, chipW = 120, devX = 300, devW = 168, W = 480;
      const H = startY + titleH + pins.length * rowH + 12;
      const chipR = chipX + chipW;
      const yOf = i => startY + titleH + i * rowH + rowH / 2;

      let g = `<svg viewBox="0 0 ${W} ${H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="monospace">`;
      const chipTop = startY, chipBot = yOf(pins.length - 1) + rowH / 2 - 4;
      g += `<rect x="${chipX}" y="${chipTop}" width="${chipW}" height="${chipBot - chipTop}" rx="8" fill="#16181d" stroke="#39414f"/>`;
      g += `<text x="${chipX + chipW / 2}" y="${chipTop + 19}" fill="#7fd9c0" font-size="12" text-anchor="middle" letter-spacing="1">ESP32</text>`;

      pins.forEach((p, i) => {
        const y = yOf(i);
        g += `<line x1="${chipR}" y1="${y}" x2="${devX}" y2="${y}" stroke="${p.color}" stroke-width="2"/>`;
        g += `<circle cx="${chipR}" cy="${y}" r="3.5" fill="${p.color}"/><circle cx="${devX}" cy="${y}" r="3.5" fill="${p.color}"/>`;
        g += `<text x="${chipR - 8}" y="${y + 4}" fill="#cdd6e0" font-size="11" text-anchor="end">GPIO ${p.pin}</text>`;
        if (p.tag) g += `<text x="${devX - 8}" y="${y - 5}" fill="#8a8" font-size="9" text-anchor="end">${esc(p.tag)}</text>`;
      });

      for (let i = 0; i < pins.length; ) {
        let j = i;
        while (j + 1 < pins.length && pins[j + 1].device === pins[i].device) j++;
        const top = yOf(i) - rowH / 2 + 8, bot = yOf(j) + rowH / 2 - 8, mid = (top + bot) / 2;
        g += `<rect x="${devX}" y="${top}" width="${devW}" height="${bot - top}" rx="6" fill="#16181d" stroke="${pins[i].color}"/>`;
        g += `<text x="${devX + 14}" y="${mid - 1}" fill="#eee" font-size="12">${esc(pins[i].device)}</text>`;
        g += `<text x="${devX + 14}" y="${mid + 15}" fill="#777" font-size="10">${esc(pins[i].sub)}</text>`;
        i = j + 1;
      }
      g += `</svg>`;
      document.getElementById('diagram').innerHTML = g;
    }

    function apply(cfg) { renderControls(cfg); renderDiagram(cfg); }

    fetch('/config').then(r => r.json()).then(apply);

    document.getElementById('recal').onclick = () => {
      const btn = document.getElementById('recal'), st = document.getElementById('recal-status');
      btn.disabled = true; st.textContent = 'calibrating…';
      fetch('/recalibrate', {method: 'POST'}).then(r => r.json()).then(d => {
        st.textContent = d.status === 'ok'
          ? `done  R×${d.wb[0].toFixed(2)} G×${d.wb[1].toFixed(2)} B×${d.wb[2].toFixed(2)}`
          : 'error: ' + (d.msg || 'failed');
        btn.disabled = false;
      });
    };

    document.getElementById('reload').onclick = () => {
      const btn = document.getElementById('reload'), st = document.getElementById('reload-status');
      btn.disabled = true; st.textContent = 'reloading…';
      fetch('/reload_config', {method: 'POST'})
        .then(r => r.json().then(d => ({ok: r.ok, d})))
        .then(({ok, d}) => {
          if (ok) { apply(d); st.textContent = 'updated'; }
          else { st.textContent = 'error: ' + (d.msg || 'invalid config'); }
          btn.disabled = false;
        });
    };
  </script>
</body>
</html>"""


@app.route("/")
def index():
    return _HTML


@app.route("/stream")
def stream():
    def generate():
        while True:
            snap = dict(_latest)   # GIL makes this an atomic copy
            r, g, b = to_rgb8(snap["r"], snap["g"], snap["b"], snap["c"], _wb, _white_c)
            yield f"data: {json.dumps({'r': r, 'g': g, 'b': b, 'lux': snap['c']})}\n\n"
            time.sleep(1.0 / SAMPLE_RATE)
    return Response(generate(), mimetype="text/event-stream")


def _layout() -> dict:
    """Config-derived hardware layout for the UI controls and wiring diagram."""
    return {
        "mosfets": _cfg.get("mosfets", []),
        "sensor_light": _cfg.get("sensor_light"),
        "sensor": config.sensor_info(_cfg),
    }


@app.route("/config")
def config_route():
    return jsonify(_layout())


@app.route("/set", methods=["POST"])
def set_output():
    data = request.get_json()
    cmd = "set_digital" if data.get("cmd") == "set_digital" else "set_pwm"
    _cmd_queue.put((cmd, int(data["pin"]), int(data["value"])))
    return jsonify({"status": "ok"})


@app.route("/reload_config", methods=["POST"])
def reload_config():
    """Re-read config.json from disk and re-push the pin map to the device — apply wiring
    changes without restarting the hub. Returns the new layout for the UI to rebuild from."""
    global _cfg
    try:
        _cfg = config.load_config()
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return jsonify({"status": "error", "msg": str(e)}), 400
    _reload_done.clear()
    _reload_req.set()
    _reload_done.wait(timeout=5.0)
    return jsonify({"status": "ok", **_layout()})


@app.route("/recalibrate", methods=["POST"])
def recalibrate():
    """Re-run white-balance calibration against whatever the sensor currently sees."""
    _recalib_done.clear()
    _recalib_req.set()
    if not _recalib_done.wait(timeout=10.0):
        return jsonify({"status": "error", "msg": "timeout"}), 504
    sr, sg, sb = _wb
    return jsonify({"status": "ok", "wb": [sr, sg, sb], "white_c": _white_c})


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    global _ctrl, _cfg, _wb, _white_c

    _cfg = config.load_config()
    transport = BLETransport(config.device_name(_cfg))
    _ctrl = Controller(transport)
    _ctrl.connect()

    print("Pinging...", end=" ", flush=True)
    if not _ctrl.ping():
        print("no response.")
        sys.exit(1)
    print("OK")

    pins = config.pin_map(_cfg)
    print(f"Configuring {len(pins)} pin(s)... ", end="", flush=True)
    print(_ctrl.configure(pins).get("status", "no response"), "\n")

    light = _cfg.get("sensor_light")
    if light:                                   # light on so calibration sees lit conditions
        _ctrl.set_pwm(light["pin"], 255)

    *wb, white_c = calibrate(_ctrl)
    _wb      = tuple(wb)
    _white_c = white_c

    threading.Thread(target=_sensor_loop, daemon=True).start()

    url = f"http://localhost:{HTTP_PORT}"
    print(f"Dashboard → {url}")
    threading.Timer(1.0, webbrowser.open, args=[url]).start()
    app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
