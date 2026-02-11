from __future__ import annotations

"""PR16 routes.

Currently re-exports the legacy blueprint. We'll migrate handlers into this package next.
"""

from blueprints.pr16.routes import pr16_bp  # type: ignore

__all__ = ["pr16_bp"]
