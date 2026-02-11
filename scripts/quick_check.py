from datetime import date
from app import create_app
from models.operator import Operator
from models.attendance import AttendanceDaily
from blueprints.attendance.db_helpers import recompute_range

def main(emp_no='MAL003', y=2025, m=9, d=12):
    app = create_app()
    with app.app_context():
        day = date(y, m, d)
        op = Operator.query.filter_by(emp_no=emp_no).first()
        if not op:
            print('Operator not found:', emp_no)
            return
        recompute_range(day, day, operator_ids=[op.id])
        daily = AttendanceDaily.query.filter_by(operator_id=op.id, day=day).one_or_none()
        if not daily:
            print('No daily row')
            return
        def hrs(x):
            return round((x or 0)/3600.0, 2)
        print('daily', daily.day, 'seg', daily.segment_count, 'miss_in', daily.missing_in, 'miss_out', daily.missing_out)
        print('first_in', daily.first_in, 'last_out', daily.last_out)
        print('worked_h', hrs(daily.worked_seconds), 'normal_h', hrs(daily.normal_seconds), 'ot1_h', hrs(daily.ot1_seconds), 'ot2_h', hrs(daily.ot2_seconds))

if __name__ == "__main__":
    main()
