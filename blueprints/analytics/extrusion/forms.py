from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, SubmitField
from wtforms.validators import Optional

class ExtrusionAnalyticsFilterForm(FlaskForm):
    extruder_id = SelectField('Extruder', coerce=int, validators=[Optional()])
    profile_id = SelectField('Profile', coerce=int, validators=[Optional()])
    date_from = DateField('From', validators=[Optional()])
    date_to = DateField('To', validators=[Optional()])
    submit = SubmitField('Filter')
