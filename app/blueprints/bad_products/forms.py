from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, StringField, TextAreaField, DateField, SubmitField
from wtforms.validators import DataRequired, Optional, Length, NumberRange
from datetime import date


class BadProductRecoveryForm(FlaskForm):
    """Deliberately simple - no Condition / Repair Status / Customer fields."""
    product_id = SelectField("Product", coerce=int, validators=[DataRequired()])
    quantity = IntegerField("Quantity", validators=[DataRequired(), NumberRange(min=1)])
    service_reference = StringField("Service / Job Reference", validators=[DataRequired(), Length(max=120)])
    recovery_date = DateField("Recovery Date", default=date.today, validators=[DataRequired()])
    remarks = TextAreaField("Remarks", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Submit Recovery")


class BadProductTransferForm(FlaskForm):
    source_location_id = SelectField("Source Location", coerce=int, validators=[DataRequired()])
    dest_location_id = SelectField("Destination Location", coerce=int, validators=[DataRequired()])
    remarks = StringField("Remarks", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Submit Bad Product Transfer Request")
