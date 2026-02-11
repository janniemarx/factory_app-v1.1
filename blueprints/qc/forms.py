from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, HiddenField, SubmitField
from wtforms.validators import DataRequired, NumberRange

from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, HiddenField, SubmitField, TextAreaField
from wtforms.validators import InputRequired, NumberRange, DataRequired

class QualityControlForm(FlaskForm):
    cutting_production_id = HiddenField("Cutting Production ID", validators=[DataRequired()])

    cornices_count_operator = IntegerField(
        "Cornices Count (Operator)", render_kw={'readonly': True}
    )
    cornices_count_qc = IntegerField(
        "Cornices Count (QC)", validators=[InputRequired(), NumberRange(min=0)]
    )
    bad_cornices_count = IntegerField(
        "Bad Cornices (Waste)", validators=[InputRequired(), NumberRange(min=0)]
    )

    rated_areo_effect = SelectField(
        "Areo Effect", choices=[(i, str(i)) for i in range(1, 11)], coerce=int, validators=[InputRequired()]
    )
    rated_eps_binding = SelectField(
        "EPS Binding", choices=[(i, str(i)) for i in range(1, 11)], coerce=int, validators=[InputRequired()]
    )
    rated_wetspots = SelectField(
        "Wetspots", choices=[(i, str(i)) for i in range(1, 11)], coerce=int, validators=[InputRequired()]
    )
    rated_dryness = SelectField(
        "Dryness", choices=[(i, str(i)) for i in range(1, 11)], coerce=int, validators=[InputRequired()]
    )
    rated_lines = SelectField(
        "Lines", choices=[(i, str(i)) for i in range(1, 11)], coerce=int, validators=[InputRequired()]
    )

    submit = SubmitField("Complete QC & Mark as Boxing Ready")


class PR16QualityControlForm(FlaskForm):
    session_id = HiddenField(validators=[DataRequired()])

    cornices_count_operator = IntegerField(
        "Cornices Count (Operator)", render_kw={"readonly": True}
    )
    cornices_count_qc = IntegerField(
        "Cornices Count (QC)", validators=[InputRequired(), NumberRange(min=0)]
    )
    bad_cornices_count = IntegerField(
        "Bad Cornices (Waste)", validators=[InputRequired(), NumberRange(min=0)]
    )

    notes = TextAreaField("QC Notes")
    submit = SubmitField("Complete PR16 QC & Mark as Boxing Ready")