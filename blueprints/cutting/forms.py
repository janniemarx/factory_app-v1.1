# blueprints/cutting/forms.py

from flask_wtf import FlaskForm
from wtforms import (
    SelectField, IntegerField, FloatField, StringField, SubmitField, TextAreaField, FileField, BooleanField
)
from wtforms.validators import DataRequired, NumberRange, Optional, ValidationError

class StartWireCuttingSessionForm(FlaskForm):
    block_id = SelectField('Block', coerce=int, validators=[DataRequired()])
    machine_id = SelectField('Machine', coerce=int, validators=[DataRequired()])
    profile_code = SelectField('Profile', validators=[DataRequired()])
    submit = SubmitField('Start Cutting Session')

    def validate_machine_id(form, field):
        if field.data == 0:
            raise ValidationError('Please select a machine.')

class CaptureWireCuttingProductionForm(FlaskForm):
    profiles_cut = IntegerField(
        'Number of Cornices Cut',
        validators=[DataRequired(), NumberRange(min=1, max=2000, message="Must be a positive number")]
    )
    # Wastage field will just display the value (not editable by user)
    submit = SubmitField('Complete & Save Session')

class WireCuttingSessionFilterForm(FlaskForm):
    machine_id = SelectField('Machine', coerce=int, validators=[Optional()])
    profile_code = SelectField('Profile', validators=[Optional()])
    operator_id = SelectField('Operator', coerce=int, validators=[Optional()])
    submit = SubmitField('Filter')

class UploadCutPlanForm(FlaskForm):
    file = FileField('Upload Stock To Produce Excel', validators=[DataRequired()])
    submit = SubmitField('Upload')

class AssignmentOptionsForm(FlaskForm):
    allow_overtime = BooleanField('Allow overtime assignment (max 3 blocks per machine)')
    submit = SubmitField('Auto-Assign Blocks')
