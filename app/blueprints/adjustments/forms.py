from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Optional, Length


class AdjustmentForm(FlaskForm):
    location_id = SelectField("Location", coerce=int, validators=[DataRequired()])
    product_id = SelectField("Product", coerce=int, validators=[DataRequired()])
    adjustment_qty = IntegerField("Adjustment Quantity (use negative for decrease)", validators=[DataRequired()])
    reason = SelectField("Reason", choices=[
        ("Physical stock mismatch", "Physical stock mismatch"),
        ("Damaged stock", "Damaged stock"),
        ("Missing stock", "Missing stock"),
        ("Counting error", "Counting error"),
        ("Data correction", "Data correction"),
        ("Other", "Other"),
    ], validators=[DataRequired()])
    remarks = TextAreaField("Remarks", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Submit Adjustment Request")
