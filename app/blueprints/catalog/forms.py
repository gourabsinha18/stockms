from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SubmitField, SelectField, IntegerField, DecimalField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, NumberRange


class UnitForm(FlaskForm):
    code = StringField("Code", validators=[DataRequired(), Length(max=20)])
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    description = StringField("Description", validators=[Length(max=255)])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")


class BrandForm(FlaskForm):
    unit_id = SelectField("Unit", coerce=int, validators=[DataRequired()])
    code = StringField("Code", validators=[DataRequired(), Length(max=20)])
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    description = StringField("Description", validators=[Length(max=255)])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")


class CategoryForm(FlaskForm):
    brand_id = SelectField("Company / Brand", coerce=int, validators=[DataRequired()])
    code = StringField("Code", validators=[DataRequired(), Length(max=20)])
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    description = StringField("Description", validators=[Length(max=255)])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")


class ProductForm(FlaskForm):
    sku = StringField("SKU / Product Code", validators=[DataRequired(), Length(max=40)])
    name = StringField("Product Name", validators=[DataRequired(), Length(max=150)])
    category_id = SelectField("Category", coerce=int, validators=[DataRequired()])
    model = StringField("Model", validators=[Optional(), Length(max=80)])
    description = TextAreaField("Description", validators=[Optional()])
    min_stock_level = IntegerField("Minimum Stock Level", validators=[NumberRange(min=0)], default=0)
    reorder_level = IntegerField("Reorder Level", validators=[NumberRange(min=0)], default=0)
    cost_price = DecimalField("Cost Price", validators=[Optional()], places=2)
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")
