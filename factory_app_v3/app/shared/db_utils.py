from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db


def safe_commit() -> tuple[bool, str | None]:
    """Commit current transaction and rollback on SQLAlchemyError."""
    try:
        db.session.commit()
        return True, None
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, str(e)
