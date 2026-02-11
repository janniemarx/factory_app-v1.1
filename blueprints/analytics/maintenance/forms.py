from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, SubmitField
from wtforms.validators import Optional

class MaintenanceAnalyticsFilterForm(FlaskForm):
    technician_id = SelectField('Technician', coerce=int, validators=[Optional()])
    status = SelectField('Status', choices=[('', 'All'), ('open','Open'),('assigned','Assigned'),('in_progress','In Progress'),('awaiting_review','Awaiting Review'),('closed','Closed')], validators=[Optional()])
    date_from = DateField('From', validators=[Optional()])
    date_to = DateField('To', validators=[Optional()])
    submit = SubmitField('Filter')
