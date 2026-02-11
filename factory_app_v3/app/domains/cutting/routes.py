from __future__ import annotations

"""Cutting / wire cutting routes.

Currently re-exports the legacy blueprint. We'll migrate handlers into this package next.
"""

from blueprints.cutting.routes import cutting_bp  # type: ignore

__all__ = ["cutting_bp"]
