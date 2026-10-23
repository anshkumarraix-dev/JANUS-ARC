"""JANUS-ARC — Authentication, Bearer Token Verification & Access Control.

Implements token validation, actor resolution, role-based access control,
and HTTP Authorization header parsing for non-clinical eldercare operations.
"""

from __future__ import annotations

import contextvars
import os
import re
from enum import Enum
from typing import Any, Dict, Optional, Set, Tuple, Union

from janus.errors import ErrorCode, JanusError

# Asynchronous identity contextvar for storing {role, allowed_seniors, actor}
current_identity: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "current_identity", default=None
)


def get_current_identity() -> Optional[Dict[str, Any]]:
    """Return the identity associated with the current asynchronous context."""
    return current_identity.get()


def set_current_identity(identity: Optional[Dict[str, Any]]) -> contextvars.Token:
    """Set the identity for the current asynchronous context."""
    return current_identity.set(identity)


class Role(str, Enum):
    """Authorized roles for non-clinical operations."""
    SENIOR = "senior"
    CAREGIVER = "caregiver"
    ADMIN = "admin"


# Explicit token table, enabled only when JANUS_DEMO_MODE=1
DEMO_TOKENS: Dict[str, Dict[str, Any]] = {
    "janus-demo-senior-margaret": {
        "actor": "senior_margaret",
        "role": Role.SENIOR.value,
        "allowed_seniors": {"margaret_01"},
    },
    "janus-demo-caregiver-sarah": {
        "actor": "caregiver_sarah",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"margaret_01"},
    },
    "janus-demo-caregiver-david": {
        "actor": "caregiver_david",
        "role": Role.CAREGIVER.value,
        "allowed_seniors": {"arthur_02"},
    },
}

DEMO_SENIOR_TOKEN = "janus-demo-senior-margaret"
DEMO_CAREGIVER_SARAH_TOKEN = "janus-demo-caregiver-sarah"
DEMO_CAREGIVER_DAVID_TOKEN = "janus-demo-caregiver-david"
DEMO_TOKEN = DEMO_SENIOR_TOKEN

# Backward-compatibility reference
DEFAULT_TOKENS = DEMO_TOKENS


def get_token_registry() -> Dict[str, Dict[str, Any]]:
    """Return registered authorization tokens.

    Demo tokens are enabled ONLY when JANUS_DEMO_MODE=1.
    An admin token with '*' is loaded ONLY from the JANUS_ADMIN_TOKEN environment variable.
    """
    registry: Dict[str, Dict[str, Any]] = {}

    raw_demo = os.environ.get("JANUS_DEMO_MODE", "0").strip().strip("'\"").lower()
    if raw_demo in ("1", "true", "yes", "on"):
        registry.update(DEMO_TOKENS)

    admin_token = os.environ.get("JANUS_ADMIN_TOKEN")
    if admin_token:
        clean_admin = admin_token.strip().strip("'\"")
        if clean_admin:
            registry[clean_admin] = {
                "actor": "admin",
                "role": Role.ADMIN.value,
                "allowed_seniors": {"*"},
            }

    return registry


class AuthError(JanusError):
    """Raised when authentication or authorization fails."""

    def __init__(self, message: str, code: str = ErrorCode.FORBIDDEN) -> None:
        super().__init__(code=code, message=message)


def extract_bearer_token(auth_header: Optional[str]) -> Optional[str]:
    """Extract Bearer token string from HTTP Authorization header.

    Examples:
        'Bearer abc123' -> 'abc123'
        'bearer abc123' -> 'abc123'
        'Bearer Bearer abc123' -> 'abc123'
        'Bearer "abc123"' -> 'abc123'
        'Token abc123'  -> None
        None            -> None
    """
    if not auth_header:
        return None
    match = re.match(r"^Bearer\s+(.+)$", auth_header.strip(), re.IGNORECASE)
    if not match:
        return None
    token = match.group(1).strip()
    # Strip any accidental repeated Bearer prefix
    token = re.sub(r"^(Bearer\s+)+", "", token, flags=re.IGNORECASE).strip()
    # Strip any surrounding matching quotes
    token = token.strip("'\"")
    return token if token else None


def verify_token(
    token: Optional[str],
    token_registry: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """Verify an authorization token against explicit token registry.

    Returns:
        (is_valid, claims_dict, reason)
    """
    if not token:
        return False, None, "Missing authorization token."

    registry = token_registry if token_registry is not None else get_token_registry()

    if token in registry:
        claims = dict(registry[token])
        if isinstance(claims.get("allowed_seniors"), (list, tuple)):
            claims["allowed_seniors"] = set(claims["allowed_seniors"])
        return True, claims, "Token authenticated."

    return False, None, "Invalid or unrecognized authorization token."


def check_senior_access(
    token_or_identity: Optional[Union[str, Dict[str, Any]]] = None,
    senior_id: Optional[str] = None,
    token_registry: Optional[Dict[str, Dict[str, Any]]] = None,
) -> bool:
    """Verify whether a token or identity is authorized to access a given senior profile."""
    target = token_or_identity if token_or_identity is not None else current_identity.get()
    if not target or not senior_id:
        return False

    if isinstance(target, dict):
        allowed: Set[str] = set(target.get("allowed_seniors", set()))
        return "*" in allowed or senior_id in allowed

    if isinstance(target, str):
        is_valid, claims, _ = verify_token(target, token_registry=token_registry)
        if not is_valid or not claims:
            return False
        allowed = set(claims.get("allowed_seniors", set()))
        return "*" in allowed or senior_id in allowed

    return False


def check_role_access(
    identity: Optional[Dict[str, Any]],
    action: str,
    senior_id: str,
) -> Tuple[bool, str]:
    """Enforce senior access and role rules for non-clinical eldercare operations.

    Role Rules (Requirement 4):
    - seniors log and confirm only for themselves
    - only caregivers may propose or confirm shift handoffs or read summaries for assigned seniors
    - admin has '*' and can perform any operation for any senior
    """
    if not identity:
        return False, "Unauthorized: missing or invalid caller identity."

    role = identity.get("role", "")
    allowed_seniors = set(identity.get("allowed_seniors", set()))
    actor = identity.get("actor", "unknown")

    # Admin with wildcard has full access
    if role == Role.ADMIN.value or "*" in allowed_seniors:
        return True, "Admin access granted."

    # Check senior profile access
    if senior_id not in allowed_seniors:
        return (
            False,
            f"Access to senior '{senior_id}' is forbidden for actor '{actor}' with allowed seniors {allowed_seniors}.",
        )

    # Role-specific rule enforcement
    if role == Role.SENIOR.value:
        # Seniors log and confirm only for themselves
        if action in ("log_routine", "confirm_routine", "flag_missed", "read_resource"):
            return True, f"Senior '{actor}' authorized for '{action}' on '{senior_id}'."
        elif action in ("read_summary", "propose_handoff", "confirm_handoff"):
            return (
                False,
                f"Role 'senior' is forbidden from executing '{action}'. Caregiver role is required.",
            )
        else:
            return False, f"Action '{action}' is not permitted for senior role."

    if role == Role.CAREGIVER.value:
        # Only caregivers may propose or confirm shift handoffs or read summaries for assigned seniors
        if action in (
            "log_routine",
            "read_summary",
            "propose_handoff",
            "confirm_handoff",
            "confirm_routine",
            "flag_missed",
            "read_resource",
        ):
            return True, f"Caregiver '{actor}' authorized for '{action}' on '{senior_id}'."
        else:
            return False, f"Action '{action}' is not permitted for caregiver role."

    return False, f"Unrecognized role '{role}'."


def get_actor_from_header(auth_header: Optional[str], default_actor: str = "senior_voice") -> str:
    """Resolve the caller identity from the Authorization header."""
    token = extract_bearer_token(auth_header)
    if token:
        is_valid, claims, _ = verify_token(token)
        if is_valid and claims and "actor" in claims:
            return claims["actor"]
    return default_actor
