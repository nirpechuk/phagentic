# PHAGENTIC — Architecture (diagram brief for Claude)

> **Purpose of this file:** a precise, technical-yet-on-theme description of the PHAGENTIC system so Claude can generate an architecture diagram that (a) is *accurate* to the real system and (b) *looks like our product* — the same parchment-and-ink watercolor lab-console aesthetic, the same blue⇄colorless oscillation motif, the same phage iconography.
>
> Read the **Visual theme** section first (so the diagram matches our UI), then the **System** section (so the boxes and arrows are correct), then **Diagram spec** (layout, labels, what to draw).

---

## Visual theme (match our actual UI)

PHAGENTIC's UI is a hand-built scientific desk console — warm, papery, analog-instrument feel, not a cold SaaS dashboard. The diagram must feel like it was drawn *on the same desk*.

**Palette**
| Token | Hex | Use |
|---|---|---|
| Parchment (bg) | `#ece4d6` | Canvas / background |
| Warm ink | `#3b372f` | Lines, text, borders |
| Ink @ 24% | `rgba(59,55,47,.24)` | Hairlines, grid, subtle dividers |
| Methylene blue (deep) | `#265cc8` | The "blue" oscillation state, active dataflow, highlights |
| Pale solution | `#e4e2d6` | The "colorless"/reduced state; fills |
| Optional accents | Meadow green / Clay terracotta / Mist grey | Sparingly, for grouping zones |

**Type**
- **Instrument Serif** — titles, the word PHAGENTIC, zone headers (elegant, editorial serif).
- **Space Grotesk** — box labels, captions, prose (clean geometric sans).
- **JetBrains Mono** — anything that is data, code, a protocol, a pin, a message type, a number (e.g. `set_pwm`, `20 Hz`, `B̂∈[0,1]`, `6E400003…`).

**Motifs & texture**
- A subtle **blue⇄colorless oscillation waveform** can run along the bottom or thread through the diagram as a connective ribbon — it *is* the signal the whole system controls.
- A small **bacteriophage** glyph (icosahedral head + tail + leg fibers, line-drawn, not photoreal) as a recurring mark — use it for the "AI copilot" node and/or as a corner emblem.
- Hand-plotted, **engineering-notebook** feel: thin rules, light dotted grid, hairline boxes with slightly rounded corners, soft drop shadows like the UI's "soft-close" windows. Watercolor wash *behind* zones, crisp ink *on top*.
- Avoid: glossy gradients, neon, 3D bevels, stock "cloud/server" clip-art, dark mode.

**One-line vibe:** *a control-systems diagram sketched in a naturalist's field journal, where the data flows in methylene blue.*

---

## System (what the boxes and arrows actually are)

The system is a **closed control loop on real hardware** with a thin client on top and a read-only AI copilot to the side. Data flows clockwise: sensor → analysis → control → actuator → (the chemistry) → back to sensor.

### Nodes (draw each as a labeled box)

**1. The vessel — "the plant"** *(bottom-center, the heart of the loop)*
- The Blue Bottle oscillating reaction in a flask: methylene blue + glucose + NaOH. Oscillates **blue ⇄ colorless**. Self-damping; it dies without intervention.
- Draw it literally oscillating (half blue, half pale, with a little waveform). Label: `the plant — nonlinear, drifting, self-damping`.

**2. ESP32 controller + peripherals — "the body"** *(adjacent to the vessel)*
- `controller/controller.ino`. Generic **runtime-configurable pin registry** (told its pins at runtime via `configure`, no reflash).
- Peripherals around it: **Stirrer** (PWM, O₂ in), **Glucose pump** (digital), **NaOH pump** (digital), **Sensor light** (PWM), **TCS34725 RGB sensor** (I²C, 20 Hz).
- Label the link to the backend: `BLE · Nordic UART Service · newline-delimited JSON · MTU 512`. Commands in mono: `configure / set_pwm / set_digital / get_rgb`.

**3. Backend — "the brain" (headless Python, FastAPI + uvicorn, :8080)** *(center; the largest zone)*
This is one zone containing the loop. Inside it, draw the **DeviceWorker 20 Hz loop** as a circular/clockwise flow through these sub-blocks:
- **Device link** (`hardware/device.py`) — the *only* thread that touches hardware; supervises BLE reconnect, re-pushes pin map, re-asserts outputs, zeroes actuators on shutdown.
- **Analysis / DSP** (`analysis/detector.py`) — raw RGBC → IR-corrected, white-balanced → normalized blue `B̂∈[0,1]`; extrema detection → `amplitude, half-period, period, cycles, phase, stall-risk`.
- **State estimator** (`estimator/`) — EMA filter + oscillation baseline + **continuous phase angle** + stall risk. Clean, deterministic, no sim-to-real gap.
- **Control / arbiter** (`control/arbiter.py`) — mode machine: **manual · auto · ml**. Merges model output + manual commands + pump-pulse timers.
- **The three policies** (draw as a small stacked rack feeding the arbiter, escalating sophistication):
  - `pi_baseline` — interpretable PI (reactive).
  - `goal_blue` — deadline-aware goal-seeking (plans to a target hue by a target time).
  - `goal_blue_mpc` — **MPC** over a **grey-box ODE** (4-state: blue/O₂/glucose/pH), fit from logged runs (`sim/fit.py`); enumerates 16 actions, rolls each forward, picks best; **trust-gated** (only drives after held-out validation).
- **State store + protocol** (`state/`, `protocol/messages.py`) — thread-safe snapshot, command queue, event pairs.

**4. Web UI — "the face" (thin client, :5173)** *(top, above the backend)*
- A **draggable console desktop**: panels for Oscillation (waveform), Colour Log, Narration, Console, Calculator (incl. phage⇄blue converter), Runs, Actuators, Ask Phage. Watercolor aesthetic; physics-simulated 3D phage on the landing page.
- It runs **no analysis** — it renders streamed state and sends commands.
- Link to backend: `WebSocket :8080/ws — state ~15 Hz out · commands in`. Mono command list: `set_actuator / pulse_actuator / set_mode / set_model / set_model_params / recalibrate / reload_config`.

**5. ASK PHAGE — the AI copilot (Claude, read-only)** *(to the side, deliberately OFF the control loop)*
- `hub/chat_server.py` — Flask, holds the Anthropic key server-side; **Claude Haiku 4.5**; chemistry briefing prompt-cached; live reaction state injected per turn; streams tokens to the UI.
- **Draw the boundary explicitly:** a dashed "read-only" wall between the copilot and every actuator. Arrows from copilot point only *to text in the UI* — **never** to the device. Label: `no tools · no actuation path · read-only is structural, not a prompt`.
- This is the single most important *semantic* detail in the diagram (it's our ethics story). Make the "can read, cannot act" relationship visually unmistakable.

### The loop (the arrows that matter most)
Draw the control loop as a continuous **methylene-blue ribbon** going clockwise:

```
TCS34725 sensor ──► Analysis/DSP ──► State estimator ──► Control (arbiter + policy)
      ▲                                                            │
      │                                                            ▼
  the vessel  ◄──  Stirrer / Glucose / NaOH  ◄──  Device link  ◄──┘
 (blue⇄colorless)        (actuators, via ESP32 over BLE)
```
- The UI sits above the backend with a two-way `WebSocket` arrow (state up, commands down).
- The copilot sits to the side with a **one-way read** arrow from the state store and a **one-way text** arrow to the UI — and a visible *blocked* connection to actuators.

---

## Diagram spec (how to lay it out)

- **Format:** wide landscape (≈16:9 or 3:2), suitable for a slide and a Devpost header.
- **Layout (3 bands):**
  1. **Top band — Web UI** (the console, thin client).
  2. **Middle band — Backend brain** (the big zone; the 20 Hz loop drawn as a clockwise cycle; the 3-policy rack visible). The ASK PHAGE copilot hangs off the *right edge* of this band behind a dashed read-only wall.
  3. **Bottom band — Hardware**: ESP32 + actuators + sensor on one side, the oscillating vessel on the other, connected by the blue control ribbon.
- **Cross-band links labeled with their real protocol:** `WebSocket :8080/ws` (UI↔backend), `BLE / NUS` (backend↔ESP32), `I²C / PWM / digital` (ESP32↔peripherals).
- **Legend (small, bottom corner):** blue ribbon = live signal/dataflow; dashed wall = read-only boundary; mono text = protocol/code; serif = system & zones.
- **Title block:** "PHAGENTIC" in Instrument Serif, with the tagline beneath in Space Grotesk: *"The OS for autonomous bioreactors."* A small line-drawn phage as the logo mark.
- **Keep every label truthful** — use the exact module names, message types, and rates above. The diagram should double as documentation a real engineer trusts.

### Three callouts to make visually prominent (these are the "why we win" beats)
1. **The closed loop** — the blue ribbon completing a full circle through real hardware (this is the *physical AI* claim).
2. **The 3-policy rack** — PI → goal-seeking → MPC-over-fitted-ODE (this is the *technical depth* claim).
3. **The dashed read-only wall** around the AI (this is the *ethics / safety* claim).
