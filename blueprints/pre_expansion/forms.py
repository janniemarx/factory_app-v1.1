from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, DateField, SelectField, SubmitField, BooleanField
from wtforms.validators import DataRequired
from datetime import date

class PreExpansionForm(FlaskForm):
    material_type = SelectField(
        'Material Type',
        choices=[('501', '501'), ('401', '401'), ('201', '201'), ('other', 'Other')],
        validators=[DataRequired()]
    )

    density = SelectField('Density (g/l)', choices=[(18, '18'), (23, '23')], coerce=int, validators=[DataRequired()])
    planned_kg = FloatField('Kg Material before expansion', validators=[DataRequired()])
    purpose = SelectField('Purpose', choices=[('Block', 'Block'), ('Moulded', 'Moulded')], validators=[DataRequired()])
    submit = SubmitField('Start Pre-Expansion')



class DensityCheckForm(FlaskForm):
    measured_density = FloatField('Measured Density (g/l)', validators=[DataRequired()])
    measured_weight = FloatField('Measured Weight (Kg)', validators=[DataRequired()])
    submit = SubmitField('Add Density Check')

class PreExpansionChecklistForm(FlaskForm):
    check1 = BooleanField('1. Check if all material in expansion chamber and in fluidized bed drier are cleared of lumps and other objects, and check agitating rods.', validators=[DataRequired()])
    check2 = BooleanField('2. Check air filter and oil lubricator. Remove water in filter and add Viscosity Grade 10 oil if oil level is low.', validators=[DataRequired()])
    check3 = BooleanField('3. Before opening main steam valve, open drain valve to let water out. Close drain valve.', validators=[DataRequired()])
    check4 = BooleanField('4. Check pressure, temperature, current, volt gauges and motors. Report and repair any malfunction.', validators=[DataRequired()])
    check5 = BooleanField("5. Check electronic scale, arrange calibration if not precise.", validators=[DataRequired()])
    check6 = BooleanField("6. Check earth connection.", validators=[DataRequired()])
    check7 = BooleanField("7. Check sealing of 80mm Butterfly valve on filling/vent ports. Replace seal if leakage.", validators=[DataRequired()])
    check8 = BooleanField("8. Check all valves/pipes. Repair any leaks.", validators=[DataRequired()])
    check9 = BooleanField("9. Manually test and check safety valve.", validators=[DataRequired()])
    check10 = BooleanField("10. Ensure copper pipe for pressure gauge switch is not blocked.", validators=[DataRequired()])
    check11 = BooleanField("11. After operation: Check all material is cleared.", validators=[DataRequired()])
    check12 = BooleanField("12. After operation: Check if power to conveyor, scale, drier and pre-expander is off.", validators=[DataRequired()])
    check13 = BooleanField("13. After operation: Check compressed air and steam valves are closed.", validators=[DataRequired()])
    submit = SubmitField('Checklist Complete - Start Pre-Expansion Session')

class MarkPastelForm(FlaskForm):
    submit = SubmitField('Mark as Captured')
