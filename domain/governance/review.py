"""Review item state machine. A timeout never converts a hold into a pass."""

from __future__ import annotations

from enum import Enum

from ..utils.domain_errors import InvalidTransition

__all__ = ["ReviewState", "ReviewResolution", "next_state", "TERMINAL_REVIEW_STATES"]


class ReviewState(str, Enum):
    OPEN = "open"
    APPROVED = "approved"              # a scoped, expiring exception was granted
    REJECTED = "rejected"
    REPAIR_REQUESTED = "repair_requested"
    SUPERSEDED = "superseded"          # a newer run/decision replaced this item
    CANCELLED = "cancelled"


class ReviewResolution(str, Enum):
    APPROVE_EXCEPTION = "approve_exception"
    REJECT = "reject"
    REQUEST_REPAIR = "request_repair"


TERMINAL_REVIEW_STATES = {ReviewState.APPROVED, ReviewState.REJECTED, ReviewState.REPAIR_REQUESTED,
                          ReviewState.SUPERSEDED, ReviewState.CANCELLED}

_MAP = {
    ReviewResolution.APPROVE_EXCEPTION: ReviewState.APPROVED,
    ReviewResolution.REJECT: ReviewState.REJECTED,
    ReviewResolution.REQUEST_REPAIR: ReviewState.REPAIR_REQUESTED,
}


def next_state(state: ReviewState, resolution: ReviewResolution) -> ReviewState:
    if state != ReviewState.OPEN:
        raise InvalidTransition(f"review is already {state.value}")
    return _MAP[resolution]
