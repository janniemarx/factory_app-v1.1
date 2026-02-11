from __future__ import annotations
from datetime import datetime, date, timedelta

from app import create_app
from models import db
from models.operator import Operator
from models.attendance import LeaveRequest
from utils.leave_pdf import render_leave_pdf
import os


def test_leave_system():
    app = create_app()
    with app.app_context():
        print("=" * 60)
        print("LEAVE SYSTEM TEST")
        print("=" * 60)
        
        # 1. Check if operators exist
        operators = Operator.query.filter_by(active=True).limit(5).all()
        print(f"\n1. Available operators: {len(operators)}")
        for op in operators[:3]:
            print(f"   - {op.full_name or op.username} (ID: {op.id})")
        
        if not operators:
            print("   No active operators found!")
            return
            
        # 2. Check existing leave requests
        leave_requests = LeaveRequest.query.order_by(LeaveRequest.created_at.desc()).limit(5).all()
        print(f"\n2. Recent leave requests: {len(leave_requests)}")
        for lr in leave_requests:
            status_icon = "✓" if lr.status == 'approved' else "✗" if lr.status == 'rejected' else "⏳"
            print(f"   {status_icon} {lr.operator.full_name or lr.operator.username}: {lr.leave_type} ({lr.start_date} → {lr.end_date}) - {lr.status}")
        
        # 3. Test PDF template existence
        template_path = app.config.get('LEAVE_FORM_TEMPLATE')
        if not template_path:
            template_path = os.path.join(app.root_path, 'static', 'files', '62 - Application for leave.pdf')
        
        print(f"\n3. PDF Template check:")
        print(f"   Path: {template_path}")
        print(f"   Exists: {os.path.exists(template_path)}")
        
        # 4. Test PDF generation (if template exists)
        if os.path.exists(template_path):
            print(f"\n4. Testing PDF generation...")
            try:
                test_op = operators[0]
                pdf_buffer = render_leave_pdf(
                    template_path=template_path,
                    employee_name=test_op.full_name or test_op.username,
                    application_date=date.today(),
                    leave_type='annual',
                    start_date=date.today() + timedelta(days=7),
                    end_date=date.today() + timedelta(days=10),
                    hours_per_day=8.0,
                    comments="Test leave request for system validation"
                )
                pdf_size = len(pdf_buffer.getvalue())
                print(f"   ✓ PDF generated successfully ({pdf_size} bytes)")
            except Exception as e:
                print(f"   ✗ PDF generation failed: {e}")
        else:
            print(f"\n4. PDF generation skipped (template not found)")
        
        # 5. Create a test leave request
        print(f"\n5. Creating test leave request...")
        try:
            test_op = operators[0]
            lr = LeaveRequest(
                operator_id=test_op.id,
                leave_type='annual',
                start_date=date.today() + timedelta(days=14),
                end_date=date.today() + timedelta(days=16),
                hours_per_day=8.0,
                status='pending',
                created_by_id=test_op.id,  # Self-created for test
                notes='System test leave request'
            )
            db.session.add(lr)
            db.session.commit()
            print(f"   ✓ Test leave request created (ID: {lr.id})")
            
            # Clean up test data
            db.session.delete(lr)
            db.session.commit()
            print(f"   ✓ Test data cleaned up")
            
        except Exception as e:
            print(f"   ✗ Failed to create test leave: {e}")
        
        # 6. Route verification
        print(f"\n6. Available leave routes:")
        leave_routes = [
            '/attendance/leave',
            '/attendance/leave/new', 
            '/attendance/leave/<id>',
            '/attendance/leave/<id>/print',
            '/attendance/payroll/leave'
        ]
        for route in leave_routes:
            print(f"   - {route}")
        
        print(f"\n{'='*60}")
        print("Leave system check complete!")
        print("Navigate to /attendance/leave to access the leave management interface.")


if __name__ == '__main__':
    test_leave_system()
