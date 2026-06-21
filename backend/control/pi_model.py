"""Baseline controller: PI on the stirrer + auto glucose pulse on amplitude decay.

Line-by-line port of frontend/logic.js control() (:201-205). This is what 'auto'
mode runs, and it doubles as the reference implementation of the Model contract.
"""
from backend.control.model import Action, Model, ReactionState


class PIModel(Model):
    name = "pi_baseline"

    def __init__(self):
        self.target_half_period = 25.0   # seconds
        self.amp_threshold = 0.40        # 0..1 (logic.js stored 5-95 % / 100)
        self.glucose_dose_ms = 500
        self._pi_i = 0.0
        self._low_amp = 0

    def observe(self, s: ReactionState) -> Action:
        act = Action()
        hp = s.half_period
        if hp > 0:
            err = self.target_half_period - hp
            self._pi_i = max(-80.0, min(80.0, self._pi_i + err * 0.02))
            act.stirrer = round(max(40.0, min(255.0, 150 - err * 4 - self._pi_i)))
        if s.cycle_event:
            if s.amp < self.amp_threshold:
                self._low_amp += 1
            else:
                self._low_amp = 0
            if self._low_amp >= 2:
                act.glucose_pulse_ms = self.glucose_dose_ms
                act.notes.append("Amplitude decayed — auto pulse glucose")
                self._low_amp = 0
        return act

    def get_params(self) -> dict:
        return {
            "target_half_period": self.target_half_period,
            "amp_threshold": self.amp_threshold,
            "glucose_dose_ms": self.glucose_dose_ms,
        }

    def set_params(self, p: dict) -> None:
        if "target_half_period" in p:
            self.target_half_period = max(1.0, float(p["target_half_period"]))
        if "amp_threshold" in p:
            self.amp_threshold = max(0.05, min(0.95, float(p["amp_threshold"])))
        if "glucose_dose_ms" in p:
            self.glucose_dose_ms = max(50, min(2000, int(p["glucose_dose_ms"])))

    def reset(self) -> None:
        self._pi_i = 0.0
        self._low_amp = 0
