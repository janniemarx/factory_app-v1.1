"""Minimal ETL to copy core data from v1 (factory.db) to v2 (factory_v2.db).
Run inside a Flask app context for v2 so SQLAlchemy models are available.

This script demonstrates the pattern and copies Operators and Profiles as a baseline.
Extend it to other entities as you finalize the v2 schema.
"""
import os
from sqlalchemy import create_engine, text
from v2.app import create_app, db
from v2.models.operator import Operator
from v2.models.profile import Profile

OLD_DB = os.environ.get('V1_DATABASE_URL', 'sqlite:///factory.db')


def copy_operators(old_engine):
    rows = old_engine.execute(text('SELECT id, username, full_name, is_manager FROM operator')).fetchall()
    for r in rows:
        op = Operator(id=r.id, username=r.username, full_name=r.full_name, is_manager=bool(r.is_manager))
        db.session.merge(op)
    db.session.commit()
    print(f"Copied {len(rows)} operators")


def copy_profiles(old_engine):
    rows = old_engine.execute(text('SELECT code, density, cornices_per_box, cornices_per_block FROM profile')).fetchall()
    for r in rows:
        p = Profile(code=r.code, density=r.density, cornices_per_box=r.cornices_per_box, cornices_per_block=r.cornices_per_block)
        db.session.merge(p)
    db.session.commit()
    print(f"Copied {len(rows)} profiles")


def main():
    app = create_app()
    with app.app_context():
        # Ensure tables exist
        db.create_all()
        old_engine = create_engine(OLD_DB)
        copy_operators(old_engine)
        copy_profiles(old_engine)
        print("ETL baseline complete. Extend for sessions and production data.")

if __name__ == '__main__':
    main()
