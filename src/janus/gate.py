"""Janus (ElderSync) — Two-Step Safety Confirmation Gate.

Enforces the safety invariant:
All write/state-mutating operations MUST require a two-step confirmation flow:
1. confirm=False: Read-only proposal preview (0 database writes, status='PROPOSAL_PREVIEW').
2. confirm=True: Atomic commit (1 database write, status='COMMITTED') requiring a live transaction_id.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from janus import storage
from janus.errors import (
    ErrorCode,
    InvalidCategoryError,
    ProposalExpiredError,
    ProposalNotFoundError,
    SafetyBlockedError,
)
from janus.safety import (
    SafetyOutcome,
    assess_safety,
)


# Re-export core storage functions for proposal gate lifecycle
create_proposal = storage.create_proposal
get_proposal = storage.get_proposal
commit_proposal = storage.commit_proposal
cancel_proposal = storage.cancel_proposal
validate_category = storage.validate_category


class ConfirmationGate:
    """High-level safety gate controller enforcing the two-step confirmation pattern."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    def propose(
        self,
        senior_id: str,
        action_type: str,
        payload: Dict[str, Any],
        actor: str = "senior_voice",
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Generate a read-only proposal preview (0 database mutations to logs or handoffs)."""
        # Medical Safety Policy Check before proposal creation
        if action_type == "routine_log":
            cat = payload.get("category") or payload.get("routine_type")
            details = payload.get("details") or payload.get("notes") or ""
            # If details contains emergency, block immediately with highest priority
            if details:
                safety_res = assess_safety(details, category=cat)
                if safety_res.outcome == SafetyOutcome.EMERGENCY_GUIDANCE:
                    raise SafetyBlockedError(safety_res.outcome.value, safety_res.guidance, safety_res.matched_rule)
            if not cat:
                raise InvalidCategoryError("empty")
            payload["category"] = validate_category(cat)
            safety_res = assess_safety(details, category=payload["category"])
            if safety_res.outcome != SafetyOutcome.ROUTINE_ALLOWED:
                raise SafetyBlockedError(safety_res.outcome.value, safety_res.guidance, safety_res.matched_rule)
        elif action_type == "shift_handoff":
            notes = payload.get("handoff_notes") or ""
            safety_res = assess_safety(notes, category="wellness")
            if safety_res.outcome != SafetyOutcome.ROUTINE_ALLOWED:
                raise SafetyBlockedError(safety_res.outcome.value, safety_res.guidance, safety_res.matched_rule)

        return create_proposal(
            senior_id=senior_id,
            action_type=action_type,
            payload=payload,
            actor=actor,
            now=now,
            db_path=self.db_path,
        )

    def preview(
        self,
        transaction_id: str,
        now: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """Inspect a pending proposal without mutating state (0 database writes)."""
        prop = get_proposal(transaction_id, now=now, db_path=self.db_path)
        if not prop:
            raise ProposalNotFoundError(transaction_id)
        if prop.get("is_expired"):
            raise ProposalExpiredError(transaction_id)
        return prop

    def commit(
        self,
        transaction_id: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Commit a live proposal atomically. Returns COMMITTED or ALREADY_COMMITTED."""
        if not transaction_id:
            return {
                "status": "error",
                "error_code": ErrorCode.MISSING_TRANSACTION_ID,
                "message": "confirm=True REQUIRES a valid transaction_id of a live pending proposal.",
                "database_writes": 0,
            }
        return commit_proposal(transaction_id, now=now, db_path=self.db_path)

    def cancel(
        self,
        transaction_id: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Cancel a pending proposal."""
        return cancel_proposal(transaction_id, now=now, db_path=self.db_path)
