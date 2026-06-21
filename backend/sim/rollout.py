"""Forward rollout of the grey-box ODE — shared by MPC scoring and offline eval.

A rollout holds one mixer level and (optionally) fires glucose/NaOH pulses at
t=0, then integrates the ODE over a horizon, returning the latent endpoint and a
list of ``(t, blue)`` samples.
"""
from backend.sim.bluebottle_ode import (
    STIR_LEVEL, apply_pulse, blue_of, rk4_step,
)


def rollout(y0: list, mixer: int, glucose: bool, naoh: bool, p: dict,
            horizon_s: float, dt: float = 0.5) -> tuple[list, list]:
    """Return (y_end, [(t, blue), ...]) for one held action over the horizon."""
    y = apply_pulse(list(y0), glucose, naoh, p)
    stir = STIR_LEVEL[mixer]
    traj = [(0.0, blue_of(y[0], p))]
    t = 0.0
    n = max(1, int(round(horizon_s / dt)))
    for _ in range(n):
        y = rk4_step(y, dt, stir, p)
        t += dt
        traj.append((t, blue_of(y[0], p)))
    return y, traj


def blue_at(traj: list, t_target: float) -> float:
    """Linearly interpolate blue at ``t_target`` within a rollout trajectory."""
    if t_target <= traj[0][0]:
        return traj[0][1]
    if t_target >= traj[-1][0]:
        return traj[-1][1]
    for i in range(1, len(traj)):
        t1, b1 = traj[i]
        if t1 >= t_target:
            t0, b0 = traj[i - 1]
            f = (t_target - t0) / (t1 - t0) if t1 > t0 else 0.0
            return b0 + f * (b1 - b0)
    return traj[-1][1]
