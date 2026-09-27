from flask import Blueprint, render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Location, Employee, LocationStock, Product
from app.services.audit_service import log_action
from app.services.permission_service import admin_required, can_access_location
from .forms import LocationForm

bp = Blueprint("locations", __name__)


@bp.route("/")
@login_required
def list_locations():
    if current_user.is_main_admin():
        locations = Location.query.order_by(Location.name).all()
    else:
        from app.services.permission_service import accessible_location_ids
        ids = accessible_location_ids(current_user) or []
        locations = Location.query.filter(Location.id.in_(ids)).order_by(Location.name).all()
    return render_template("locations/list.html", locations=locations)


@bp.route("/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_location():
    form = LocationForm()
    if form.validate_on_submit():
        if Location.query.filter_by(code=form.code.data.upper()).first():
            flash("A location with this code already exists.", "danger")
            return render_template("locations/form.html", form=form, title="New Location")
        loc = Location(code=form.code.data.upper(), name=form.name.data, address=form.address.data,
                        is_active=form.is_active.data)
        db.session.add(loc)
        db.session.flush()
        log_action("CREATE", "Location", entity_id=loc.id, new_value=f"{loc.code} {loc.name}")
        db.session.commit()
        flash("Location created.", "success")
        return redirect(url_for("locations.list_locations"))
    return render_template("locations/form.html", form=form, title="New Location")


@bp.route("/<int:location_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_location(location_id):
    loc = Location.query.get_or_404(location_id)
    form = LocationForm(obj=loc)
    if form.validate_on_submit():
        prev = f"{loc.code} {loc.name} active={loc.is_active}"
        loc.code = form.code.data.upper()
        loc.name = form.name.data
        loc.address = form.address.data
        loc.is_active = form.is_active.data
        log_action("UPDATE", "Location", entity_id=loc.id, previous_value=prev,
                   new_value=f"{loc.code} {loc.name} active={loc.is_active}")
        db.session.commit()
        flash("Location updated.", "success")
        return redirect(url_for("locations.list_locations"))
    return render_template("locations/form.html", form=form, title="Edit Location")


@bp.route("/<int:location_id>")
@login_required
def view_location(location_id):
    if not can_access_location(current_user, location_id):
        abort(403)
    loc = Location.query.get_or_404(location_id)
    employees = Employee.query.filter_by(location_id=location_id, is_active=True).all()
    stock = (
        db.session.query(LocationStock, Product)
        .join(Product, LocationStock.product_id == Product.id)
        .filter(LocationStock.location_id == location_id).all()
    )
    return render_template("locations/view.html", location=loc, employees=employees, stock=stock)
