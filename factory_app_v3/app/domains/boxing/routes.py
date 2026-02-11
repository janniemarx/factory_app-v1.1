from __future__ import annotations

"""Boxing routes.

Currently re-exports the legacy blueprint. We'll migrate handlers into this package next.
"""

from blueprints.boxing.routes import boxing_bp  # type: ignore

__all__ = ["boxing_bp"]
