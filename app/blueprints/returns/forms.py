from flask_wtf import FlaskForm
from wtforms import SelectField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length


class ReturnForm(FlaskForm):
    source_location_id = SelectField("Source Location", coerce=int, validators=[DataRequired()])
    dest_location_id = SelectField("Return Destination", coerce=int, validators=[DataRequired()])
    reason = TextAreaField("Reason", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Submit Return Request")
