from flask_wtf import FlaskForm
from wtforms import (
    SelectField, IntegerField, HiddenField, TextAreaField, SubmitField,
    BooleanField, FieldList, FormField
)
from wtforms.validators import InputRequired, NumberRange, DataRequired, Optional


class StartMouldedBoxingForm(FlaskForm):
    moulded_session_id = SelectField(
        'Select Moulded Session (Completed & Not Fully Boxed)',
        coerce=int,
        validators=[InputRequired()]
    )
    submit = SubmitField('Start Boxing')


class SaveLineForm(FlaskForm):
    session_id = HiddenField(validators=[DataRequired()])
    profile_code = HiddenField(validators=[DataRequired()])
    boxes_packed = IntegerField('Boxes', validators=[InputRequired(), NumberRange(min=0)], default=0)
    leftovers = IntegerField('Leftovers', validators=[InputRequired(), NumberRange(min=0)], default=0)
    save = SubmitField('Save Line')


class PauseResumeForm(FlaskForm):
    pause = SubmitField('Pause')
    resume = SubmitField('Resume')


class FinishMouldedBoxingForm(FlaskForm):
    finish = SubmitField('Finish Boxing (Pending QC)')


# ---------- QC (Per-profile) ----------

class ProfileBoxesForm(FlaskForm):
    """One QC row for a profile."""
    profile_code = HiddenField(validators=[DataRequired()])
    counted_boxes = IntegerField('Counted Boxes', validators=[InputRequired(), NumberRange(min=0)], default=0)


class MouldedBoxingQCForm(FlaskForm):
    """
    QC now records per-profile counted boxes.
    We still keep the old fields internally (we'll compute totals before saving).
    """
    rows = FieldList(FormField(ProfileBoxesForm), min_entries=0)
    confirm_all_boxes_complete = BooleanField(
        'I confirm all boxes for this session are complete and ready for selling.',
        validators=[DataRequired(message="Please confirm all boxes are complete.")]
    )
    discrepancy_reason = TextAreaField(
        'If counts do not match, explain why',
        validators=[Optional()],
        render_kw={"rows": 2, "placeholder": "Explain any discrepancy..."}
    )
    submit = SubmitField('Complete QC & Mark Stock Ready')
