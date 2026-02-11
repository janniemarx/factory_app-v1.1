from __future__ import annotations

"""Quality control routes.

Currently re-exports the legacy blueprint. We'll migrate handlers into this package next.
"""

from blueprints.qc.routes import qc_bp  # type: ignore

__all__ = ["qc_bp"]
