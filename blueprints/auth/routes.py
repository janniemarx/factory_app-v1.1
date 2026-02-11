from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse
import re
from models import db
from models.operator import Operator
from .forms import OperatorRegistrationForm, OperatorLoginForm


def _username_base_from_full_name(full_name: str) -> str:
    """Generate username as: firstname + first letter of surname.

    Example: "Jannie Marx" -> "janniem"
    """
    parts = [p for p in re.split(r"\s+", (full_name or "").strip()) if p]
    if not parts:
        return ""
    first = re.sub(r"[^a-z0-9]", "", parts[0].lower())
    last = re.sub(r"[^a-z0-9]", "", parts[-1].lower())
    if not first:
        return ""
    if last:
        return f"{first}{last[0]}"
    return first


def _unique_username_from_full_name(full_name: str) -> str:
    base = _username_base_from_full_name(full_name)
    if not base:
        return ""

    if not Operator.query.filter_by(username=base).first():
        return base

    # Collision: keep the rule but suffix a number (e.g. janniem2)
    for i in range(2, 100):
        candidate = f"{base}{i}"
        if not Operator.query.filter_by(username=candidate).first():
            return candidate
    return ""

auth_bp = Blueprint('auth', __name__, template_folder='../../templates/auth')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    form = OperatorLoginForm()

    if form.validate_on_submit():
        operator = Operator.query.filter_by(username=form.username.data).first()
        if operator and operator.check_password(form.password.data):
            if not getattr(operator, 'active', True):
                flash('Your account is inactive. Please contact an administrator.', 'danger')
                return render_template('auth/login.html', form=form)
            login_user(operator)
            flash('Logged in successfully!', 'success')
            next_page = request.args.get('next')
            if next_page and urlparse(next_page).netloc == "":
                return redirect(next_page)
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Allow open registration ONLY for the very first user (bootstrap).
    # After that, only managers can create accounts.
    if Operator.query.count() > 0:
        if not current_user.is_authenticated or not getattr(current_user, 'is_manager', False):
            flash('Only administrators can create new users.', 'danger')
            return redirect(url_for('auth.login'))

    form = OperatorRegistrationForm()
    if form.validate_on_submit():
        # Enforce username rule: firstname + first initial of surname
        full_name = (form.full_name.data or '').strip()
        if not full_name:
            flash('Full name is required.', 'danger')
            return render_template('auth/register.html', form=form)

        username = _unique_username_from_full_name(full_name)
        if not username:
            flash('Could not generate a username from the full name provided.', 'danger')
            return render_template('auth/register.html', form=form)
        new_operator = Operator(
            username=username,
            full_name=full_name,
            active=True,
            is_manager=form.is_manager.data or False  # <--- Set manager flag here!
        )
        new_operator.set_password(form.password.data)
        db.session.add(new_operator)
        db.session.commit()
        flash('Operator registered successfully!', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', form=form)


@auth_bp.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if not getattr(current_user, 'is_manager', False):
        flash('Unauthorized.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip().lower()
        try:
            if action == 'create':
                full_name = (request.form.get('full_name') or '').strip()
                password = request.form.get('password') or ''
                password2 = request.form.get('password2') or ''
                is_manager = bool(request.form.get('is_manager'))
                active = bool(request.form.get('active'))

                if not full_name:
                    flash('Full name is required.', 'danger')
                    return redirect(url_for('auth.admin_users'))
                if password != password2:
                    flash('Passwords do not match.', 'danger')
                    return redirect(url_for('auth.admin_users'))
                if not password:
                    flash('Password is required.', 'danger')
                    return redirect(url_for('auth.admin_users'))

                username = _unique_username_from_full_name(full_name)
                if not username:
                    flash('Could not generate a username from the full name provided.', 'danger')
                    return redirect(url_for('auth.admin_users'))

                op = Operator(username=username, full_name=full_name, active=active, is_manager=is_manager)
                op.set_password(password)
                db.session.add(op)
                db.session.commit()
                flash(f'User created: {username}', 'success')

            elif action in ('update', 'reset_password'):
                op_id = request.form.get('operator_id', type=int)
                op = Operator.query.get(op_id) if op_id else None
                if not op:
                    flash('User not found.', 'danger')
                    return redirect(url_for('auth.admin_users'))

                if op.id == current_user.id and action == 'update':
                    # Avoid locking the admin out by accident
                    requested_active = bool(request.form.get('active'))
                    requested_is_manager = bool(request.form.get('is_manager'))
                    if not requested_active:
                        flash('You cannot deactivate your own account.', 'danger')
                        return redirect(url_for('auth.admin_users'))
                    if not requested_is_manager:
                        flash('You cannot remove your own manager role.', 'danger')
                        return redirect(url_for('auth.admin_users'))

                if action == 'update':
                    requested_is_manager = bool(request.form.get('is_manager'))
                    requested_active = bool(request.form.get('active'))

                    # Prevent removing the last manager
                    if op.is_manager and not requested_is_manager:
                        other_managers = (
                            Operator.query
                            .filter(Operator.is_manager.is_(True), Operator.id != op.id)
                            .count()
                        )
                        if other_managers == 0:
                            flash('Cannot remove manager role from the last manager.', 'danger')
                            return redirect(url_for('auth.admin_users'))

                    op.is_manager = requested_is_manager
                    op.active = requested_active
                    db.session.commit()
                    flash('User updated.', 'success')

                elif action == 'reset_password':
                    new_password = request.form.get('new_password') or ''
                    if not new_password:
                        flash('New password is required.', 'danger')
                        return redirect(url_for('auth.admin_users'))
                    op.set_password(new_password)
                    db.session.commit()
                    flash('Password reset.', 'success')

            else:
                flash('Unknown action.', 'danger')

        except Exception as e:
            db.session.rollback()
            flash(f'Could not save changes: {e}', 'danger')

        return redirect(url_for('auth.admin_users'))

    users = Operator.query.order_by(Operator.username.asc()).all()
    return render_template('auth/admin_users.html', users=users)


@auth_bp.route('/')
def index():
    # Keep /auth/ as a convenience entrypoint, but serve the real dashboard at /
    return redirect(url_for('index'))