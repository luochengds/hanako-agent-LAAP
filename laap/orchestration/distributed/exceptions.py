"""Exceptions for the distributed actor subsystem."""

from __future__ import annotations


class ActorRoutingError(Exception):
    """Raised when a message cannot be routed to a remote actor."""
