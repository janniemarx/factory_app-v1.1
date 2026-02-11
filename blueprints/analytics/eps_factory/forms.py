from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, SubmitField
from wtforms.validators import Optional

class EPSAnalyticsFilterForm(FlaskForm):
    operator_id = SelectField('Operator', choices=[], coerce=int, validators=[Optional()])
    batch_no = SelectField('Batch Number', choices=[], validators=[Optional()])
    usage_type = SelectField('Usage Type', choices=[('', 'All'), ('Block', 'Block'), ('Moulded', 'Moulded')], validators=[Optional()])
    date_from = DateField('Date From', validators=[Optional()])
    date_to = DateField('Date To', validators=[Optional()])
    submit = SubmitField('Filter')

class AnalyticsFilterForm(FlaskForm):
    batch_no = SelectField("Batch Number", choices=[], validators=[Optional()])
    usage_type = SelectField("Purpose", choices=[('', '-- All --'), ('Block', 'Block'), ('Moulded', 'Moulded')], validators=[Optional()])
    date_from = DateField("From Date", validators=[Optional()])
    date_to = DateField("To Date", validators=[Optional()])
    submit = SubmitField("Filter")