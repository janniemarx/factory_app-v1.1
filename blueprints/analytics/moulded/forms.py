from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, SubmitField
from wtforms.validators import Optional

class MouldedAnalyticsFilterForm(FlaskForm):
    mould_number = SelectField(
        'Mould',
        choices=[(0, '-- All Moulds --'), (1, 'Mould 1 (5 lines)'), (2, 'Mould 2 (6 lines)'), (3, 'Mould 3 (6 lines)')],
        coerce=int, validators=[Optional()]
    )
    # NEW: filter by machine (optional)
    machine_id = SelectField('Machine', choices=[(0, '-- All Machines --')], coerce=int, validators=[Optional()])

    operator_id = SelectField('Operator', choices=[], coerce=int, validators=[Optional()])
    date_from = DateField('From Date', validators=[Optional()])
    date_to = DateField('To Date', validators=[Optional()])

    # NEW: period for the Per-Machine table
    period = SelectField(
        'Period',
        choices=[('today', 'Today'), ('month', 'This Month'), ('year', 'This Year'), ('all', 'All Periods')],  # + all
        validators=[Optional()]
    )

    submit = SubmitField('Filter')