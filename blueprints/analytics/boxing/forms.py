# blueprints/boxing/forms.py

from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, SubmitField
from wtforms.validators import Optional

class BoxingAnalyticsFilterForm(FlaskForm):
    operator_id = SelectField('Operator', coerce=int, choices=[], validators=[Optional()])
    date_from = DateField('From', validators=[Optional()])
    date_to = DateField('To', validators=[Optional()])
    period = SelectField('Period', choices=[('day', 'Day'), ('month', 'Month'), ('all', 'All')], validators=[Optional()])
    submit = SubmitField('Filter')
