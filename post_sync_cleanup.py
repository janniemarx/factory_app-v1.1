#!/usr/bin/env python3
"""
Post-sync cleanup script to fix consecutive check-ins and recompute attendance
"""
from app import app
from models import db, Operator
from models.attendance import AttendanceEvent
from blueprints.attendance.db_helpers import recompute_range
from datetime import date, datetime, timedelta
from sqlalchemy import and_

def fix_consecutive_checkins_post_sync(start_date=None, end_date=None):
    """
    Fix consecutive check-ins after sync is complete.
    This runs after all events are loaded to avoid transaction conflicts.
    """
    with app.app_context():
        if not start_date:
            # Default to last 30 days
            end_date = date.today()
            start_date = end_date - timedelta(days=30)
        
        print(f"Fixing consecutive check-ins for period {start_date} to {end_date}")
        
        # Get all operators
        operators = Operator.query.all()
        total_fixes = 0
        
        for op in operators:
            print(f"Checking {op.emp_no} ({op.full_name or op.username})...")
            
            # Get all events for this operator in the date range, ordered by timestamp
            events = AttendanceEvent.query.filter(
                and_(
                    AttendanceEvent.operator_id == op.id,
                    AttendanceEvent.timestamp >= datetime.combine(start_date, datetime.min.time()),
                    AttendanceEvent.timestamp <= datetime.combine(end_date, datetime.max.time())
                )
            ).order_by(AttendanceEvent.timestamp.asc()).all()
            
            if not events:
                continue
            
            # Check for consecutive check_ins and fix them
            fixes_for_operator = 0
            prev_event = None
            
            for event in events:
                if (prev_event and 
                    prev_event.event_type == 'check_in' and 
                    event.event_type == 'check_in'):
                    
                    # Convert the second check_in to check_out
                    print(f"  Fix: {event.timestamp} check_in -> check_out")
                    event.event_type = 'check_out'
                    fixes_for_operator += 1
                    total_fixes += 1
                
                prev_event = event
            
            if fixes_for_operator > 0:
                print(f"  Fixed {fixes_for_operator} consecutive check-ins for {op.emp_no}")
        
        if total_fixes > 0:
            try:
                db.session.commit()
                print(f"\nSuccessfully fixed {total_fixes} consecutive check-ins!")
                
                # Recompute attendance for the affected period
                print(f"Recomputing attendance for {start_date} to {end_date}...")
                affected_days = recompute_range(start_date, end_date)
                print(f"Recomputed {affected_days} days")
                
                # Suggest overtime recalculation
                print("\nRecommendation: Go to Attendance > Sync and run 'Propose Overtime' for this period.")
                
            except Exception as e:
                db.session.rollback()
                print(f"Error committing fixes: {e}")
        else:
            print("No consecutive check-ins found!")

if __name__ == "__main__":
    print("=== Post-Sync Consecutive Check-in Cleanup ===")
    print()
    
    # You can specify date range here or it will default to last 30 days
    fix_consecutive_checkins_post_sync()
