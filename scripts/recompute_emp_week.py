import sys
from datetime import date

from app import create_app
from models import db
from models.operator import Operator
from blueprints.attendance.db_helpers import recompute_range


def main(emp_no: str, start: date, end: date) -> None:
    app = create_app()
    with app.app_context():
        op = Operator.query.filter_by(emp_no=emp_no).first()
        if not op:
            print(f"Operator not found: {emp_no}")
            return
        print(f"Recomputing {emp_no} from {start} to {end} (id={op.id})")
        recompute_range(start, end, operator_ids=[op.id])
        print("Done")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python scripts/recompute_emp_week.py EMP_NO YYYY-MM-DD YYYY-MM-DD")
        sys.exit(1)
    emp = sys.argv[1]
    y1, m1, d1 = map(int, sys.argv[2].split("-"))
    y2, m2, d2 = map(int, sys.argv[3].split("-"))
    main(emp, date(y1, m1, d1), date(y2, m2, d2))
