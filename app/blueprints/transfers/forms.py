from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Optional, Length


class TransferForm(FlaskForm):
    source_location_id = SelectField("Source Location", coerce=int, validators=[DataRequired()])
    dest_location_id = SelectField("Destination Location", coerce=int, validators=[DataRequired()])
    remarks = StringField("Remarks", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Submit Transfer Request")
