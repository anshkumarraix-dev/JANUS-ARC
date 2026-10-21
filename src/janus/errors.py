"""Janus (ElderSync) — Structured Errors and Error Codes.

Defines stable, protocol-level error codes and human-safe conversational messages
for non-clinical eldercare operations.
"""

from __future__ import annotations

from typing import Optional


class ErrorCode:
    """Stable error codes published across JSON-RPC and REST interfaces."""

    INVALID_CATEGORY = "INVALID_CATEGORY"
    PROPOSAL_EXPIRED = "PROPOSAL_EXPIRED"
    PROPOSAL_NOT_FOUND = "PROPOSAL_NOT_FOUND"
    PROPOSAL_CANCELLED = "PROPOSAL_CANCELLED"
    MISSING_TRANSACTION_ID = "MISSING_TRANSACTION_ID"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    FORBIDDEN = "FORBIDDEN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


HUMAN_SAFE_MESSAGES = {
    ErrorCode.INVALID_CATEGORY: (
        "Only non-clinical daily routine categories (hydration, meal, vitamins, activity, wellness) "
        "are supported. Medical treatments and medications cannot be logged."
    ),
    ErrorCode.PROPOSAL_EXPIRED: (
        "This proposal expired after 5 minutes without confirmation. Please make a new request."
    ),
    ErrorCode.PROPOSAL_NOT_FOUND: (
        "The requested proposal was not found or has already been cleared."
    ),
    ErrorCode.PROPOSAL_CANCELLED: (
        "This proposal was cancelled and cannot be committed."
    ),
    ErrorCode.MISSING_TRANSACTION_ID: (
        "A valid transaction ID of a live pending proposal is required to commit this action."
    ),
    ErrorCode.INVALID_ARGUMENTS: (
        "The arguments provided are invalid or incomplete for this operation."
    ),
    ErrorCode.FORBIDDEN: (
        "This operation is restricted to non-clinical daily living routines. "
        "Clinical triage, medical orders, and prescription modifications are strictly prohibited."
    ),
    ErrorCode.INTERNAL_ERROR: (
        "A server error occurred while processing the request. Please try again."
    ),
}


class JanusError(ValueError):
    """Base exception for Janus with a stable error code and human-safe message."""

    def __init__(
        self,
        code: str,
        message: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        self.code = code
        self.human_message = message or HUMAN_SAFE_MESSAGES.get(code, "An error occurred.")
        self.details = details
        error_text = message if message else (f"{self.human_message} ({details})" if details else self.human_message)
        super().__init__(error_text)


class InvalidCategoryError(JanusError):
    """Raised when an unapproved or clinical category is submitted."""

    def __init__(self, category: str) -> None:
        super().__init__(
            code=ErrorCode.INVALID_CATEGORY,
            message=(
                f"Invalid category '{category}'. Non-clinical allowed categories are: "
                "activity, hydration, meal, vitamins, wellness."
            ),
        )


class ProposalExpiredError(JanusError):
    """Raised when attempting to confirm an expired proposal."""

    def __init__(self, transaction_id: str) -> None:
        super().__init__(
            code=ErrorCode.PROPOSAL_EXPIRED,
            message=f"Proposal '{transaction_id}' has expired.",
        )


class ProposalNotFoundError(JanusError):
    """Raised when a proposal transaction ID is not found."""

    def __init__(self, transaction_id: str) -> None:
        super().__init__(
            code=ErrorCode.PROPOSAL_NOT_FOUND,
            message=f"Proposal '{transaction_id}' was not found.",
        )


class ForbiddenOperationError(JanusError):
    """Raised when an operation violates non-clinical boundaries."""

    def __init__(self, reason: str = "Operation is outside non-clinical scope.") -> None:
        super().__init__(
            code=ErrorCode.FORBIDDEN,
            message=reason,
        )
