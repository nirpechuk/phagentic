"""Deterministic state estimation — turns the finicky raw sensor stream into a
clean, normalized, dimensionless ``CleanState`` for the controller to consume.

This is the sim-to-real firewall: the only thing that crosses sim→real is
unitless phase/amplitude/level, never raw sensor counts. It is a filter, not a
learned net, so it has no transfer gap of its own.
"""
from backend.estimator.state_estimator import CleanState, StateEstimator

__all__ = ["CleanState", "StateEstimator"]
