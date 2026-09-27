from flask import Blueprint, render_template, redirect, url_for, flash, request, Response
import csv
import io
from flask_login import login_required, current_user
from app.extensions import db
from app.models import LocationStock, Product, Location, StockMovement, ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER
from app.services.permission_service import accessible_location_ids, require_location_access, roles_required
from app.services.stock_service import receive_stock, StockError
from app.services.notification_service import notify_main_admins
from .forms import StockInHeaderForm

bp = Blueprint("stock", __name__)


@bp.route("/current")
@login_required
def current_stock():
    loc_ids = accessible_location_ids(current_user)
    location_filter = request.args.get("location_id", type=int)
    q = request.args.get("q", "").strip()

    query = db.session.query(LocationStock, Product, Location).join(
        Product, LocationStock.product_id == Product.id
    ).join(Location, LocationStock.location_id == Location.id)

    if loc_ids is not None:  # None = Main Admin (all locations)
        query = query.filter(LocationStock.location_id.in_(loc_ids))
    if location_filter:
        require_location_access(location_filter)
        query = query.filter(LocationStock.location_id == location_filter)
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%") | Product.sku.ilike(f"%{q}%"))

    rows = query.order_by(Location.name, Product.name).all()

    locations = Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids is not None else Location.query.filter_by(is_active=True).all()
    return render_template("stock/current_stock.html", rows=rows, locations=locations,
                           location_filter=location_filter, q=q)


@bp.route("/in", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def stock_in():
    form = StockInHeaderForm()
    loc_ids = accessible_location_ids(current_user)
    locations = Location.query.filter_by(is_active=True).all() if loc_ids is None else Location.query.filter(Location.id.in_(loc_ids)).all()
    form.location_id.choices = [(l.id, f"{l.code} - {l.name}") for l in locations]
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()

    if form.validate_on_submit():
        require_location_access(form.location_id.data)
        product_ids = request.form.getlist("product_id[]")
        quantities = request.form.getlist("quantity[]")
        items = []
        try:
            for pid, qty in zip(product_ids, quantities):
                if pid and qty:
                    items.append((int(pid), int(qty)))
            if not items:
                raise StockError("Add at least one product line with a quantity.")
            receipt = receive_stock(
                form.location_id.data, items, current_user.id,
                supplier_source=form.supplier_source.data,
                reference_number=form.reference_number.data,
                remarks=form.remarks.data,
            )
            notify_main_admins("Stock Received", f"{receipt.receipt_code} received at location {form.location_id.data}.",
                               link=url_for("stock.stock_history"))
            db.session.commit()
            flash(f"Stock received successfully ({receipt.receipt_code}).", "success")
            return redirect(url_for("stock.current_stock"))
        except (StockError, ValueError) as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("stock/stock_in.html", form=form, products=products)


@bp.route("/history")
@login_required
def stock_history():
    loc_ids = accessible_location_ids(current_user)
    location_filter = request.args.get("location_id", type=int)
    product_filter = request.args.get("product_id", type=int)
    movement_type = request.args.get("movement_type", "")

    query = StockMovement.query
    if loc_ids is not None:
        query = query.filter(StockMovement.location_id.in_(loc_ids))
    if location_filter:
        require_location_access(location_filter)
        query = query.filter(StockMovement.location_id == location_filter)
    if product_filter:
        query = query.filter(StockMovement.product_id == product_filter)
    if movement_type:
        query = query.filter(StockMovement.movement_type == movement_type)

    movements = query.order_by(StockMovement.created_at.desc()).limit(300).all()

    if request.args.get("export") == "csv":
        return _export_movements_csv(movements)

    locations = Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids is not None else Location.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    return render_template("stock/history.html", movements=movements, locations=locations, products=products,
                           location_filter=location_filter, product_filter=product_filter, movement_type=movement_type)


def _export_movements_csv(movements):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Product", "SKU", "Location", "Type", "Qty Before", "Change", "Qty After", "User", "Reason", "Remarks"])
    for m in movements:
        writer.writerow([
            m.created_at.strftime("%Y-%m-%d %H:%M:%S"), m.product.name, m.product.sku, m.location.name,
            m.movement_type, m.qty_before, m.qty_change, m.qty_after, m.user.full_name, m.reason or "", m.remarks or "",
        ])
    resp = Response(output.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=stock_movement_history.csv"
    return resp
