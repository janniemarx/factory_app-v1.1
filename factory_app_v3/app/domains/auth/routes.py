from __future__ import annotations

"""Auth blueprint.

For the rewrite we reuse the legacy auth routes/templates so the app stays usable.
Later we can rewrite auth cleanly too.
"""

from flask import Blueprint

# Import legacy blueprint to avoid rewriting auth first.
from blueprints.auth.routes import auth_bp  # type: ignore

# Re-export under the new package namespace
__all__ = ["auth_bp"]
