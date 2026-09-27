from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SelectMultipleField, BooleanField, SubmitField, DateField
from wtforms.validators import DataRequired, Length, Email, Optional, Regexp


class NewStockManagerForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(max=64)])
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("Initial Password", validators=[DataRequired(), Length(min=8)])
    location_ids = SelectMultipleField("Authorized Locations", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Create Stock Manager")


class NewEmployeeForm(FlaskForm):
    employee_code = StringField("Employee ID", validators=[Optional(), Length(max=20)])
    username = StringField("Username", validators=[DataRequired(), Length(max=64)])
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    phone = StringField("Phone", validators=[Optional(), Length(max=20), Regexp(r"^[0-9+\-() ]*$", message="Invalid phone number.")])
    designation = StringField("Designation", validators=[Optional(), Length(max=100)])
    department = StringField("Department", validators=[Optional(), Length(max=100)])
    password = PasswordField("Initial Password", validators=[DataRequired(), Length(min=8)])
    location_id = SelectField("Location", coerce=int, validators=[DataRequired()])
    stock_manager_id = SelectField("Supervising Stock Manager", coerce=int, validators=[Optional()])
    submit = SubmitField("Create Employee")


class EditEmployeeForm(FlaskForm):
    employee_code = StringField("Employee ID", validators=[DataRequired(), Length(max=20)])
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    phone = StringField("Phone", validators=[Optional(), Length(max=20), Regexp(r"^[0-9+\-() ]*$", message="Invalid phone number.")])
    designation = StringField("Designation", validators=[Optional(), Length(max=100)])
    department = StringField("Department", validators=[Optional(), Length(max=100)])
    location_id = SelectField("Location", coerce=int, validators=[DataRequired()])
    stock_manager_id = SelectField("Supervising Stock Manager", coerce=int, validators=[Optional()])
    is_active = BooleanField("Active")
    submit = SubmitField("Save Changes")


class ToggleActiveForm(FlaskForm):
    submit = SubmitField("Toggle Active")
