# blueprints/extrusion/forms.py
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField, DateTimeField, FloatField, IntegerField, SelectField,
    StringField, SubmitField, TextAreaField
)
from wtforms.validators import DataRequired, Optional, NumberRange, InputRequired, ValidationError

from models.extrusion import MaterialType, UsageUnit, ReadingType


def _enum_choices(e):
    return [(m.value, m.name.replace("_", " ").title()) for m in e]


class StartExtrusionSessionForm(FlaskForm):
    extruder_id = SelectField("Extruder", coerce=int, validators=[DataRequired()])
    profile_id  = SelectField("Profile",  coerce=int, validators=[DataRequired()])
    started_at  = DateTimeField("Start Time (optional)", validators=[Optional()])

    # was: DataRequired()
    checklist_answers_json = TextAreaField("Pre-start Checklist (JSON)", validators=[Optional()])
    checklist_approved     = BooleanField("Checklist Approved?", default=True)
    checklist_notes        = StringField("Checklist Notes", validators=[Optional()])

    notes  = StringField("Session Notes", validators=[Optional()])
    submit = SubmitField("Start Extrusion Session")

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators=extra_validators)
        if not ok:
            return False
        if not self.checklist_approved.data:
            self.checklist_approved.errors.append("Checklist must be approved before starting.")
            return False
        return True


class AddRatePlanForm(FlaskForm):
    effective_from = DateTimeField("Effective From", validators=[Optional()])

    rpm = IntegerField("RPM", validators=[Optional(), NumberRange(min=0)])
    gpps_kg_h = FloatField("GPPS (kg/h)", validators=[Optional(), NumberRange(min=0)])
    talc_kg_h = FloatField("Talc (kg/h)", validators=[Optional(), NumberRange(min=0)])
    fire_retardant_kg_h = FloatField("Fire Retardant (kg/h)", validators=[Optional(), NumberRange(min=0)])
    recycling_kg_h = FloatField("Recycling (kg/h)", validators=[Optional(), NumberRange(min=0)])
    co2_kg_h = FloatField("CO₂ (kg/h)", validators=[Optional(), NumberRange(min=0)])
    alcohol_l_h = FloatField("Alcohol (L/h)", validators=[Optional(), NumberRange(min=0)])

    submit = SubmitField("Save Rate Plan")


class MaterialUsageForm(FlaskForm):
    material = SelectField("Material", choices=_enum_choices(MaterialType), validators=[DataRequired()])
    unit = SelectField("Unit", choices=_enum_choices(UsageUnit), validators=[DataRequired()])
    quantity = FloatField("Quantity", validators=[InputRequired(), NumberRange(min=0.0)])
    note = StringField("Note", validators=[Optional()])

    submit = SubmitField("Log Usage")

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators=extra_validators)
        if not ok:
            return False

        mat = self.material.data
        unit = self.unit.data

        liquid = mat in (MaterialType.OIL.value, MaterialType.ALCOHOL.value)
        if liquid and unit not in (UsageUnit.LITRE.value, UsageUnit.CANS_5L.value):
            self.unit.errors.append("Liquids must be logged in L or 5L cans.")
            return False
        if not liquid and unit not in (UsageUnit.KG.value, UsageUnit.BAGS_25KG.value):
            if mat == MaterialType.CO2.value and unit == UsageUnit.KG.value:
                return True
            self.unit.errors.append("Solids must be logged in kg or 25kg bags.")
            return False
        return True


class CycleLogForm(FlaskForm):
    reading_type = SelectField("Reading Type",
                               choices=_enum_choices(ReadingType),
                               validators=[DataRequired()])
    reading_value = IntegerField("Counter", validators=[InputRequired(), NumberRange(min=0)])
    note = StringField("Note", validators=[Optional()])
    submit = SubmitField("Log Cycle Counter")


class PrestartChecklistForm(FlaskForm):
    answers_json = TextAreaField("Checklist JSON", validators=[DataRequired()])
    approved = BooleanField("Approved?", default=True)
    notes = StringField("Notes", validators=[Optional()])
    submit = SubmitField("Save Checklist")


class ProfileSettingsForm(FlaskForm):
    extruder_id = SelectField("Machine", coerce=int, validators=[DataRequired()])  # NEW

    # Machine-2 (existing)
    rpm = IntegerField("Extruder (RPM)", validators=[Optional(), NumberRange(min=0)])
    gpps_kg_h = FloatField("GPPS (kg/h)", validators=[Optional(), NumberRange(min=0)])
    talc_kg_h = FloatField("Talc (kg/h)", validators=[Optional(), NumberRange(min=0)])
    fire_retardant_kg_h = FloatField("Fire Retardant (kg/h)", validators=[Optional(), NumberRange(min=0)])
    recycling_kg_h = FloatField("Recycling (kg/h)", validators=[Optional(), NumberRange(min=0)])
    co2_kg_h = FloatField("CO₂ (kg/h)", validators=[Optional(), NumberRange(min=0)])
    alcohol_l_h = FloatField("Alcohol (L/h)", validators=[Optional(), NumberRange(min=0)])

    # Machine-1 (new Hz fields)
    extruder_hz = FloatField("Extruder (Hz)", validators=[Optional(), NumberRange(min=0)])
    co2_hz = FloatField("Pump1 CO₂ (Hz)", validators=[Optional(), NumberRange(min=0)])
    alcohol_hz = FloatField("Pump2 Alcohol (Hz)", validators=[Optional(), NumberRange(min=0)])
    oil_hz = FloatField("Pump3 Oil (Hz)", validators=[Optional(), NumberRange(min=0)])

    # Zones JSON
    heat_table_json = TextAreaField("Heat Table (JSON)", validators=[Optional()], render_kw={"rows": 6})
    notes = StringField("Notes", validators=[Optional()])

    # hidden (we still store it server-side)
    effective_from = DateTimeField("Effective From", validators=[Optional()])
    submit = SubmitField("Save Settings")


class ProfileForm(FlaskForm):
    code = StringField("Code", validators=[DataRequired()])
    length_m = FloatField("Length (m)", validators=[InputRequired(), NumberRange(min=0.01)])
    pieces_per_box = IntegerField("Pieces per Box", validators=[InputRequired(), NumberRange(min=1)])
    description = StringField("Description", validators=[Optional()])
    submit = SubmitField("Save Profile")


class BoxesClosedForm(FlaskForm):
    actual_boxes_boxed = IntegerField("Actual Boxes Boxed", validators=[InputRequired(), NumberRange(min=0)])
    submit = SubmitField("Save Actual Boxes")
