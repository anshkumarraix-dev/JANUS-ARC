"""Janus (ElderSync) — Base Pydantic Models.

Provides JanusBaseModel with backward-compatible dict subscripting and get() access,
allowing FastMCP tools to return fully typed Pydantic models without breaking callers
or tests expecting dictionary-like field access.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict


class JanusBaseModel(BaseModel):
    """Base Pydantic v2 model for Janus with backward-compatible dict subscripting."""

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    def __getitem__(self, item: str) -> Any:
        try:
            return getattr(self, item)
        except AttributeError:
            raise KeyError(item)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)
