# Blue Bottle Oscillating Reaction — Experiment Description

## Chemistry

The **Blue Bottle** reaction is a classic oscillating redox demonstration.

**Reagents (initial charge to the vessel):**
| Reagent | Role |
|---|---|
| Distilled water | Solvent |
| Dextrose (D-glucose) | Reducing agent; fuel for oscillations |
| NaOH | Alkaline medium required for glucose to reduce methylene blue |
| Methylene Blue (trace) | Redox indicator; blue when oxidized, colorless (leuco form) when reduced |

**Mechanism:**
1. In alkaline solution, glucose slowly reduces methylene blue to its colorless leuco form.
2. Stirring introduces dissolved O₂, which re-oxidizes leuco-MB back to blue.
3. Net result: the solution cycles blue → colorless → blue as the competing redox reactions proceed.
4. Oscillations dampen as glucose is consumed; adding more glucose (via the Glucose Pump) restarts them.

**Reagents added by the model during the run:**
- **Glucose Pump** — pulses a concentrated dextrose solution to replenish reducing power when oscillations dampen.
- **Chloride Pump** — reserved; can deliver a NaOH top-up to maintain alkalinity if pH drift damps oscillations early.

---

## Hardware Used

| Device | Pin | Mode | Role |
|---|---|---|---|
| Glucose Pump | GPIO 19 | digital (on/off) | Injects dextrose bolus |
| Chloride Pump | GPIO 18 | digital (on/off) | NaOH top-up (if needed) |
| Stirrer | GPIO 23 | PWM 0–255 | Controls O₂ introduction rate |
| Sensor Light | GPIO 25 | PWM 0–255 | Illuminates solution for TCS34725 |
| TCS34725 | I²C (SDA 21, SCL 22) | sensor | Measures RGBC at 20 Hz |

---

## What the Model Controls

The model is a feedback controller that reads the RGB sensor and actuates the stirrer and glucose pump to sustain oscillations at a target period.

**Observation:** raw RGBC from TCS34725, IR-corrected and white-balance-normalized → scalar blue channel intensity B̂ ∈ [0, 1].

**Control outputs:**
1. **Stirrer PWM** (continuous, 0–255) — primary knob. High duty cycle introduces O₂ quickly (drives blue phase); low duty cycle lets glucose reduction dominate (drives colorless phase). The model modulates this to shape oscillation period and amplitude.
2. **Glucose Pump pulse** (binary, triggered event) — fires a fixed-duration on pulse (~0.5 s) when oscillation amplitude has decayed below a threshold for two consecutive cycles. Restores reducing power without flooding the vessel.

**Control objective:** maintain peak-to-trough blue amplitude > 0.4 (normalized) for the full run duration, with an oscillation half-period in the 15–45 s range.

**Model type:** rule-seeded PID on stirrer PWM, with an event trigger for the glucose pump. The PID setpoint tracks the midpoint of the last observed swing; the event trigger fires if peak amplitude < 0.4 over a 2-cycle window. This gives interpretable behavior for a live demonstration.

---

## Time Horizon

| Phase | Duration | Description |
|---|---|---|
| Setup & calibration | ~2 min | Push `configure`, warm up sensor light, white-balance against blank water |
| Reaction initialization | ~1 min | Charge vessel, wait for first spontaneous colorless state |
| Controlled run | **20 min** | Model actively modulates stirrer + glucose pump |
| Cooldown / observation | ~2 min | Stirrer off, log final state, export time-series CSV |

**Total wall-clock: ~25 minutes.**

The 20-minute active window is chosen because:
- A single glucose charge sustains ~8–12 oscillations before dampening; with pump top-ups the model can extend this to 20+ cycles.
- Methylene Blue is not consumed, so the indicator remains effective for the full run.
- The demo fits a typical audience attention span and a single Jupyter session.

---

## Success Criteria

- ≥ 10 full blue ↔ colorless cycles observed during the 20-minute window.
- No cycle gap longer than 90 s (indicates stalled oscillation — model failure).
- Glucose Pump fires ≤ 4 times (more suggests tuning issue or reagent underdosing).
- Exported `run_YYYYMMDD_HHMMSS.csv` with columns `t_s, r, g, b, c, stirrer_pwm, glucose_pump, chloride_pump`.