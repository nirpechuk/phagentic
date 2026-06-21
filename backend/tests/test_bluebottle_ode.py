from backend.control.mpc_controller import MPCController
from backend.estimator.state_estimator import MIXER_PWM, CleanState
from backend.sim.bluebottle_ode import DEFAULT_PARAMS, blue_of, initial_state, rk4_step
from backend.sim.rollout import blue_at, rollout


def _clean(**over):
    base = dict(
        t=10.0, blue_level=0.5, baseline=0.5, amplitude=0.6, phase_angle=0.0,
        phase="blue", period=20.0, period_norm=1.0, stall_risk=0.0,
        cycle_event=False, mixer_level=2, mixer_onehot=(0, 0, 1, 0),
        goal_blue=None, time_remaining=None,
    )
    base.update(over)
    return CleanState(**base)


def test_rk4_keeps_states_physical():
    p = DEFAULT_PARAMS
    y = initial_state(p)
    for _ in range(2000):
        y = rk4_step(y, 0.5, 1.0, p)
    M, O, G, P = y
    assert 0.0 <= M <= 1.0 and O >= 0.0 and G >= 0.0 and P >= 0.0


def test_more_stirring_drives_bluer():
    """Higher mixer ⇒ more O2 ⇒ higher oxidised (blue) fraction at steady-ish state."""
    p = DEFAULT_PARAMS
    _, traj_lo = rollout(initial_state(p), 0, False, False, p, 60.0)
    _, traj_hi = rollout(initial_state(p), 3, False, False, p, 60.0)
    assert blue_at(traj_hi, 60.0) > blue_at(traj_lo, 60.0)


def test_glucose_pulse_pushes_colourless():
    p = DEFAULT_PARAMS
    _, base = rollout(initial_state(p), 2, False, False, p, 20.0)
    _, glu = rollout(initial_state(p), 2, True, False, p, 20.0)
    # extra reductant ⇒ less blue shortly after the pulse
    assert blue_at(glu, 10.0) <= blue_at(base, 10.0) + 1e-6


def test_mpc_returns_valid_action():
    mpc = MPCController()
    a = mpc.decide(_clean(goal_blue=0.7, time_remaining=30.0))
    assert a.stirrer in MIXER_PWM.values()
    assert isinstance(a.glucose, bool) and isinstance(a.naoh, bool)


def test_mpc_prefers_more_stirring_for_a_bluer_goal():
    mpc = MPCController()
    low = mpc.decide(_clean(goal_blue=0.15, time_remaining=40.0, blue_level=0.5))
    mpc.reset()
    high = mpc.decide(_clean(goal_blue=0.95, time_remaining=40.0, blue_level=0.5))
    assert high.stirrer >= low.stirrer


def test_blue_of_is_clamped():
    assert 0.0 <= blue_of(0.0, DEFAULT_PARAMS) <= 1.0
    assert blue_of(1.0, DEFAULT_PARAMS) <= 1.0
