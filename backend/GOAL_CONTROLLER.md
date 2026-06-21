# Goal-Seeking Controller — How to Train & Run It IRL

This is the controller that drives the Blue Bottle reaction to a **target blue
intensity** (`goal_blue`, 0..1) by a **target time** (`ideal_time`, seconds since
run start). You give it a goal; it picks the mixer level and (rarely) pumps.

There are two controllers, switchable at runtime:

| Model name        | Controller | Needs training? | When to use |
|-------------------|------------|-----------------|-------------|
| `goal_blue`       | heuristic  | **No**          | Start here. Phase-aware scheduler. No sim, no fitting, no deps. |
| `goal_blue_mpc`   | MPC        | Yes (fit ODE)   | Use only after fitting the ODE and passing the trust gate below. |

**Mixing is the primary lever.** Glucose and NaOH pumps add liquid volume (→
dilution/drift), so they are used *only* to rescue a collapsing oscillation
(glucose) or a stalled one (NaOH), never for routine hue/timing steering. Pump
usage is rate-limited and reported in `model_params` (`glucose_fired`,
`naoh_fired`, `*_ms_total`) — watch those for drift.

---

## What to do right now (get it working IRL, no training)

1. **Start the backend** (owns BLE + control loop):
   ```
   make backend
   ```
   Confirm it connects: `BLE connected — streaming.`

2. **Calibrate white balance** once the bottle is in place and lit. From the UI
   hit *recalibrate*, or:
   ```
   make probe PROBE_ARGS='--frames 1'      # sanity-check the stream first
   ```

3. **Select the goal controller and set a goal.** Easiest from the UI (mode → ml,
   model → `goal_blue`, then the goal params). Headless equivalent:
   ```
   make probe PROBE_ARGS='--mode ml'
   make probe PROBE_ARGS='--model goal_blue'
   make probe PROBE_ARGS='--set-params {"goal_blue":0.7,"ideal_time":180}'
   ```
   - `goal_blue` — target blueness 0..1 (watch the live `blue` value to pick a realistic target).
   - `ideal_time` — absolute seconds since run start. Prefer `time_to_goal` for
     "N seconds from now": `--set-params {"goal_blue":0.7,"time_to_goal":120}`.
   - After `reset_run` the clock zeroes — re-send the goal (or use `time_to_goal`).

4. **Watch it work.** The mixer should move through off/low/mid/high to land the
   target hue on time. `glucose_fired`/`naoh_fired` should stay **0** on a healthy
   reaction. If they climb, your reaction is genuinely weak (see Tuning).

That's a working closed loop. The heuristic needs no training and has no
sim-to-real gap (it consumes only the cleaned, normalized state).

---

## Training the MPC controller (optional, ~1 hour)

Do this only if the heuristic can't hit your timing targets tightly enough. The
MPC plans on a small grey-box ODE that must be **fit to your real reaction** —
an unfitted ODE will plan confidently wrong, so there is a trust gate.

### Step 1 — Collect real runs (~15 min, while running the reactor anyway)
With the backend up, record a few runs to JSONL. Each is just the live state
stream (read-only):
```
make log-run RUN=runs/free_low.jsonl     # then drive mixer=low for several cycles
make log-run RUN=runs/free_high.jsonl    # mixer=high for several cycles
make log-run RUN=runs/glucose.jsonl      # pulse glucose once, capture the recovery
make log-run RUN=runs/validate.jsonl     # a mixed/varied schedule — HELD OUT for validation
```
Drive the actuators manually (UI sliders or `make probe PROBE_ARGS='--set stirrer 255'`)
while each records. Aim for several oscillation cycles per run. Use the **frame's
own `t`** as the time base — the broadcast isn't perfectly uniform.

### Step 2 — Fit the ODE (~20 min)
```
make fit LOGS='runs/free_low.jsonl runs/free_high.jsonl runs/glucose.jsonl'
```
This writes `backend/sim/fitted_params.json` (auto-loaded by the MPC). It prints
initial vs fitted SSE.

### Step 3 — Trust gate (do NOT skip)
Validate on the **held-out** run:
```
make replay RUN=runs/validate.jsonl
```
Read the output:
- `phase slips: ~0` — the estimator (the firewall) tracks reality. This should
  hold regardless of fitting.
- `ODE blue RMSE` — must be **small (≈ ≤ 0.1)** and use **`fitted`** params (not
  `DEFAULT`). If it's high, the ODE doesn't model your reaction well enough —
  **stay on `goal_blue` (heuristic)** and do not deploy MPC.

### Step 4 — Deploy MPC
Only after the gate passes:
```
make probe PROBE_ARGS='--model goal_blue_mpc'
make probe PROBE_ARGS='--set-params {"goal_blue":0.7,"ideal_time":180}'
```
Or switch live without changing models: `--set-params {"controller":"mpc"}`.

### Step 5 — Validate on hardware, conservatively
1. **Shadow:** run a few minutes, compare MPC's mixer choices / notes against the
   heuristic. Confirm pumps are rare.
2. **Easy goal first:** comfortable deadline, mid-range `goal_blue`. Measure the
   real timing error.
3. Only then attempt tight deadlines / extreme hues.

The arbiter is your backstop throughout: a model exception holds all outputs, and
pump pulses are hard-clamped to 50–5000 ms.

---

## Tuning (all via `set_model_params`, no restart)

Pumps / volume (raise penalties or cooldowns if you see drift):
- `glucose_dose_ms` (default 300), `naoh_dose_ms` (250) — smaller = less volume per feed.
- The model self-limits with 25 s (glucose) / 60 s (NaOH) cooldowns.
- MPC only: `mpc_goal_tol` (0.05 — how close mixing must get before pumps are even
  considered; raise to use pumps *less*), `mpc_glucose_penalty` (0.06),
  `mpc_naoh_penalty` (0.15). Higher penalty ⇒ pump used less.

Behavior:
- `decision_hz` (2.0) — how often the controller re-decides (reaction is slow;
  20 Hz would just chatter the mixer).
- Heuristic only: `amp_floor` (0.15 — below this amplitude glucose rescues the
  reaction), `naoh_stall_thresh` (0.8 — stall_risk above this triggers pH support).
- MPC only: `mpc_horizon_s` (45) — planning lookahead.

Check current values any time: `make probe PROBE_ARGS='--frames 1'` and read
`model_params` in the state frame.

---

## How it works (one paragraph)

`backend/estimator/state_estimator.py` cleans the finicky raw RGB into a
normalized, dimensionless `CleanState` (EMA-smoothed blue, continuous phase
angle, amplitude, period, stall risk, mixer level) — a deterministic *filter*,
not a net, so it has no sim-to-real gap. The controller
(`backend/control/heuristic_controller.py` or `mpc_controller.py`) consumes only
that clean state and returns a discrete decision (mixer 0–3, glucose?, NaOH?),
which `backend/control/goal_model.py` maps to actuator commands at ~2 Hz with
pump cooldowns. The MPC additionally rolls a 4-state grey-box ODE
(`backend/sim/bluebottle_ode.py`, fit by `backend/sim/fit.py`) forward over the
16 discrete actions and picks the one landing closest to `goal_blue` at the
deadline — trying mixing alone first, adding pumps only if mixing can't get there.
