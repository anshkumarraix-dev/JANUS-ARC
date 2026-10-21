"""Janus (ElderSync) — Authentication, Bearer Token Verification & Access Control.

Implements token validation, actor resolution, role-based access control,
and HTTP Authorization header parsing for non-clinical eldercare operations.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, Optional, Set, Tuple

from janus.errors import ErrorCode, JanusError

# Default authorized tokens
DEMO_TOKEN = "janus-demo-token-alexa-plus-2026"
DEFAULT_TOKENS = {
    DEMO_TOKEN: {
        "actor": "caregiver_david",
        "role": "caregiver",
        "allowed_seniors": {"margaret_01", "*"},
    },
    "senior-voice-token": {
        "actor": "senior_voice",
        "role": "senior",
        "allowed_seniors": {"margaret_01"},
    },
    "caregiver-sarah-token": {
        "actor": "caregiver_sarah",
        "role": "caregiver",
        "allowed_seniors": {"margaret_01"},
    },
}


class Role(str, Enum):
    """Authorized roles for non-clinical operations."""
    SENIOR = "senior"
    CAREGIVER = "caregiver"
    ADMIN = "admin"


class AuthError(JanusError):
    """Raised when authentication or authorization fails."""

    def __init__(self, message: str, code: str = ErrorCode.FORBIDDEN) -> None:
        super().__init__(code=code, message=message)


def extract_bearer_token(auth_header: Optional[str]) -> Optional[str]:
    """Extract Bearer token string from HTTP Authorization header.

    Examples:
        'Bearer abc123' -> 'abc123'
        'bearer abc123' -> 'abc123'
        'Token abc123'  -> None
        None            -> None
    """
    if not auth_header:
        return None
    match = re.match(r"^Bearer\s+(.+)$", auth_header.strip(), re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def verify_token(token: Optional[str], token_registry: Optional[Dict[str, Dict[str, Any]]] = None) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """Verify an authorization token.

    Returns:
        (is_valid, claims_dict, reason)
    """
    if not token:
        return False, None, "Missing authorization token."

    registry = token_registry if token_registry is not None else DEFAULT_TOKENS

    # Check direct match in known tokens
    if token in registry:
        claims = dict(registry[token])
        return True, claims, "Token authenticated."

    # Permissive fallback for demo tokens starting with 'janus-demo-'
    if token.startswith("janus-demo-"):
        claims = {
            "actor": "demo_user",
            "role": "caregiver",
            "allowed_seniors": {"*"},
        }
        return True, claims, "Demo token accepted."

    return False, None, "Invalid or unrecognized authorization token."


def check_senior_access(
    token: Optional[str],
    senior_id: str,
    token_registry: Optional[Dict[str, Dict[str, Any]]] = None,
) -> bool:
    """Verify whether a token is authorized to read/mutate data for a given senior profile."""
    # When no token is passed, allow ambient local simulator access for backward compatibility
    if not token:
        return True

    is_valid, claims, _ = verify_token(token, token_registry=token_registry)
    if not is_valid or not claims:
        return False

    allowed: Set[str] = set(claims.get("allowed_seniors", set()))
    if "*" in allowed or senior_id in allowed:
        return True

    return False


def get_actor_from_header(auth_header: Optional[str], default_actor: str = "senior_voice") -> str:
    """Resolve the caller identity from the Authorization header."""
    token = extract_bearer_token(auth_header)
    if token:
        is_valid, claims, _ = verify_token(token)
        if is_valid and claims and "actor" in claims:
            return claims["actor"]
    return default_actor
