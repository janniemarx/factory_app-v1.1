from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, SubmitField, FieldList, FormField
from wtforms.validators import DataRequired, NumberRange

MOULD_CHOICES = [
    (1, "Mould 1 (5 lines)"),
    (2, "Mould 2 (6 lines)"),
    (3, "Mould 3 (6 lines)")
]

PROFILE_CHOICES = [
    ('M01', 'M01'), ('M02', 'M02'), ('M03', 'M03'), ('M04', 'M04'), ('M05', 'M05'),
    ('M06', 'M06'), ('M07', 'M07'), ('M08', 'M08'), ('M09', 'M09'), ('M10', 'M10'),
    ('M11', 'M11'), ('M12', 'M12'), ('M13', 'M13')
]

class LineConfigForm(FlaskForm):
    profile_code = SelectField('Profile', choices=PROFILE_CHOICES, validators=[DataRequired()])

class StartMouldedCorniceSessionForm(FlaskForm):
    pre_expansion_id = SelectField('Pre-Expansion Batch', coerce=int, validators=[DataRequired()])
    machine_id = SelectField('Machine', coerce=int, validators=[DataRequired()])
    mould_number = SelectField('Mould Number', choices=MOULD_CHOICES, coerce=int, validators=[DataRequired()])
    line_configs = FieldList(FormField(LineConfigForm), min_entries=5, max_entries=6)
    submit = SubmitField('Start Moulded Cornice Session')

class AddCycleForm(FlaskForm):
    cycles_to_add = IntegerField('Number of Cycles', validators=[DataRequired(), NumberRange(min=1, max=999)])
    submit = SubmitField('Add Cycles')

class FinishMouldedCorniceSessionForm(FlaskForm):
    submit = SubmitField('Finish Session')
