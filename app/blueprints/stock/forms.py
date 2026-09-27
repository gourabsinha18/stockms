from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional


class StockInHeaderForm(FlaskForm):
    """CSRF-protected header form; product/quantity line items are posted as parallel arrays via JS."""
    location_id = SelectField("Location", coerce=int, validators=[DataRequired()])
    supplier_source = StringField("Supplier / Source", validators=[Optional(), Length(max=150)])
    reference_number = StringField("Reference Number", validators=[Optional(), Length(max=80)])
    remarks = StringField("Remarks", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Receive Stock")
