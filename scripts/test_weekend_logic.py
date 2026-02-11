from __future__ import annotations
from datetime import datetime, date, time, timedelta

from app import create_app
from models import db
from models.operator import Operator
from models.attendance import AttendanceEvent, AttendanceDaily, OvertimeRequest
from blueprints.attendance.db_helpers import recompute_day


def test_weekend_logic():
    app = create_app()
    with app.app_context():
        # Find Samuel
        sam = Operator.query.filter(
            (Operator.full_name.ilike('%Samuel%')) | 
            (Operator.username.ilike('%Samuel%'))
        ).first()
        
        if not sam:
            print("Samuel not found")
            return
            
        print(f"Testing weekend logic for {sam.full_name or sam.username}")
        
        # Test recent Saturday and Sunday
        test_dates = [
            date(2025, 9, 6),  # Saturday
            date(2025, 9, 7),  # Sunday
        ]
        
        for d in test_dates:
            print(f"\n--- {d} ({d.strftime('%A')}) ---")
            
            # Recompute to apply new logic
            daily = recompute_day(sam, d)
            
            if daily and daily.worked_seconds > 0:
                dow = d.weekday()
                worked_h = daily.worked_seconds / 3600.0
                ot1_h = (daily.ot1_seconds or 0) / 3600.0
                ot2_h = (daily.ot2_seconds or 0) / 3600.0
                
                print(f"Worked: {worked_h:.2f}h")
                print(f"OT1: {ot1_h:.2f}h")
                print(f"OT2: {ot2_h:.2f}h")
                
                # Calculate expected equivalent hours for Hours(edit)
                lunch_h = 1.0  # assuming 1h lunch
                actual_work_h = worked_h - lunch_h
                
                if dow == 5:  # Saturday
                    expected_equiv = actual_work_h * 1.5
                    print(f"Expected: All {worked_h:.2f}h should be OT1")
                    print(f"Hours(edit) should show: {expected_equiv:.2f}h ({actual_work_h:.2f}h × 1.5)")
                    correct = (ot1_h == worked_h and ot2_h == 0)
                elif dow == 6:  # Sunday
                    expected_equiv = actual_work_h * 2.0
                    print(f"Expected: All {worked_h:.2f}h should be OT2")
                    print(f"Hours(edit) should show: {expected_equiv:.2f}h ({actual_work_h:.2f}h × 2.0)")
                    correct = (ot2_h == worked_h and ot1_h == 0)
                else:
                    correct = True
                    
                print(f"✓ Correct" if correct else "✗ Incorrect")
            else:
                print("No attendance data")
        
        db.session.commit()


if __name__ == '__main__':
    test_weekend_logic()
