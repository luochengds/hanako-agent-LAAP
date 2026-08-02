"""Compatibility namespace for the historical LAAP memory vault API.

The active memory implementation lives in :mod:`laap.memory`.  This package
keeps the small vault API used by the RSI/Truth Grounding integration stable
while the larger memory migration is completed.
"""

from .vault_manager import _open_vault_connection, vault_manager

__all__ = ["vault_manager", "_open_vault_connection"]
