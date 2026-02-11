from flask import Blueprint

# Create the blueprint here so submodules can import it without circular issues
attendance_bp = Blueprint('attendance', __name__)

# Import parent package route modules so their @attendance_bp.route handlers register
# These modules expect to import `attendance_bp` from `blueprints.attendance.routes` (this package).
from .. import leave_routes  # noqa: F401
from .. import overtime_routes  # noqa: F401
from .. import operator_routes  # noqa: F401
from .. import schedule_routes  # noqa: F401
from .. import sync_routes  # noqa: F401
from .. import event_routes  # noqa: F401
from .. import exception_routes  # noqa: F401
from .. import dashboard_routes  # noqa: F401

__all__ = ["attendance_bp"]
