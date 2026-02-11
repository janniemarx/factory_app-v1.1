from __future__ import annotations

"""Blocks (block making) routes.

Currently re-exports the legacy blueprint. We'll migrate handlers into this package next.
"""

from blueprints.blocks.routes import blocks_bp  # type: ignore

__all__ = ["blocks_bp"]
