"""Retry helper scaffolding for transient operations.

This module defines policy types and deterministic backoff calculation used
by network-bound components. Execution wrappers can be added in later phases.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RetryPolicy:
    """Retry policy parameters for exponential backoff."""

    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0


def next_backoff_seconds(attempt: int, policy: RetryPolicy) -> float:
    """Calculate bounded exponential backoff delay for an attempt number."""

    raw = policy.base_delay_seconds * (2 ** max(0, attempt - 1))
    return min(raw, policy.max_delay_seconds)
