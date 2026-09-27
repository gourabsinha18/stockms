from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Optional, Length, NumberRange


class IssueStockForm(FlaskForm):
    employee_id = SelectField("Employee", coerce=int, validators=[DataRequired()])
    product_id = SelectField("Product", coerce=int, validators=[DataRequired()])
    quantity = IntegerField("Quantity", validators=[DataRequired(), NumberRange(min=1)])
    reason = StringField("Reason", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Issue Stock")


class ReturnRequestForm(FlaskForm):
    product_id = SelectField("Product", coerce=int, validators=[DataRequired()])
    quantity = IntegerField("Return Quantity", validators=[DataRequired(), NumberRange(min=1)])
    reported_condition = SelectField("Reported Condition", choices=[("GOOD", "Good / Original"), ("BAD", "Bad / Damaged")],
                                     validators=[DataRequired()])
    reason = TextAreaField("Reason", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Submit Return Request")


class ReviewReturnForm(FlaskForm):
    remarks = TextAreaField("Manager Remarks", validators=[Optional(), Length(max=255)])
