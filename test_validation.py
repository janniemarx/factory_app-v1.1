#!/usr/bin/env python3
"""
Test script for consecutive check-in validation
"""
from app import app
from models import db, Operator
from models.attendance import AttendanceEvent
from blueprints.attendance.db_helpers import add_manual_event, _validate_and_fix_event_sequence
from datetime import date, datetime

def test_consecutive_checkin_validation():
    """Test the consecutive check-in validation and auto-correction"""
    with app.app_context():
        # Find an operator to test with
        op = Operator.query.first()
        if not op:
            print("No operators found for testing")
            return
        
        print(f"Testing with operator: {op.full_name or op.username} (ID: {op.id})")
        
        # Show recent events
        recent_events = AttendanceEvent.query.filter(
            AttendanceEvent.operator_id == op.id
        ).order_by(AttendanceEvent.timestamp.desc()).limit(5).all()
        
        print("\nRecent events:")
        for ev in recent_events:
            print(f"  {ev.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - {ev.event_type}")
        
        # Test the validation function directly
        print("\nTesting validation function:")
        
        # Case 1: check_in when last event was check_out (should remain check_in)
        if recent_events and recent_events[0].event_type == 'check_out':
            result = _validate_and_fix_event_sequence(op.id, op.emp_no, 'check_in', datetime.now())
            print(f"  check_in after check_out -> {result} (expected: check_in)")
        
        # Case 2: check_in when last event was check_in (should become check_out)
        if recent_events and recent_events[0].event_type == 'check_in':
            result = _validate_and_fix_event_sequence(op.id, op.emp_no, 'check_in', datetime.now())
            print(f"  check_in after check_in -> {result} (expected: check_out)")
        
        # Test with a different operator who might have different last event
        ops = Operator.query.limit(3).all()
        for test_op in ops:
            last_event = AttendanceEvent.query.filter(
                AttendanceEvent.operator_id == test_op.id
            ).order_by(AttendanceEvent.timestamp.desc()).first()
            
            if last_event:
                result = _validate_and_fix_event_sequence(test_op.id, test_op.emp_no, 'check_in', datetime.now())
                print(f"  {test_op.emp_no}: last={last_event.event_type}, check_in -> {result}")

if __name__ == "__main__":
    test_consecutive_checkin_validation()
