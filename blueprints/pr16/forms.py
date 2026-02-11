from flask_wtf import FlaskForm
from wtforms import (
    StringField, IntegerField, FloatField, DateTimeField,
    SubmitField, SelectField, BooleanField, TextAreaField, HiddenField,
)
from wtforms.validators import DataRequired, Optional, NumberRange, InputRequired

PARTIAL_ROLL_CHOICES = [
    ('0', 'None'),
    ('0.25', 'Quarter roll (~75 m)'),
    ('0.5', 'Half roll (~150 m)'),
    ('0.75', 'Three quarters (~225 m)'),
]

class StartPR16SessionForm(FlaskForm):
    block_id = SelectField('Block Number', coerce=int, validators=[DataRequired()])
    initial_glue_kg = FloatField('Initial Glue (kg)', validators=[DataRequired(), NumberRange(min=0.01)])
    initial_paper_m = FloatField('Initial White Paper (m)', validators=[Optional(), NumberRange(min=0.0)], default=0.0)
    start_partial_roll = SelectField('Starting Partial Roll', choices=PARTIAL_ROLL_CHOICES, default='0', validators=[DataRequired()])
    submit = SubmitField('Start PR16 Wrapping Session')


class AddResourceUsageForm(FlaskForm):
    glue_kg = FloatField('Additional Glue Used (kg)', validators=[Optional(), NumberRange(min=0.0)], default=0.0)
    paper_m = FloatField('Additional White Paper Used (m)', validators=[Optional(), NumberRange(min=0.0)], default=0.0)
    submit = SubmitField('Add Resource Usage')


class WrapProductionForm(FlaskForm):
    cornices_wrapped = IntegerField('Cornices Wrapped (qty)', validators=[DataRequired(), NumberRange(min=1)])
    submit = SubmitField('Log Wrapping Production')


class FinishWrappingForm(FlaskForm):
    end_partial_roll = SelectField('Leftover Partial Roll (at finish)', choices=PARTIAL_ROLL_CHOICES, default='0', validators=[DataRequired()])
    submit = SubmitField('Complete Wrapping & Start Drying')


class CompleteDryingForm(FlaskForm):
    submit = SubmitField('Drying Complete / Start Trimming')


class TrimmingLogForm(FlaskForm):
    trimming_start = DateTimeField('Trimming Start', validators=[Optional()])
    trimming_end = DateTimeField('Trimming End', validators=[Optional()])
    cornices_trimmed = IntegerField('Cornices Trimmed (qty)', validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField('Log Trimming Results')



