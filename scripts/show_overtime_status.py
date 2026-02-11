from __future__ import annotations
from datetime import datetime, date, time, timedelta

from app import create_app
from models import db
from models.operator import Operator
from models.attendance import AttendanceDaily, OvertimeRequest


def show_overtime_status():
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
            
        print(f"Overtime Status for {sam.full_name or sam.username}")
        print("=" * 60)
        
        # Look at recent week
        test_dates = [
            date(2025, 9, 1),   # Monday
            date(2025, 9, 2),   # Tuesday  
            date(2025, 9, 3),   # Wednesday
            date(2025, 9, 4),   # Thursday
            date(2025, 9, 5),   # Friday
            date(2025, 9, 6),   # Saturday
            date(2025, 9, 7),   # Sunday
        ]
        
        for d in test_dates:
            print(f"\n{d} ({d.strftime('%A')}):")
            
            # Raw attendance data
            daily = AttendanceDaily.query.filter_by(operator_id=sam.id, day=d).first()
            if daily:
                raw_ot1 = (daily.ot1_seconds or 0) / 3600.0
                raw_ot2 = (daily.ot2_seconds or 0) / 3600.0
                print(f"  Raw calculated OT: OT1={raw_ot1:.2f}h, OT2={raw_ot2:.2f}h")
            else:
                print("  No attendance data")
                continue
                
            # Overtime requests for this day
            ots = OvertimeRequest.query.filter_by(operator_id=sam.id, day=d).all()
            if ots:
                for ot in ots:
                    status_icon = "✓" if ot.status == 'approved' else "✗" if ot.status == 'rejected' else "⏳"
                    proposed = ot.proposed_hours or 0.0
                    approved = ot.hours or 0.0
                    print(f"  {status_icon} {ot.ot_type.upper()}: Proposed={proposed:.2f}h → Approved={approved:.2f}h ({ot.status})")
                    if ot.approved_by:
                        print(f"    Approved by: {ot.approved_by.full_name or ot.approved_by.username}")
                    if ot.reason:
                        print(f"    Reason: {ot.reason}")
            else:
                print("  No overtime requests")
        
        # Summary of approved overtime for reports
        print(f"\n{'='*60}")
        print("APPROVED OVERTIME TOTALS (for payroll reports):")
        approved_ots = OvertimeRequest.query.filter(
            OvertimeRequest.operator_id == sam.id,
            OvertimeRequest.day.between(test_dates[0], test_dates[-1]),
            OvertimeRequest.status == 'approved'
        ).all()
        
        total_approved = sum(float(ot.hours or 0.0) for ot in approved_ots)
        print(f"Total approved OT hours: {total_approved:.2f}h")
        
        by_type = {}
        for ot in approved_ots:
            by_type[ot.ot_type] = by_type.get(ot.ot_type, 0.0) + float(ot.hours or 0.0)
        
        for ot_type, hours in by_type.items():
            rate = "1.5x" if ot_type == 'ot1' else "2.0x" if ot_type == 'ot2' else "1.0x"
            print(f"  {ot_type.upper()}: {hours:.2f}h ({rate} rate)")


if __name__ == '__main__':
    show_overtime_status()
