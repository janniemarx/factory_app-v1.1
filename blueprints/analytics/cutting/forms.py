# blueprints/analytics/cutting/forms.py

from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField
from wtforms.validators import Optional

class WireCuttingSessionFilterForm(FlaskForm):
    machine_id = SelectField('Machine', coerce=int, validators=[Optional()])
    operator_id = SelectField('Operator', coerce=int, validators=[Optional()])
    profile_code = SelectField('Profile', validators=[Optional()])
    submit = SubmitField('Filter')
