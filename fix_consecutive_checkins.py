#!/usr/bin/env python3
"""
Utility script to find and fix consecutive check-in events
"""
from app import app
from models import db, Operator
from models.attendance import AttendanceEvent
from datetime import date, datetime
from sqlalchemy import func

def find_consecutive_checkins():
    """Find operators with consecutive check-in events"""
    with app.app_context():
        print("Searching for consecutive check-in events...")
        
        # Get all operators
        operators = Operator.query.all()
        issues_found = []
        
        for op in operators:
            # Get all events for this operator, ordered by timestamp
            events = AttendanceEvent.query.filter(
                AttendanceEvent.operator_id == op.id
            ).order_by(AttendanceEvent.timestamp.asc()).all()
            
            # Check for consecutive check_ins
            prev_event = None
            for event in events:
                if prev_event and prev_event.event_type == 'check_in' and event.event_type == 'check_in':
                    issues_found.append({
                        'operator': op,
                        'first_checkin': prev_event,
                        'second_checkin': event
                    })
                prev_event = event
        
        if issues_found:
            print(f"\nFound {len(issues_found)} consecutive check-in issues:")
            for issue in issues_found:
                op = issue['operator']
                first = issue['first_checkin']
                second = issue['second_checkin']
                print(f"\n{op.emp_no} ({op.full_name or op.username}):")
                print(f"  First check-in:  {first.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  Second check-in: {second.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  Suggestion: Convert second check-in to check-out")
        else:
            print("No consecutive check-in issues found!")
        
        return issues_found

def fix_consecutive_checkins():
    """Fix consecutive check-in events by converting the second one to check-out"""
    with app.app_context():
        issues = find_consecutive_checkins()
        
        if not issues:
            print("No issues to fix!")
            return
        
        print(f"\nFixing {len(issues)} consecutive check-in issues...")
        
        for issue in issues:
            second_checkin = issue['second_checkin']
            op = issue['operator']
            
            # Update the second check-in to check-out
            second_checkin.event_type = 'check_out'
            
            print(f"Fixed: {op.emp_no} - converted {second_checkin.timestamp.strftime('%Y-%m-%d %H:%M:%S')} to check-out")
        
        try:
            db.session.commit()
            print("All fixes committed successfully!")
            
            # Suggest recomputing affected days
            print("\nRecommendation: Recompute attendance for affected days to update overtime calculations.")
            
        except Exception as e:
            db.session.rollback()
            print(f"Error committing fixes: {e}")

if __name__ == "__main__":
    print("=== Consecutive Check-in Detection and Fix Utility ===")
    print()
    
    issues = find_consecutive_checkins()
    
    if issues:
        print("\nDo you want to fix these issues? (y/n): ", end="")
        response = input().strip().lower()
        if response == 'y':
            fix_consecutive_checkins()
        else:
            print("No changes made.")
    
    print("\nNote: The validation guard is now active and will prevent future consecutive check-ins.")
