from backend.control.mpc_controller import MPCAmplitudeController, MPCController
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


def test_mpc_amplitude_drives_up_then_cuts_to_fade():
    """The MPC oscillator plans the rise (stirrer > 0 while below target) and cuts
    the stirrer once the peak is reached — the relay then fades passively."""
    ctrl = MPCAmplitudeController()
    ctrl.set_params({"target_amplitude": 0.5, "low_threshold": 0.1})
    rising = ctrl.decide(_clean(t=0.0, blue_level=0.15, mixer_level=0))
    assert rising.stirrer > 0                       # plans a climb toward the peak
    ctrl.decide(_clean(t=0.5, blue_level=0.5, mixer_level=2))   # reach peak → flip
    fading = ctrl.decide(_clean(t=1.0, blue_level=0.5, mixer_level=2))
    assert fading.stirrer == ctrl.drive_low         # stirrer cut: passive fade


def test_mpc_amplitude_higher_peak_needs_at_least_as_much_stir():
    """A bluer target peak should never be planned with less stirring."""
    lo = MPCAmplitudeController(); lo.set_params({"target_amplitude": 0.35})
    hi = MPCAmplitudeController(); hi.set_params({"target_amplitude": 0.6})
    a = lo.decide(_clean(t=0.0, blue_level=0.15, mixer_level=0))
    b = hi.decide(_clean(t=0.0, blue_level=0.15, mixer_level=0))
    assert b.stirrer >= a.stirrer


def _drive_online(ctrl, plant_p, secs=400.0, hz=2.0):
    """Run the controller closed-loop against an ODE plant, feeding observed blue
    back so the online buffer fills with real rise/fall excitation."""
    from backend.estimator.state_estimator import mixer_level_of
    y = [0.1, 0.1, plant_p["G0"], plant_p["P0"]]
    t, stir, dt = 0.0, 0, 1.0 / hz
    while t < secs:
        blue = blue_of(y[0], plant_p)
        d = ctrl.decide(_clean(t=t, blue_level=blue, mixer_level=mixer_level_of(stir)))
        stir = d.stirrer
        sub = max(1, int(dt / 0.1))
        from backend.sim.bluebottle_ode import STIR_LEVEL
        for _ in range(sub):
            y = rk4_step(y, dt / sub, STIR_LEVEL[mixer_level_of(stir)], plant_p)
        t += dt


def _drifted_plant(base, **scale):
    """A stationary (no slow reservoir decay → well-defined target) plant with the
    given rate constants scaled, so a tracking target actually exists."""
    p = dict(base)
    p["k_pd"] = p["k_gc"] = 0.0
    for k, f in scale.items():
        p[k] *= f
    return p


def test_online_learning_on_by_default_for_mpc():
    assert MPCAmplitudeController().online_learn is True


def test_online_learning_disabled_freezes_params():
    ctrl = MPCAmplitudeController()
    ctrl.set_params({"target_amplitude": 0.5, "online_learn": False})
    before = {k: ctrl.p[k] for k in ("k_ox", "k_red")}
    _drive_online(ctrl, _drifted_plant(ctrl._baseline_p, k_red=1.5))
    assert all(ctrl.p[k] == before[k] for k in before)      # untouched when off


def test_online_learning_tracks_a_drifted_plant_within_bounds():
    ctrl = MPCAmplitudeController()
    ctrl.set_params({"target_amplitude": 0.5, "online_learn": True,
                     "online_period_s": 20.0, "online_rate": 0.5})
    base_kred = ctrl._baseline_p["k_red"]
    plant = _drifted_plant(ctrl._baseline_p, k_red=1.4)      # faster fade
    _drive_online(ctrl, plant, secs=600.0)
    # adapted toward the (faster) plant, and stayed inside the ±band trust region
    assert ctrl.p["k_red"] > base_kred
    assert base_kred * 0.6 - 1e-9 <= ctrl.p["k_red"] <= base_kred * 1.4 + 1e-9


def test_online_learning_improves_prediction_vs_frozen_baseline():
    """The point of adapting: the live params should predict the drifted reaction
    better than the frozen offline baseline."""
    from backend.estimator.state_estimator import mixer_level_of
    from backend.sim.bluebottle_ode import STIR_LEVEL
    from backend.sim.fit import FIT_WINDOW_S, simulate
    ctrl = MPCAmplitudeController()
    ctrl.set_params({"target_amplitude": 0.5, "online_learn": True,
                     "online_period_s": 20.0, "online_rate": 0.5})
    baseline = dict(ctrl._baseline_p)
    plant = _drifted_plant(baseline, k_ox=0.8, k_red=1.4)    # weaker rise, faster fade
    _drive_online(ctrl, plant, secs=600.0)

    # collect a fresh validation window from the same (drifted) plant
    y = [0.1, 0.1, plant["G0"], plant["P0"]]; t = 0.0; buf = []
    for _ in range(360):
        lvl = 2 if (t % 50) < 15 else 0
        buf.append({"t": t, "blue": blue_of(y[0], plant), "mixer": lvl,
                    "glucose_edge": False, "naoh_edge": False})
        for _ in range(5):
            y = rk4_step(y, 0.1, STIR_LEVEL[lvl], plant)
        t += 0.5
    obs = [f["blue"] for f in buf]

    def sse(p):
        pred = simulate(buf, p, reseed_s=FIT_WINDOW_S, obs=obs)
        return sum((a - b) ** 2 for a, b in zip(pred, obs))

    assert sse(ctrl.p) < sse(baseline)
