from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from app.extensions import db
from app.models import Unit, Brand, Category, Product
from app.services.audit_service import log_action
from app.services.permission_service import admin_required
from .forms import UnitForm, BrandForm, CategoryForm, ProductForm

bp = Blueprint("catalog", __name__)


# ---------------- Units ----------------

@bp.route("/units")
@login_required
@admin_required
def list_units():
    units = Unit.query.order_by(Unit.name).all()
    return render_template("catalog/units_list.html", units=units)


@bp.route("/units/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_unit():
    form = UnitForm()
    if form.validate_on_submit():
        if Unit.query.filter_by(code=form.code.data.upper()).first():
            flash("A unit with this code already exists.", "danger")
        else:
            u = Unit(code=form.code.data.upper(), name=form.name.data,
                      description=form.description.data, is_active=form.is_active.data)
            db.session.add(u)
            db.session.flush()
            log_action("CREATE", "Unit", entity_id=u.id, new_value=u.name)
            db.session.commit()
            flash("Unit created.", "success")
            return redirect(url_for("catalog.list_units"))
    return render_template("catalog/entity_form.html", form=form, title="New Unit", cancel_url=url_for("catalog.list_units"))


@bp.route("/units/<int:unit_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_unit(unit_id):
    u = Unit.query.get_or_404(unit_id)
    form = UnitForm(obj=u)
    if form.validate_on_submit():
        prev = f"{u.code} {u.name} active={u.is_active}"
        u.code, u.name, u.description, u.is_active = form.code.data.upper(), form.name.data, form.description.data, form.is_active.data
        log_action("UPDATE", "Unit", entity_id=u.id, previous_value=prev, new_value=f"{u.code} {u.name} active={u.is_active}")
        db.session.commit()
        flash("Unit updated.", "success")
        return redirect(url_for("catalog.list_units"))
    return render_template("catalog/entity_form.html", form=form, title="Edit Unit", cancel_url=url_for("catalog.list_units"))


# ---------------- Brands ----------------

@bp.route("/brands")
@login_required
@admin_required
def list_brands():
    brands = Brand.query.join(Unit).order_by(Unit.name, Brand.name).all()
    return render_template("catalog/brands_list.html", brands=brands)


@bp.route("/brands/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_brand():
    form = BrandForm()
    form.unit_id.choices = [(u.id, u.name) for u in Unit.query.filter_by(is_active=True).order_by(Unit.name)]
    if form.validate_on_submit():
        b = Brand(unit_id=form.unit_id.data, code=form.code.data.upper(), name=form.name.data,
                   description=form.description.data, is_active=form.is_active.data)
        db.session.add(b)
        db.session.flush()
        log_action("CREATE", "Brand", entity_id=b.id, new_value=b.name)
        db.session.commit()
        flash("Company/Brand created.", "success")
        return redirect(url_for("catalog.list_brands"))
    return render_template("catalog/entity_form.html", form=form, title="New Company / Brand", cancel_url=url_for("catalog.list_brands"))


@bp.route("/brands/<int:brand_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_brand(brand_id):
    b = Brand.query.get_or_404(brand_id)
    form = BrandForm(obj=b)
    form.unit_id.choices = [(u.id, u.name) for u in Unit.query.filter_by(is_active=True).order_by(Unit.name)]
    if form.validate_on_submit():
        prev = f"{b.code} {b.name}"
        b.unit_id, b.code, b.name = form.unit_id.data, form.code.data.upper(), form.name.data
        b.description, b.is_active = form.description.data, form.is_active.data
        log_action("UPDATE", "Brand", entity_id=b.id, previous_value=prev, new_value=f"{b.code} {b.name}")
        db.session.commit()
        flash("Company/Brand updated.", "success")
        return redirect(url_for("catalog.list_brands"))
    return render_template("catalog/entity_form.html", form=form, title="Edit Company / Brand", cancel_url=url_for("catalog.list_brands"))


# ---------------- Categories ----------------

@bp.route("/categories")
@login_required
@admin_required
def list_categories():
    categories = Category.query.join(Brand).order_by(Brand.name, Category.name).all()
    return render_template("catalog/categories_list.html", categories=categories)


@bp.route("/categories/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_category():
    form = CategoryForm()
    form.brand_id.choices = [(b.id, f"{b.unit.name} / {b.name}") for b in Brand.query.filter_by(is_active=True).join(Unit).order_by(Unit.name, Brand.name)]
    if form.validate_on_submit():
        c = Category(brand_id=form.brand_id.data, code=form.code.data.upper(), name=form.name.data,
                      description=form.description.data, is_active=form.is_active.data)
        db.session.add(c)
        db.session.flush()
        log_action("CREATE", "Category", entity_id=c.id, new_value=c.name)
        db.session.commit()
        flash("Category created.", "success")
        return redirect(url_for("catalog.list_categories"))
    return render_template("catalog/entity_form.html", form=form, title="New Category", cancel_url=url_for("catalog.list_categories"))


@bp.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_category(category_id):
    c = Category.query.get_or_404(category_id)
    form = CategoryForm(obj=c)
    form.brand_id.choices = [(b.id, f"{b.unit.name} / {b.name}") for b in Brand.query.filter_by(is_active=True).join(Unit).order_by(Unit.name, Brand.name)]
    if form.validate_on_submit():
        prev = f"{c.code} {c.name}"
        c.brand_id, c.code, c.name = form.brand_id.data, form.code.data.upper(), form.name.data
        c.description, c.is_active = form.description.data, form.is_active.data
        log_action("UPDATE", "Category", entity_id=c.id, previous_value=prev, new_value=f"{c.code} {c.name}")
        db.session.commit()
        flash("Category updated.", "success")
        return redirect(url_for("catalog.list_categories"))
    return render_template("catalog/entity_form.html", form=form, title="Edit Category", cancel_url=url_for("catalog.list_categories"))


# ---------------- Products ----------------

@bp.route("/products")
@login_required
def list_products():
    q = request.args.get("q", "").strip()
    query = Product.query.join(Category).join(Brand).join(Unit)
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%") | Product.sku.ilike(f"%{q}%"))
    products = query.order_by(Product.name).all()
    return render_template("catalog/products_list.html", products=products, q=q)


@bp.route("/products/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_product():
    form = ProductForm()
    form.category_id.choices = [
        (c.id, f"{c.brand.unit.name} / {c.brand.name} / {c.name}")
        for c in Category.query.filter_by(is_active=True).join(Brand).join(Unit).order_by(Unit.name, Brand.name, Category.name)
    ]
    if form.validate_on_submit():
        if Product.query.filter_by(sku=form.sku.data).first():
            flash("A product with this SKU already exists.", "danger")
        else:
            p = Product(sku=form.sku.data, name=form.name.data, category_id=form.category_id.data,
                        model=form.model.data, description=form.description.data,
                        min_stock_level=form.min_stock_level.data, reorder_level=form.reorder_level.data,
                        cost_price=form.cost_price.data, is_active=form.is_active.data)
            db.session.add(p)
            db.session.flush()
            log_action("CREATE", "Product", entity_id=p.id, new_value=f"{p.sku} {p.name}")
            db.session.commit()
            flash("Product created.", "success")
            return redirect(url_for("catalog.list_products"))
    return render_template("catalog/entity_form.html", form=form, title="New Product", cancel_url=url_for("catalog.list_products"))


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_product(product_id):
    p = Product.query.get_or_404(product_id)
    form = ProductForm(obj=p)
    form.category_id.choices = [
        (c.id, f"{c.brand.unit.name} / {c.brand.name} / {c.name}")
        for c in Category.query.filter_by(is_active=True).join(Brand).join(Unit).order_by(Unit.name, Brand.name, Category.name)
    ]
    if form.validate_on_submit():
        prev = f"{p.sku} {p.name} min={p.min_stock_level} reorder={p.reorder_level}"
        p.sku, p.name, p.category_id = form.sku.data, form.name.data, form.category_id.data
        p.model, p.description = form.model.data, form.description.data
        p.min_stock_level, p.reorder_level = form.min_stock_level.data, form.reorder_level.data
        p.cost_price, p.is_active = form.cost_price.data, form.is_active.data
        log_action("UPDATE", "Product", entity_id=p.id, previous_value=prev,
                   new_value=f"{p.sku} {p.name} min={p.min_stock_level} reorder={p.reorder_level}")
        db.session.commit()
        flash("Product updated.", "success")
        return redirect(url_for("catalog.list_products"))
    return render_template("catalog/entity_form.html", form=form, title="Edit Product", cancel_url=url_for("catalog.list_products"))
