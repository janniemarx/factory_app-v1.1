# blueprints/boxing/forms.py

from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, HiddenField, TextAreaField, SubmitField, BooleanField, SelectMultipleField
from wtforms.validators import InputRequired, NumberRange, Optional, DataRequired

# 1. Start Boxing Session Form
class BoxingSessionStartForm(FlaskForm):
    # NEW: a single select carrying composite values like "cut:123" or "ext:456"
    source = SelectField(
        'Select Batch (Ready for Boxing)',
        validators=[InputRequired()],
        render_kw={"class": "form-select"}
    )
    submit = SubmitField('Start Boxing Session', render_kw={"class": "btn btn-primary btn-lg w-100"})

# 2. Finish Boxing Session Form
class BoxingSessionFinishForm(FlaskForm):
    boxes_packed = IntegerField(
        'Boxes Packed',
        validators=[InputRequired(), NumberRange(min=0)],
        render_kw={"placeholder": "Total boxes packed"}
    )
    leftovers = IntegerField(
        'Leftover Cornices',
        default=0,
        validators=[InputRequired(), NumberRange(min=0)],
        render_kw={"placeholder": "Leftover loose cornices"}
    )
    cycle_end = IntegerField(
        'Machine Cycle Counter (After Boxing)',
        validators=[InputRequired(), NumberRange(min=0)],
        render_kw={"placeholder": "e.g. 1234"}
    )
    submit = SubmitField('Complete & Save', render_kw={"class": "btn btn-success btn-lg w-100"})

# 3. Pause/Resume Form
class BoxingPauseForm(FlaskForm):
    pause = SubmitField('Pause', render_kw={"class": "btn btn-warning w-50"})
    resume = SubmitField('Resume', render_kw={"class": "btn btn-success w-50"})

# 4. Boxing Quality Control Form
class BoxingQualityControlForm(FlaskForm):
    boxes_checked = IntegerField(
        'Number of Boxes Checked',
        validators=[InputRequired(), NumberRange(min=1)],
        render_kw={"placeholder": "How many boxes did you QC?"}
    )
    notes = TextAreaField(
        'Problems Found (if any)',
        validators=[Optional()],
        render_kw={"rows": 3, "placeholder": "Describe any problems found during QC..."}
    )
    actions_taken = TextAreaField(
        'Actions Taken to Fix',
        validators=[Optional()],
        render_kw={"rows": 2, "placeholder": "Describe what was done to fix the problems..."}
    )
    submit = SubmitField('Complete QC & Mark as Stock Ready', render_kw={"class": "btn btn-primary btn-lg w-100"})

class UseLeftoversForm(FlaskForm):
    confirm_use = BooleanField('I have boxed all these leftover cornices and want to mark them as used.', validators=[DataRequired()])
    submit = SubmitField('Mark Leftovers as Used & Proceed')