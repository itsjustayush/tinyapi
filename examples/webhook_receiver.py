"""Backward-compatible import path.

Use examples.meteorbase_receiver for new services.
"""
from .meteorbase_receiver import METEORBASE_URL, SERVICE_SECRET, INTERNAL_SECRET, ping_meteorbase, require_meteorbase

__all__ = ["METEORBASE_URL", "SERVICE_SECRET", "INTERNAL_SECRET", "ping_meteorbase", "require_meteorbase"]
