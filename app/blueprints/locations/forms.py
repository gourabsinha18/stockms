from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length


class LocationForm(FlaskForm):
    code = StringField("Code", validators=[DataRequired(), Length(max=10)])
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    address = StringField("Address", validators=[Length(max=255)])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")
