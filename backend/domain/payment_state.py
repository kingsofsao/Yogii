from enum import Enum
from typing import Dict, Set

class PaymentState(str, Enum):
    DRAFT = "DRAFT"
    ASSESSING = "ASSESSING"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
    BLOCKED = "BLOCKED"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"

class InvalidStateTransitionError(Exception):
    """Raised when an illegal payment state transition is attempted."""
    def __init__(self, current_state: str, new_state: str):
        super().__init__(f"Illegal state transition from {current_state} to {new_state}")
        self.current_state = current_state
        self.new_state = new_state

# Strict state transition matrix
LEGAL_TRANSITIONS: Dict[PaymentState, Set[PaymentState]] = {
    PaymentState.DRAFT: {
        PaymentState.ASSESSING,
        PaymentState.FAILED
    },
    PaymentState.ASSESSING: {
        PaymentState.NEEDS_VERIFICATION,
        PaymentState.BLOCKED,
        PaymentState.PENDING,
        PaymentState.COMPLETED,
        PaymentState.FAILED
    },
    PaymentState.NEEDS_VERIFICATION: {
        PaymentState.PENDING,
        PaymentState.COMPLETED,
        PaymentState.BLOCKED,
        PaymentState.FAILED
    },
    PaymentState.PENDING: {
        PaymentState.COMPLETED,
        PaymentState.FAILED
    },
    PaymentState.COMPLETED: {
        PaymentState.REVERSED  # Only reversals allowed once completed
    },
    PaymentState.BLOCKED: set(),   # Terminal state: cannot change balance, cannot become completed
    PaymentState.FAILED: set(),    # Terminal state: cannot change balance, cannot become completed
    PaymentState.REVERSED: set()   # Terminal state
}

def validate_state_transition(current: str, target: str) -> None:
    """Validates that transitioning from `current` to `target` is legally permitted."""
    try:
        curr_enum = PaymentState(current)
        target_enum = PaymentState(target)
    except ValueError as e:
        raise InvalidStateTransitionError(current, target) from e

    if target_enum not in LEGAL_TRANSITIONS.get(curr_enum, set()):
        raise InvalidStateTransitionError(current, target)
