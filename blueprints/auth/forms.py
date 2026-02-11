from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Length

class OperatorLoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class OperatorRegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=50)])
    full_name = StringField('Full Name')
    password = PasswordField('Password', validators=[DataRequired()])
    is_manager = BooleanField('Is Manager?')   # <-- Add this field
    submit = SubmitField('Register')