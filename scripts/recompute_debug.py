from datetime import date
import sys, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from app import create_app
from models import db
from models.operator import Operator
from blueprints.attendance.db_helpers import recompute_range

RANGE = (date(2025, 9, 1), date(2025, 9, 5))
EMP_NO = 'DIN002'

print('starting debug recompute...', flush=True)
app = create_app()
print('app created', flush=True)
try:
    with app.app_context():
        print('in app context', flush=True)
        op = Operator.query.filter_by(emp_no=EMP_NO).first()
        print('operator lookup done', bool(op), flush=True)
        if not op:
            print(f'Operator {EMP_NO} not found')
            raise SystemExit(1)
        cnt = recompute_range(*RANGE, operator_ids=[op.id])
        print('recomputed days:', cnt, flush=True)
        from models.attendance import AttendanceDaily
        rows = (AttendanceDaily.query
            .filter_by(operator_id=op.id)
            .filter(AttendanceDaily.day>=RANGE[0], AttendanceDaily.day<=RANGE[1])
            .order_by(AttendanceDaily.day)
            .all())
        for r in rows:
            print(f"{r.day} worked={r.worked_seconds/3600:.2f}h normal={r.normal_seconds/3600:.2f}h ot1={r.ot1_seconds/3600:.2f}h ot2={r.ot2_seconds/3600:.2f}h first_in={r.first_in} last_out={r.last_out}")
except Exception as e:
    import traceback
    traceback.print_exc()
