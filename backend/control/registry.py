"""Registry of available control models for 'ml' mode.

Map a name → zero-arg factory. The UI lists these (``list_models``) and selects
one with ``set_model``. Drop a new model in by importing it and adding an entry.
"""
from collections.abc import Callable

from backend.control.goal_model import GoalModel
from backend.control.model import Model
from backend.control.pi_model import PIModel

MODEL_REGISTRY: dict[str, Callable[[], Model]] = {
    "pi_baseline": PIModel,
    # Amplitude controller: oscillate blue between a target peak and ~0 (relay +
    # PID on the stirrer). This is the primary closed loop for "make it cycle".
    "amplitude_lock": lambda: GoalModel("amplitude"),
    # Hue controllers (target blue at a target time). They share GoalModel and the
    # `controller` model-param; `goal_blue` is the dependency-free heuristic,
    # `goal_blue_mpc` plans on the fitted grey-box ODE.
    "goal_blue": lambda: GoalModel("heuristic"),
    "goal_blue_mpc": lambda: GoalModel("mpc"),
}


def list_models() -> list[str]:
    return list(MODEL_REGISTRY)


def make_model(name: str) -> Model:
    if name not in MODEL_REGISTRY:
        raise KeyError(f"unknown model {name!r}; have {list_models()}")
    return MODEL_REGISTRY[name]()
