"""Session-lifecycle primitives; heavy modules are imported lazily."""

from .state import SessionState, StateTransitionError, can_transition

__all__ = [
    "SessionState",
    "StateTransitionError",
    "can_transition",
]
