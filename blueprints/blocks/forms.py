from flask_wtf import FlaskForm
from wtforms import SelectField, FloatField, IntegerField, SubmitField, StringField, DateField, BooleanField
from wtforms.validators import DataRequired, NumberRange, Optional

class StartBlockSessionForm(FlaskForm):
    pre_expansion_id = SelectField('Pre-Expansion Batch', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Start Block Session')

class AddBlockForm(FlaskForm):
    weight = FloatField('Block Weight (kg)', validators=[DataRequired(), NumberRange(min=0.1)])
    heating1_time = IntegerField('Heating 1 Time (seconds)', validators=[DataRequired(), NumberRange(min=1)])
    heating2_time = IntegerField('Heating 2 Time (seconds)', validators=[DataRequired(), NumberRange(min=1)])
    heating3_time = IntegerField('Heating 3 Time (seconds)', validators=[DataRequired(), NumberRange(min=1)])
    cooling_time = IntegerField('Cooling Time (seconds)', validators=[DataRequired(), NumberRange(min=1)])
    is_profile16 = BooleanField('This is a Profile 16 (Mixed Material) Block')
    submit = SubmitField('Add Block')

class EditBlockForm(FlaskForm):
    weight = FloatField('Block Weight (kg)', validators=[DataRequired(), NumberRange(min=0.1)])
    heating1_time = IntegerField('Heating 1 Time (seconds)', validators=[DataRequired(), NumberRange(min=1)])
    heating2_time = IntegerField('Heating 2 Time (seconds)', validators=[DataRequired(), NumberRange(min=1)])
    heating3_time = IntegerField('Heating 3 Time (seconds)', validators=[DataRequired(), NumberRange(min=1)])
    cooling_time = IntegerField('Cooling Time (seconds)', validators=[DataRequired(), NumberRange(min=1)])
    is_profile16 = BooleanField('Profile 16 (Mixed Material)')
    submit = SubmitField('Save Changes')

class FinishBlockSessionForm(FlaskForm):
    submit = SubmitField('Finish Block Session')


class BlockSessionFilterForm(FlaskForm):
    profile_code = StringField('Profile', validators=[Optional()])
    density = SelectField('Density', choices=[], validators=[Optional()])   # <-- ADD THIS
    date_from = DateField('From', validators=[Optional()])
    date_to = DateField('To', validators=[Optional()])
    submit = SubmitField('Search')

