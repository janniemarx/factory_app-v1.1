from __future__ import annotations

from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user, login_required


def manager_required(view_func):
    """Require an authenticated manager account.

    Redirects non-managers to the home page with a message.
    """

    @wraps(view_func)
    @login_required
    def wrapper(*args, **kwargs):
        if not getattr(current_user, "is_manager", False):
            flash("Managers only.", "danger")
            return redirect(url_for("index"))
        return view_func(*args, **kwargs)

    return wrapper
