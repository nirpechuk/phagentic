# PHAGENTIC — Hackathon Pitch, Presentation & Devpost Plan

> **One-liner:** An autonomous bioreactor that senses, reasons about, and steers a living oscillating reaction in a closed loop — a physical testbed for the AI that will one day dose phage therapy against antibiotic-resistant superbugs.

This document is the single source of truth for how we pitch, demo, and submit PHAGENTIC. It covers: the story, the technical substance, a track-by-track win strategy, a criteria scorecard, the live-demo choreography, the slide deck, the Devpost writeup (full + 200-word), Q&A prep, and an honest pre-judging punch list.

---

## 0. TL;DR for the team (read this first)

- **What we actually built:** a real, working closed-loop hardware control system. An ESP32 drives a stirrer + peristaltic pumps and reads an RGB color sensor at 20 Hz over BLE. A headless Python backend does live oscillation analysis (amplitude / period / phase / stall risk), runs a control policy (manual / PI / pluggable ML), and streams everything over a WebSocket to a hand-built web console. Claude rides on top as a **read-only** scientific copilot.
- **The chemistry:** the *Blue Bottle* reaction — a solution that oscillates blue ⇄ colorless. It naturally damps out and stalls, exactly like a real biological culture. Keeping it alive at a target rhythm is a genuine closed-loop control problem.
- **The big idea / why it matters:** phage therapy against superbugs is fundamentally a **closed-loop control problem on an oscillating predator–prey system**. You can't dose once and walk away — you have to sense, decide, actuate, repeat. PHAGENTIC is the *control architecture* for that, proven on real hardware with real failure modes, using a safe, visible chemical analog instead of a live pathogen.
- **Why we win:** it's one of the few projects that is simultaneously **physical AI** (closes the loop with real hardware), **deeply technical** (firmware → BLE → DSP → control theory → full-stack → LLM), **scientifically grounded** (biotech/health), **beautifully designed** (the console UI), and **ethically thoughtful** (the AI is *structurally* prevented from actuating). That hits five tracks at once.

---

## 1. The narrative (the spine of every pitch)

We tell this as a three-beat story. Keep it tight; the demo carries the rest.

**Beat 1 — The war we're losing.**
A war has raged for billions of years, killing trillions a day: bacteriophages vs. bacteria. We borrowed bacteria's natural predators — antibiotics from fungi — and won, for a century. But bacteria evolve. We now have superbugs resistant to nearly everything. By 2050 they could kill more people a year than cancer; in the US alone, >23,000 die from resistant infections annually. A cut or a cough could become lethal again.

**Beat 2 — Nature's answer, and the hard part nobody talks about.**
The most promising countermeasure is the oldest one: bacteriophages — viruses that hunt one specific bacterium like a guided missile, leave human cells alone, and *co-evolve* with their prey so they keep working. Phage therapy has already saved patients antibiotics couldn't. **But here's the catch:** a phage-vs-bacteria infection is a *living, oscillating, evolving* predator–prey system. Populations boom and crash in cycles (Lotka–Volterra dynamics). Dosing it isn't a single shot — it's a control problem. Too little and the bacteria rebound; too much and you crash the ecosystem; mistime it and the oscillation stalls. **No human can sit at the bedside reading the system and re-dosing every few seconds. That's a job for closed-loop autonomy.**

**Beat 3 — So we built the autopilot.**
PHAGENTIC is that autopilot, built end-to-end on real hardware. We needed an oscillating biological system we could run safely on a hackathon table — so we use the **Blue Bottle reaction**, a chemical oscillator that booms and crashes (blue ⇄ colorless) and *stalls when starved*, exactly like a microbial culture. Our system watches the color in real time, estimates the oscillation's state, and autonomously drives a stirrer (oxygen in) and a glucose pump (fuel in) to **hold the rhythm at a target setpoint** — and to **rescue it when it's about to die**. Swap the chemical oscillator for a real phage–bacteria co-culture and the *exact same control stack* is dosing therapy. And because an AI driving pumps near a patient is a serious responsibility, our Claude copilot is **structurally read-only**: it can explain everything happening in the reactor, but it has no tool, no path, no ability to touch an actuator. Advice and action are separated by design, not by a prompt.

> **The honesty line (say it proudly):** "We are not claiming to cure superbugs this weekend. We took the biggest swing we could and built the *control architecture* the cure will need — and we made it run on real hardware tonight."

---

## 2. The brainstorming & process story (judges explicitly grade this)

> New criterion: *"Does the project reflect a high level of effort put into brainstorming and iterating? We are not looking for 100% vibe-coded apps or AI wrappers."* — We lean into this hard.

Tell the iteration arc honestly:

1. **Started from the science, not the demo.** We began with the phage-therapy problem (Kurzgesagt "deadliest being on planet Earth" as motivation) and asked: what is the *actual engineering bottleneck* between "phages work" and "phages are standard care"? We landed on **closed-loop dosing of an oscillating system** — that's the insight the whole project is built around.
2. **Faced the constraint.** We can't culture a real pathogen at a hackathon (safety, ethics, time). So we asked: what is the simplest physical system that has the *same dynamical signature* — oscillation, damping, stall, rescue-by-resource-injection? The Blue Bottle reaction. This is a deliberate **analog-modeling** decision, not a gimmick.
3. **Architected for the real thing.** We didn't hard-code the Blue Bottle. The control layer is a **pluggable `Model` interface** (`observe(state) -> Action`). The PI controller is just the baseline `pi_baseline` model; a learned RL policy drops in without touching firmware, transport, or UI. This is the seam where a phage-dosing policy would plug in.
4. **Moved the brains off the browser — twice.** First version ran analysis in the browser. We refactored to a **headless Python backend** so the control loop keeps running with no UI open (a real bioreactor can't depend on an open tab), and so we can drop in sklearn/torch/RL. The `hub/` directory is the visible fossil record of that migration — we kept its device layer as the single source of truth and deprecated the rest.
5. **Designed the safety boundary deliberately.** When we added the Claude copilot, we made a conscious architectural choice: the assistant gets *no write tools*. The read-only guarantee is structural, not a prompt we hope holds.

The repo *shows* the iteration: a deprecated `hub/` dashboard, a built UI assembled from widget partials, a tested control core, an experiment write-up with explicit success criteria. This is the opposite of a vibe-coded wrapper.

---

## 3. What we actually built (the technical substance)

This is the "Most Technical Hack" ammunition. Know it cold.

### 3.1 System architecture

```
Browser (thin client)  ──WebSocket──►  backend/  (FastAPI + uvicorn, :8080)
  renders state                          • /ws: streams full state ~15 Hz, accepts commands
  sends commands                         • GET /config: hardware layout + roles + models
       ▲                                      │ shared StateStore / command queue / events
       │ ASK PHAGE (read-only)                ▼
  chat_server.py ──Anthropic API──►   DeviceWorker thread — the ONLY thread touching hardware
       (Claude Haiku 4.5)               20 Hz loop: read sensor → analyse → model decides → actuate
                                              │ (BLE, Nordic UART Service)
                                              ▼
                                ESP32 firmware (controller/) — stirrer, pumps, RGB sensor
```

**Six real engineering layers, all working** (firmware → transport → DSP → control → simulation/MPC → app/LLM):

1. **Firmware (`controller/controller.ino`)** — ESP32, Arduino. A *generic, runtime-configurable* pin API: the firmware boots with an empty pin registry and is told its pin map at runtime by a `configure` command — no reflash to move a device. PWM pins use `ledcAttach`/`ledcWrite` (5 kHz, 8-bit), digital pins toggle pumps. Reads a TCS34725 RGB sensor over I²C. Talks newline-delimited JSON over BLE.
2. **Transport / device link (`hub/transport/ble_transport.py`, `hub/controller.py`)** — BLE over the Nordic UART Service (`bleak` async loop in a daemon thread, exposed as a *synchronous* API; reassembles newline-delimited JSON; MTU 512). The backend re-pushes the pin map and re-asserts outputs on every reconnect, because the firmware loses its registry on reset. This robustness detail matters for a live demo.
3. **Signal analysis (`backend/analysis/detector.py`, `signal.py`)** — turns a noisy RGB stream into oscillation state. IR-corrected, white-balanced color → normalized blue intensity B̂ ∈ [0,1]. Extrema detection → **amplitude, half-period, period, cycle count, phase, and stall risk**. This is real-time DSP on sensor data.
4. **Control (`backend/control/`, `backend/sim/`, `backend/estimator/`)** — a mode machine (`arbiter.py`) with three modes sharing one device: **manual** (UI drives actuators), **auto** (a PI controller holding a target half-period on the stirrer + an event-triggered glucose pulse when amplitude decays), and **ml** (any registered `Model`). The `ml` registry already ships **three policies of escalating sophistication** — this is the depth that wins "Most Technical":
   - **`pi_baseline`** — the auto PI controller wrapped as a model. Interpretable on purpose; you can narrate exactly why it acted.
   - **`goal_blue`** — a *goal-seeking* controller. The operator sets a target hue + a deadline; a phase-aware heuristic decides whether to use the stirrer (O₂) to reach the goal now or to *time* the oscillation so the right phase lands at the deadline, and only feeds glucose/NaOH if the reaction is actually dying (rate-limited, with cooldowns).
   - **`goal_blue_mpc`** — **model-predictive control**. We fit a **grey-box ODE** of the reaction (a 4-state physical model: methylene-blue redox, dissolved O₂, glucose, pH) from *logged real-run data* via least-squares (`backend/sim/fit.py`). Each tick, an observer keeps the latent ODE state synced to the live sensor, the controller **enumerates all 16 candidate actions** (stirrer level × glucose × NaOH), **rolls each forward through the ODE**, and picks the one whose predicted hue at the deadline is closest to goal — with pump penalties so it prefers mixing over adding liquid. Critically, a **trust gate** only lets MPC drive *after the fitted model passes validation on a held-out run*. That's real "don't deploy a model you haven't validated" discipline, on hardware.
   - A **`StateEstimator`** (`backend/estimator/`) sits in front of all of them: it filters the jittery raw signal (EMA), tracks the oscillation baseline and a continuous **phase angle**, and computes stall risk — a clean, deterministic state with no sim-to-real gap. All params are tunable live: `target_half_period`, `amp_threshold`, `glucose_dose_ms`, goal hue/deadline.
5. **App + protocol (`backend/server.py`, `protocol/messages.py`, `state/`)** — FastAPI WebSocket streaming a full state snapshot ~15 Hz + incremental narration; thread-safe StateStore, command queue, event pairs. A headless `ws_probe` tool verifies the whole thing with no browser. Unit-tested control core (`make test`).

### 3.2 The control problem, concretely

- **Observation:** raw RGBC from the TCS34725, IR-corrected (`IR=(R+G+B−C)/2`) and white-balanced → scalar blue B̂.
- **Objective:** keep peak-to-trough blue amplitude > ~0.4 and half-period in the 15–45 s band, for a 20-minute run, with ≥10 full cycles and no stall gap > 90 s.
- **Actuators:** stirrer PWM (continuous — more O₂ → faster blue phase) and glucose pump (binary pulse — restores reducing power when amplitude decays for 2 consecutive cycles).
- **Why it's a real control problem:** the plant is *nonlinear, drifting, and self-damping*. Open-loop it always dies. Holding it at setpoint requires sensing + feedback — which is the whole point.
- **The progression we can show live:** PI (reactive) → goal-seeking (planning to a deadline) → MPC over a data-fitted ODE (predictive, validated before deployment). Three rungs of control sophistication on the *same* hardware and interface — a clean story of "we didn't stop at the obvious controller."

### 3.3 The Claude integration ("ASK PHAGE", `hub/chat_server.py`)

- A thin Flask server holds the Anthropic API key server-side (never ships to the browser) and streams **Claude (Haiku 4.5)** replies token-by-token to the UI's ASK PHAGE panel.
- The browser sends the question + recent chat history + a **snapshot of live reaction state** (amplitude/period/phase/etc.), so the assistant reasons about *this run, right now*.
- The chemistry briefing (from `experiment.md`) is folded into a stable, **prompt-cached** system prompt; only the per-turn live state varies.
- **The safety design:** the assistant has **no tools and no actuation path**. It can describe the reaction but *structurally cannot* control the stirrer, pumps, or anything else. "The read-only guarantee is structural, not just a prompt instruction." ← This sentence is in the code's own docstring. Quote it to judges.

### 3.4 The UI (Best UI/UX ammunition)

- A hand-built, draggable "console" desktop: panels for **Colour Log** (live RGB swatch + lux), **Oscillation** (the live waveform / world model), **Narration** (a running, human-readable log of what the controller is thinking and doing), **Console** (manual actuator control), **Calculator** (named, unit-tagged Blue-Bottle equations incl. a **phage⇄blue converter** mapping bacteriophage count to a blue shade on a log scale, and a °C⇄°F converter), **Ask Phage**, **Runs**, **Temp Notes**, **Actuators**.
- A landing page with a **physics-simulated 3D bacteriophage** — a hexagonal icosahedral head with tail fibers, shading and a specular highlight, drifting with wall-bounce and mouse-repulsion. A watercolor desk aesthetic, drifting-phage motion, soft-close windows. Built from widget partials (`frontend/src/widgets/*.html`) assembled by `build.js` — a real little build system, not one giant file.
- Header status is honest about hardware: `⬡ HARDWARE` / `◌ NO DEVICE` / `◌ OFFLINE` with auto-reconnect.

---

## 4. Track-by-track win strategy

We are eligible for and should explicitly target **five** tracks. Tailor the one-liner per judge.

| Track | Prize | Our angle (lead with this) | Emphasize | De-emphasize |
|---|---|---|---|---|
| **Ultimate Bots — Best Physical AI** | $3,000 + SF stage | "Code that closes the loop with real hardware." We literally do: sense → decide → actuate at 20 Hz on an ESP32-driven reactor. The judges' test is *"would a real robotics team use it?"* — our pluggable `Model` interface + headless backend + runtime-configurable firmware is exactly the control scaffold a lab automation / robotics team reuses. | Closed-loop on real hardware; reconnect robustness; pluggable policy; runs headless. | The chemistry trivia. |
| **Most Technical Hack** | 3D printers | Six real layers, no wrapper: firmware (runtime pin registry) → BLE/NUS transport → real-time DSP → **three-rung control stack (PI → goal-seeking → MPC over a data-fitted grey-box ODE, gated by held-out validation)** → full-stack streaming → LLM with a structural safety boundary. Unit-tested core. | The MPC + fitted-ODE + trust-gate story; BLE reconnect; white-balance color math; headless 20 Hz loop. | UI prettiness. |
| **Ddoski's Lab (Science & Engineering)** | $5,000 cash | Biotech + closed-loop control for a real health crisis (AMR). Grounded in actual chemistry (redox oscillation) and actual medicine (phage therapy), with explicit, measurable success criteria. | The science framing; AMR statistics; analog modeling as legitimate method. | — |
| **Anthropic** | $5,000 API credits + SF office hours | "The biggest swing toward the hardest problem." Antibiotic resistance is a civilization-scale health threat; we built the autonomy layer phage therapy needs, with Claude as a safe scientific copilot. Aspiration + effort, on real hardware. | The moonshot framing; Claude as read-only domain expert; health impact. | Over-claiming a cure. |
| **The Token Company** | Claude Code, money, merch | Depth of research + ingenuity: analog-modeling a predator–prey control problem with a chemical oscillator is a genuinely creative research move. | The brainstorming/iteration story (§2); research depth. | — |
| **Best UI/UX** | Kodak cameras | A distinctive, hand-built scientific console with live waveform, narration, and a watercolor aesthetic — not a dashboard template. | The console, narration panel, phage⇄blue converter. | Backend internals. |
| **Hacker's Choice** | Mechanical keyboards | Peer-voted: a *physical thing that visibly oscillates blue* on the table wins attention. Make the demo magnetic. | The live color change; let people press a button. | — |

**Strategic priority order** (where our edge is sharpest): **Ultimate Bots** and **Most Technical** first (the physical closed loop is rare and hard), then **Ddoski's Lab** and **Anthropic** (story + impact), then UI/UX and Hacker's Choice as bonus from a great demo.

---

## 5. Judging-criteria scorecard (rehearse one line of evidence per cell)

| Criterion | Our evidence (say this) |
|---|---|
| **Application** | AMR is a real, escalating health crisis; phage therapy is a real, FDA-trial-stage treatment whose adoption is gated on *dosing/control*. We built the control layer, and the same stack generalizes to any lab-automation / autonomous-experiment use case. |
| **Functionality / Quality** | It works end-to-end on real hardware, live: sensor → analysis → control → actuation, streamed to a polished UI. Unit-tested control core (`make test`), headless verification tool, graceful degradation (`◌ NO DEVICE` / auto-reconnect). |
| **Creativity** | Analog-modeling phage–bacteria predator–prey control with a *chemical* oscillator — and separating AI advice from AI action *structurally*. Neither is a pattern judges will have seen tonight. |
| **Technical Complexity** | Firmware + BLE + real-time DSP + a three-rung control stack (PI → goal-seeking → **MPC over a grey-box ODE fit from real data, with a held-out trust gate**) + full-stack streaming + LLM, integrated and tested. Other hard wins: runtime-configurable pin registry, BLE reconnect that re-asserts state, IR-corrected white-balanced color math, headless 20 Hz loop, state estimator with continuous phase tracking. |
| **Ethical Considerations** | The Claude copilot is **structurally read-only** — no write tool exists, so it cannot actuate near a patient even if prompted to. We chose a *safe chemical analog* over a live pathogen. We're explicit about what we have and haven't proven (no over-claiming a cure). Privacy: the API key stays server-side, never in the browser. |
| **Brainstorming & Process** | The whole §2 arc: problem-first, the analog-modeling decision, the browser→headless refactor (visible in the deprecated `hub/`), the pluggable `Model` seam for a future phage policy, the deliberate safety boundary. Demonstrably iterated, not vibe-coded. |

---

## 6. The live demo (the thing that actually wins)

**Total: ~3–4 minutes at the table.** The reaction is the star — let it change color while you talk.

**Pre-demo checklist (do BEFORE judges arrive):**
- [ ] Vessel charged, sensor white-balanced against blank water (`recalibrate`).
- [ ] ESP32 powered, advertising as `Bioreactor`; header shows `⬡ HARDWARE`.
- [ ] Backend up (`make backend`), UI up (`make ui`), ASK PHAGE server up (`make chat`, key set).
- [ ] Reaction already oscillating (it takes a minute to get going — don't cold-start in front of a judge).
- [ ] Have a fallback: a recorded screen capture + a saved `run_*.csv`, in case BLE drops.

**Choreography:**

1. **(0:00–0:30) The hook, while pointing at the oscillating vessel.** "This solution is alive in the way an infection is alive — it oscillates, and if we leave it alone, it *dies*. Watch." Show the live waveform in the Oscillation panel tracking the real color.
2. **(0:30–1:15) The problem.** Two sentences of superbugs + phage therapy, landing on: "Phage therapy is a *control* problem, and that's what we automated." Point at the Narration panel reading out the controller's decisions in real time.
3. **(1:15–2:15) The closed loop, live.** Switch to **auto** mode. Let the stirrer respond. Then *induce a stall* (or wait for amplitude to decay) and let the controller **fire the glucose pump to rescue it** — narrate the rescue as it happens. This is the money shot: the system saving its own reaction. If you can, show **manual** mode failing (amplitude decaying) first, then **auto** holding it — contrast sells it.
4. **(2:15–2:45) The AI copilot.** Ask PHAGE a live question — "why did you just dose glucose?" — and show Claude explaining *this run's* state. Then deliver the safety line: "Notice it can *explain* but it cannot *act* — it has no actuator tool, by construction."
5. **(2:45–3:15) The swing.** "Swap the chemistry for a phage–bacteria co-culture and this same stack is dosing therapy. We didn't cure superbugs this weekend — we built the autopilot the cure will need, and it's running on this table right now." Gesture at the hardware.

**Demo rules:**
- Always have the vessel oscillating before you start talking.
- Let one judge press a button (manual pulse) — tactile involvement wins Hacker's Choice.
- If BLE drops mid-demo, *say* "and here's our reconnect handling" and let it recover, or cut to the recording. Never apologize into dead air.

---

## 7. Slide deck outline (≤7 slides; the demo is the deck)

1. **Title.** PHAGENTIC + the one-liner + a photo of the rig oscillating. Logos of the 5 tracks small in the corner.
2. **The war we're losing.** AMR stat: superbugs could kill more than cancer by 2050; >23k US deaths/yr. One image.
3. **Nature's answer + the catch.** Phages = guided missiles that co-evolve. But it's an oscillating predator–prey *control* problem — single-dose doesn't work.
4. **Our insight.** Closed-loop autonomy is the missing layer. Analog-model it safely with an oscillating chemical reactor.
5. **What we built.** The architecture diagram (§3.1). Five layers, all live. "No part of this is mocked."
6. **The safety boundary + ethics.** Structural read-only AI; safe analog; no over-claiming. (Wins the new criteria.)
7. **The swing + the ask.** Same stack → phage dosing. What's next (real co-culture, learned policy). Thank the tracks by name.

> If presenting live with the rig: cut slides 5–6 and *demo them instead*. Show, don't tell.

---

## 8. Devpost writeup (draft)

### Inspiration
A war has raged for billions of years, killing trillions a day, and we barely notice: bacteriophages versus bacteria. For a century, antibiotics let us win — until bacteria evolved into superbugs resistant to nearly everything. By 2050, drug-resistant infections could kill more people annually than cancer. The most promising answer is the oldest one: bacteriophages, viruses that hunt a single bacterial species like a guided missile, ignore human cells, and co-evolve with their prey so they keep working. Phage therapy has already saved patients antibiotics couldn't. But a phage-versus-bacteria infection is a *living, oscillating, evolving* predator–prey system — and dosing it is a closed-loop control problem no human can do by hand at the bedside. We set out to build that autopilot.

### What it does
PHAGENTIC is an autonomous bioreactor that keeps an oscillating reaction alive at a target rhythm with zero human intervention. It watches the live color of a solution at 20 Hz, estimates the oscillation's amplitude, period, phase, and stall risk in real time, and drives a stirrer and pumps to hold the rhythm — automatically rescuing the reaction when it's about to die. A Claude-powered copilot, "ASK PHAGE," explains everything the controller is doing in plain language, while being *structurally incapable* of touching the hardware. We use the Blue Bottle reaction (a solution that oscillates blue ⇄ colorless and stalls when starved) as a safe, visible physical analog of the predator–prey dynamics that govern phage therapy. Swap the chemistry for a real phage–bacteria co-culture and the same control stack is dosing treatment.

### How we built it
- **Firmware:** ESP32 (Arduino) with a runtime-configurable pin registry — pins are assigned at runtime via a `configure` command, no reflash to rewire. PWM for the stirrer and sensor light, digital toggles for peristaltic pumps, I²C to a TCS34725 RGB sensor.
- **Device link:** BLE over the Nordic UART Service via `bleak`, exposed as a synchronous API. The backend re-pushes the pin map and re-asserts outputs on every reconnect.
- **Backend (headless Python, FastAPI + uvicorn):** a single DeviceWorker thread runs a 20 Hz loop — read sensor → analyze → decide → actuate. Real-time DSP (IR-corrected, white-balanced color → normalized blue; extrema detection → amplitude/period/phase/cycles/stall) feeds a state estimator that tracks a continuous oscillation phase. A mode arbiter switches between manual, an interpretable PI controller, and a pluggable ML `Model`. We built three policies: a PI baseline, a deadline-aware goal-seeking controller, and a **model-predictive controller** that fits a 4-state grey-box ODE of the reaction to logged data and plans actions by rolling candidates forward — only allowed to drive after the fitted model passes validation on a held-out run. State streams over a WebSocket ~15 Hz.
- **Frontend:** a hand-built draggable console (live waveform, narration log, calculator with a phage⇄blue converter, manual controls), assembled from widget partials by a small build script.
- **AI copilot:** a Flask server holds the Anthropic API key server-side and streams Claude (Haiku 4.5) replies; the live reaction state is injected per turn; the chemistry briefing is prompt-cached. The assistant has no write tools by design.

### Challenges we ran into
- BLE that survives the real world: the ESP32 forgets its pin registry on reset, so the backend has to detect reconnects and re-push configuration + re-assert outputs.
- Getting clean oscillation state out of a noisy color sensor (IR correction + white balance + robust extrema detection).
- Moving the brains off the browser so the control loop survives with no UI open — a real bioreactor can't depend on an open tab.
- Tuning an interpretable controller that's stable enough to demo live but visibly *acts* (so judges can see it think).

### Accomplishments we're proud of
A genuinely closed loop on real hardware — sense, decide, actuate — not a simulation. Three rungs of control on the same rig (PI → goal-seeking → MPC over a grey-box ODE fit from our own logged runs, gated by held-out validation). A pluggable control interface where a future phage-dosing policy drops in without touching firmware or UI. And a safety boundary that's structural, not aspirational: the AI literally cannot actuate.

### What we learned
That the gap between "phages work" and "phages are standard care" is largely an *autonomy and control* gap — and that you can prototype that control layer responsibly with a safe physical analog. We also learned how much robustness lives in the unglamorous parts (reconnect handling, calibration).

### What's next
Replace the chemical oscillator with a real phage–bacteria co-culture under BSL-appropriate conditions; train an RL dosing policy against the `Model` interface; add multi-vessel parallel runs; export richer datasets for training world models of microbial dynamics.

### Built with
ESP32 · Arduino · BLE (Nordic UART Service) · `bleak` · Python · FastAPI · uvicorn · WebSockets · TCS34725 RGB sensor · grey-box ODE + model-predictive control (pure-Python RK4, least-squares fit) · React (vendored renderer) · Anthropic Claude (Haiku 4.5) · Flask.

### 200-word writeup (Ultimate Bots Devpost requirement)
> PHAGENTIC is an autonomous bioreactor that closes the loop with real hardware. An ESP32 drives a stirrer and peristaltic pumps and reads an RGB sensor at 20 Hz over BLE; a headless Python backend analyzes the signal in real time (amplitude, period, phase, stall risk) and runs a control policy that holds an oscillating reaction at a target rhythm — and rescues it when it's about to die. We use the Blue Bottle reaction, a solution that oscillates blue ⇄ colorless and stalls when starved, as a safe physical analog of the predator–prey oscillations that govern bacteriophage therapy against antibiotic-resistant superbugs. Dosing phages is a closed-loop control problem no human can do by hand; PHAGENTIC is that autopilot. The control layer is a pluggable `Model` interface — a learned dosing policy drops in without touching firmware, transport, or UI — which is exactly the scaffold a real lab-automation or robotics team would reuse. A Claude copilot explains the live run in plain language but is structurally read-only: it has no actuator tool, so it cannot act near a sample. We didn't cure superbugs this weekend; we built, on real hardware, the control architecture the cure will need.

*(Count this and trim to ≤200 before submitting.)*

---

## 9. Q&A prep (hard questions + answers)

- **"This is just the Blue Bottle reaction — where's the phage?"** → "Deliberately. We can't responsibly culture a pathogen at a hackathon. We chose a physical system with the *same dynamical signature* — oscillation, damping, stall, rescue-by-resource-injection — to prove the control architecture safely. The control code doesn't know it's chemistry; swap in a co-culture and the policy is dosing therapy."
- **"Is the AI actually doing anything, or is it a PID controller?"** → "The *baseline* is an interpretable PI — on purpose, so we can show it thinking. But we went two rungs further: a deadline-aware goal-seeking controller, and a model-predictive controller that fits a grey-box ODE of the reaction from real run data and plans by rolling candidate actions forward — only deployed after it passes held-out validation. The architecture is a pluggable `Model` interface, so a learned RL policy is a drop-in too. And Claude is a read-only domain expert, separated from actuation by design. We were honest about which layer is which rather than dressing a PID as 'AI'."
- **"Would a real robotics/lab team use this?"** → "The reusable parts are exactly what they'd want: runtime-configurable firmware, robust BLE with reconnect/re-assert, a headless control loop that doesn't need a UI, and a clean policy interface. That's the lab-automation scaffold."
- **"What's the ethical risk of AI dosing patients?"** → "Real, which is why advice and action are split *structurally*. The copilot has no write tool — it cannot actuate even if prompted to. And we'd never deploy near a patient without the human-in-the-loop and clinical validation we're explicit about not having yet."
- **"How is this technically hard?"** → Walk the five layers (§3.1) and name a hard win in each.
- **"What broke / what's rough?"** → Be honest (see §10). Judges trust teams who know their own edges.

---

## 10. Pre-judging punch list (honest; fix what we can)

Polish, in priority order:

1. **Demo reliability > features.** Lock the happy path: charge → calibrate → oscillate → auto → induce stall → rescue → ask. Rehearse it 5×. Record a clean run as a fallback **video**.
2. **The stall→rescue moment must be reproducible.** Know how to trigger amplitude decay on demand (e.g., stop stirring / let glucose deplete) so the glucose-pump rescue fires when you want it, not randomly.
3. **ASK PHAGE key + server up**, and a canned good question ready ("why did you just dose glucose?").
4. **Header honesty:** make sure it shows `⬡ HARDWARE` before judges arrive; have the reconnect story ready if BLE drops.
5. **One-screen narration:** the Narration panel is our best "show the AI thinking" surface — make sure it's visible and readable from a judge's distance.
6. **Tighten the over-claim guardrails** in our own language: always say "control architecture / analog / autopilot," never "we cured" or "this is phage therapy."
7. **`frontend/logic.js` has uncommitted changes** — commit a known-good state before the event so we can always reset to it. (Ask Shira before any git commit/push.)
8. **Print a one-pager** (the §1 narrative + architecture diagram) to leave at the table for judges who arrive while we're mid-demo with another judge.

---

## 11. The single sentences to memorize

- **Hook:** "This solution is alive the way an infection is alive — it oscillates, and left alone, it dies. We built the autopilot that keeps it alive."
- **Insight:** "Phage therapy isn't a single shot — it's a closed-loop control problem, and that's the part nobody automated. We did."
- **Safety:** "Our AI can explain everything and touch nothing — the read-only guarantee is structural, not a prompt."
- **The swing:** "We didn't cure superbugs this weekend. We built, on real hardware, the control architecture the cure will need."
