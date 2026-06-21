"""Grey-box simulator for the Blue Bottle reaction (pure Python, no numpy).

A coarse 4-state ODE surrogate used only to (a) rank the 16 discrete actions over
a short horizon inside the MPC controller and (b) tune/validate offline. It is
deliberately small and fit to logged runs; it is NOT a high-fidelity oscillator.
MPC deployment must be gated on measured fit quality (see backend/sim/fit.py).
"""
