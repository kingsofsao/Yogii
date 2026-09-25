import pytest
from backend.domain.payment_state import (
    PaymentState, validate_state_transition, InvalidStateTransitionError
)

def test_legal_state_transitions():
    # Valid flow 1: Draft -> Assessing -> Completed -> Reversed
    validate_state_transition(PaymentState.DRAFT.value, PaymentState.ASSESSING.value)
    validate_state_transition(PaymentState.ASSESSING.value, PaymentState.COMPLETED.value)
    validate_state_transition(PaymentState.COMPLETED.value, PaymentState.REVERSED.value)

    # Valid flow 2: Assessing -> Needs Verification -> Completed
    validate_state_transition(PaymentState.ASSESSING.value, PaymentState.NEEDS_VERIFICATION.value)
    validate_state_transition(PaymentState.NEEDS_VERIFICATION.value, PaymentState.COMPLETED.value)

    # Valid flow 3: Assessing -> Blocked
    validate_state_transition(PaymentState.ASSESSING.value, PaymentState.BLOCKED.value)

    # Valid flow 4: Needs Verification -> Blocked
    validate_state_transition(PaymentState.NEEDS_VERIFICATION.value, PaymentState.BLOCKED.value)

    # Valid flow 5: Assessing -> Pending -> Completed
    validate_state_transition(PaymentState.ASSESSING.value, PaymentState.PENDING.value)
    validate_state_transition(PaymentState.PENDING.value, PaymentState.COMPLETED.value)

def test_blocked_state_is_terminal_and_cannot_mutate():
    with pytest.raises(InvalidStateTransitionError):
        validate_state_transition(PaymentState.BLOCKED.value, PaymentState.COMPLETED.value)

    with pytest.raises(InvalidStateTransitionError):
        validate_state_transition(PaymentState.BLOCKED.value, PaymentState.ASSESSING.value)

    with pytest.raises(InvalidStateTransitionError):
        validate_state_transition(PaymentState.BLOCKED.value, PaymentState.PENDING.value)

def test_failed_state_is_terminal_and_cannot_mutate():
    with pytest.raises(InvalidStateTransitionError):
        validate_state_transition(PaymentState.FAILED.value, PaymentState.COMPLETED.value)

    with pytest.raises(InvalidStateTransitionError):
        validate_state_transition(PaymentState.FAILED.value, PaymentState.ASSESSING.value)

def test_draft_cannot_skip_to_completed():
    with pytest.raises(InvalidStateTransitionError):
        validate_state_transition(PaymentState.DRAFT.value, PaymentState.COMPLETED.value)
