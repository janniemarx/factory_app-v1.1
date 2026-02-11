from __future__ import annotations

"""Extrusion routes.

Currently re-exports the legacy blueprint. We'll migrate handlers into this package next.
"""

from blueprints.extrusion.routes import extrusion_bp  # type: ignore

__all__ = ["extrusion_bp"]
