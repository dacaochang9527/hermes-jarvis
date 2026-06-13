"""Shared lightweight data structures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamRating:
    """Attack and defense strength relative to league average."""

    name: str
    attack: float = 1.0
    defense: float = 1.0
