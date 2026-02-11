from __future__ import annotations
from flask_wtf import FlaskForm
from wtforms import (
    StringField, TextAreaField, SelectField, SubmitField, BooleanField
)
from wtforms.validators import DataRequired, Optional, Length

PRIORITY_CHOICES = [("low","Low"),("normal","Normal"),("high","High"),("urgent","Urgent")]
CATEGORY_CHOICES = [("general","General"),("electrical","Electrical"),("mechanical","Mechanical"),("safety","Safety")]

class JobCreateForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", validators=[Optional()])
    location = StringField("Location/Area", validators=[Optional(), Length(max=120)])
    asset_code = StringField("Asset/Equipment Code", validators=[Optional(), Length(max=50)])
    priority = SelectField("Priority", choices=PRIORITY_CHOICES, default="normal", validators=[DataRequired()])
    category = SelectField("Category", choices=CATEGORY_CHOICES, default="general", validators=[DataRequired()])
    submit = SubmitField("Create Job")

class AcceptJobForm(FlaskForm):
    confirm = BooleanField("I will take this job", default=True)
    submit = SubmitField("Accept & Start Session")

class StepLogForm(FlaskForm):
    description = TextAreaField("What did you do?", validators=[DataRequired()])
    submit = SubmitField("Add Step")

class PauseResumeForm(FlaskForm):
    pause = SubmitField("Pause")
    resume = SubmitField("Resume")

class SessionCloseForm(FlaskForm):
    closing_summary = TextAreaField("Closing Summary", validators=[Optional()])
    submit = SubmitField("Complete Session")

class SubmitForReviewForm(FlaskForm):
    submit = SubmitField("Submit Job For Review")

class ReviewForm(FlaskForm):
    decision = SelectField("Decision", choices=[("approved","Approve"),("rework_requested","Request Rework")], validators=[DataRequired()])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Save Review")
