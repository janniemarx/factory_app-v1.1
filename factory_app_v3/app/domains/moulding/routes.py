from __future__ import annotations

"""Moulding routes.

Legacy exposes two separate top-level blueprints:
- moulded cornice:   /moulded (blueprint name 'moulded_cornice')
- moulded boxing:    /moulded_boxing (blueprint name 'moulded_boxing')

In v3 we keep those URLs stable by mounting both under a wrapper blueprint.
"""

from blueprints.moulded_cornice.routes import moulded_cornice_bp  # type: ignore
from blueprints.moulded_boxing.routes import moulded_boxing_bp  # type: ignore

# Note: app.app registers `moulding_bp` as a combined wrapper below.

from flask import Blueprint

moulding_bp = Blueprint("moulding", __name__)

# Mount legacy BPs under their existing prefixes to keep URLs stable
moulding_bp.register_blueprint(moulded_cornice_bp, url_prefix="/moulded")
moulding_bp.register_blueprint(moulded_boxing_bp, url_prefix="/moulded_boxing")

__all__ = ["moulding_bp"]
