"""Registry of available control models for 'ml' mode.

Map a name → zero-arg factory. The UI lists these (``list_models``) and selects
one with ``set_model``. Drop a new model in by importing it and adding an entry.
"""
from collections.abc import Callable

from backend.control.model import Model
from backend.control.pi_model import PIModel

MODEL_REGISTRY: dict[str, Callable[[], Model]] = {
    "pi_baseline": PIModel,
    # "my_torch_policy": MyTorchPolicy,   # ← real models register here
}


def list_models() -> list[str]:
    return list(MODEL_REGISTRY)


def make_model(name: str) -> Model:
    if name not in MODEL_REGISTRY:
        raise KeyError(f"unknown model {name!r}; have {list_models()}")
    return MODEL_REGISTRY[name]()
