import csv
import io
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, Response
from flask_login import login_required, current_user
from app.extensions import db
from app.models import (
    BadProductStock, BadProductMovement, BadProductRecovery, BadProductTransfer,
    Location, Product,
    ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER, ROLE_EMPLOYEE,
    BAD_RECOVERY_STATUS_PENDING, BAD_TRANSFER_STATUS_REQUESTED, BAD_TRANSFER_STATUS_APPROVED,
    BAD_TRANSFER_STATUS_DISPATCHED,
)
from app.services.permission_service import accessible_location_ids, require_location_access, can_access_location, roles_required
from app.services.bad_product_service import (
    create_recovery_request, approve_recovery,
    create_bad_transfer_request, approve_bad_transfer, dispatch_bad_transfer, receive_bad_transfer, cancel_bad_transfer,
    BadProductError,
)
from app.services.notification_service import notify_location_managers, notify_main_admins, notify_user
from app.services.audit_service import log_action
from .forms import BadProductRecoveryForm, BadProductTransferForm

bp = Blueprint("bad_products", __name__)


# ---------------------------------------------------------------------------
# BAD PRODUCT STOCK (read-only view, kept fully separate from Current Stock)
# ---------------------------------------------------------------------------

@bp.route("/stock")
@login_required
def stock():
    loc_ids = accessible_location_ids(current_user)
    location_filter = request.args.get("location_id", type=int)
    q = request.args.get("q", "").strip()

    query = db.session.query(BadProductStock, Product, Location).join(
        Product, BadProductStock.product_id == Product.id
    ).join(Location, BadProductStock.location_id == Location.id)

    if loc_ids is not None:
        query = query.filter(BadProductStock.location_id.in_(loc_ids))
    if location_filter:
        require_location_access(location_filter)
        query = query.filter(BadProductStock.location_id == location_filter)
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%") | Product.sku.ilike(f"%{q}%"))

    rows = query.order_by(Location.name, Product.name).all()
    locations = Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids is not None else Location.query.filter_by(is_active=True).all()
    return render_template("bad_products/stock.html", rows=rows, locations=locations,
                           location_filter=location_filter, q=q)


# ---------------------------------------------------------------------------
# BAD PRODUCT RECOVERIES
# ---------------------------------------------------------------------------

@bp.route("/recoveries")
@login_required
def list_recoveries():
    query = BadProductRecovery.query

    if current_user.is_employee():
        # Employees only ever see their own recovery requests.
        query = query.filter(BadProductRecovery.requested_by == current_user.id)
    else:
        loc_ids = accessible_location_ids(current_user)
        if loc_ids is not None:
            query = query.filter(BadProductRecovery.location_id.in_(loc_ids))

    recovery_code = request.args.get("recovery_code", "").strip()
    product_id = request.args.get("product_id", type=int)
    location_id = request.args.get("location_id", type=int)
    status_filter = request.args.get("status", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    if recovery_code:
        query = query.filter(BadProductRecovery.recovery_code.ilike(f"%{recovery_code}%"))
    if location_id:
        query = query.filter(BadProductRecovery.location_id == location_id)
    if status_filter:
        query = query.filter(BadProductRecovery.status == status_filter)
    if date_from:
        query = query.filter(BadProductRecovery.recovery_date >= date_from)
    if date_to:
        query = query.filter(BadProductRecovery.recovery_date <= date_to)
    if product_id:
        query = query.filter(BadProductRecovery.items.any(product_id=product_id))

    recoveries = query.order_by(BadProductRecovery.requested_at.desc()).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    locations = Location.query.filter_by(is_active=True).all()
    return render_template(
        "bad_products/recoveries_list.html", recoveries=recoveries, products=products, locations=locations,
        recovery_code=recovery_code, product_id=product_id, location_id=location_id,
        status_filter=status_filter, date_from=date_from, date_to=date_to,
    )


@bp.route("/recoveries/new", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_EMPLOYEE)
def new_recovery():
    profile = current_user.employee_profile
    if not profile:
        abort(403, description="No employee profile / assigned location found for this account.")

    form = BadProductRecoveryForm()
    form.product_id.choices = [(p.id, f"{p.sku} - {p.name}") for p in Product.query.filter_by(is_active=True).order_by(Product.name)]

    if form.validate_on_submit():
        try:
            recovery = create_recovery_request(
                profile.location_id,
                [(form.product_id.data, form.quantity.data)],
                current_user.id,
                service_reference=form.service_reference.data,
                recovery_date=form.recovery_date.data,
                remarks=form.remarks.data,
            )
            log_action("CREATE_BAD_PRODUCT_RECOVERY", "BadProductRecovery", entity_id=recovery.id, new_value=recovery.recovery_code)
            notify_location_managers(
                profile.location_id, "New Bad Product Recovery",
                f"New Bad Product Recovery {recovery.recovery_code} is pending approval.",
                link=url_for("bad_products.view_recovery", recovery_id=recovery.id),
            )
            db.session.commit()
            flash(f"Bad product recovery {recovery.recovery_code} submitted for approval.", "success")
            return redirect(url_for("bad_products.view_recovery", recovery_id=recovery.id))
        except BadProductError as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("bad_products/recovery_form.html", form=form, location=profile.location)


@bp.route("/recoveries/<int:recovery_id>")
@login_required
def view_recovery(recovery_id):
    recovery = BadProductRecovery.query.get_or_404(recovery_id)
    if current_user.is_employee():
        if recovery.requested_by != current_user.id:
            abort(403)
    elif not can_access_location(current_user, recovery.location_id):
        abort(403)
    return render_template("bad_products/recovery_view.html", recovery=recovery)


@bp.route("/recoveries/<int:recovery_id>/approve", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def approve_recovery_route(recovery_id):
    recovery = BadProductRecovery.query.get_or_404(recovery_id)
    require_location_access(recovery.location_id)
    try:
        approve_recovery(recovery_id, current_user.id, approve=True, comment=request.form.get("comment"))
        log_action("APPROVE_BAD_PRODUCT_RECOVERY", "BadProductRecovery", entity_id=recovery.id, new_value=recovery.recovery_code)
        notify_user(recovery.requested_by, "Bad Product Recovery Approved",
                   f"{recovery.recovery_code} was approved. Bad product stock updated.",
                   link=url_for("bad_products.view_recovery", recovery_id=recovery.id))
        db.session.commit()
        flash("Recovery approved. Bad product stock updated.", "success")
    except BadProductError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("bad_products.view_recovery", recovery_id=recovery_id))


@bp.route("/recoveries/<int:recovery_id>/reject", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def reject_recovery_route(recovery_id):
    recovery = BadProductRecovery.query.get_or_404(recovery_id)
    require_location_access(recovery.location_id)
    try:
        approve_recovery(recovery_id, current_user.id, approve=False, comment=request.form.get("comment"))
        log_action("REJECT_BAD_PRODUCT_RECOVERY", "BadProductRecovery", entity_id=recovery.id, new_value=recovery.recovery_code)
        notify_user(recovery.requested_by, "Bad Product Recovery Rejected",
                   f"{recovery.recovery_code} was rejected.",
                   link=url_for("bad_products.view_recovery", recovery_id=recovery.id))
        db.session.commit()
        flash("Recovery rejected.", "info")
    except BadProductError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("bad_products.view_recovery", recovery_id=recovery_id))


# ---------------------------------------------------------------------------
# BAD PRODUCT TRANSFERS
# ---------------------------------------------------------------------------

@bp.route("/transfers")
@login_required
def list_transfers():
    loc_ids = accessible_location_ids(current_user)
    query = BadProductTransfer.query
    if loc_ids is not None:
        query = query.filter(
            (BadProductTransfer.source_location_id.in_(loc_ids)) | (BadProductTransfer.dest_location_id.in_(loc_ids))
        )
    status_filter = request.args.get("status", "")
    if status_filter:
        query = query.filter(BadProductTransfer.status == status_filter)
    transfers = query.order_by(BadProductTransfer.requested_at.desc()).all()
    return render_template("bad_products/transfers_list.html", transfers=transfers, status_filter=status_filter)


@bp.route("/transfers/new", methods=["GET", "POST"])
@login_required
def new_transfer():
    """Fix 7 permission policy: creation is open to any authenticated user with access to the
    source location (Main Admin, Stock Manager, or Employee for their own assigned location) -
    this deliberately MIRRORS the existing normal Stock Transfer policy (app/blueprints/transfers
    /routes.py new_transfer, which also has no @roles_required and relies on
    accessible_location_ids/require_location_access). `requested_by` is always current_user.id,
    never taken from the client. Source/destination validity, difference, and sufficient
    BadProductStock are all re-validated server-side inside bad_product_service, independent of
    whatever the HTML <select> happened to submit."""
    loc_ids = accessible_location_ids(current_user)
    locations = Location.query.filter_by(is_active=True).all() if loc_ids is None else Location.query.filter(Location.id.in_(loc_ids)).all()
    all_locations = Location.query.filter_by(is_active=True).all()

    form = BadProductTransferForm()
    form.source_location_id.choices = [(l.id, f"{l.code} - {l.name}") for l in locations]
    form.dest_location_id.choices = [(l.id, f"{l.code} - {l.name}") for l in all_locations]
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()

    if form.validate_on_submit():
        require_location_access(form.source_location_id.data)
        product_ids = request.form.getlist("product_id[]")
        quantities = request.form.getlist("quantity[]")
        items = []
        try:
            for pid, qty in zip(product_ids, quantities):
                if pid and qty:
                    items.append((int(pid), int(qty)))
            if not items:
                raise BadProductError("Add at least one product line with a quantity.")
            transfer = create_bad_transfer_request(
                form.source_location_id.data, form.dest_location_id.data, items,
                current_user.id, remarks=form.remarks.data,
            )
            log_action("CREATE_BAD_PRODUCT_TRANSFER", "BadProductTransfer", entity_id=transfer.id, new_value=transfer.transfer_code)
            notify_location_managers(form.source_location_id.data, "New Bad Product Transfer Request",
                               f"{transfer.transfer_code} awaiting approval.",
                               link=url_for("bad_products.view_transfer", transfer_id=transfer.id))
            notify_main_admins("New Bad Product Transfer Request", f"{transfer.transfer_code} awaiting approval.",
                               link=url_for("bad_products.view_transfer", transfer_id=transfer.id))
            db.session.commit()
            flash(f"Bad product transfer request {transfer.transfer_code} submitted.", "success")
            return redirect(url_for("bad_products.view_transfer", transfer_id=transfer.id))
        except (BadProductError, ValueError) as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("bad_products/transfer_form.html", form=form, products=products)


@bp.route("/transfers/<int:transfer_id>")
@login_required
def view_transfer(transfer_id):
    t = BadProductTransfer.query.get_or_404(transfer_id)
    if not (can_access_location(current_user, t.source_location_id) or can_access_location(current_user, t.dest_location_id)):
        abort(403)
    return render_template("bad_products/transfer_view.html", t=t)


@bp.route("/transfers/<int:transfer_id>/approve", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def approve_transfer_route(transfer_id):
    t = BadProductTransfer.query.get_or_404(transfer_id)
    require_location_access(t.source_location_id)
    try:
        approve_bad_transfer(transfer_id, current_user.id, approve=True, comment=request.form.get("comment"))
        log_action("APPROVE_BAD_PRODUCT_TRANSFER", "BadProductTransfer", entity_id=t.id, new_value=t.transfer_code)
        notify_user(t.requested_by, "Bad Product Transfer Approved", f"{t.transfer_code} was approved.",
                   link=url_for("bad_products.view_transfer", transfer_id=t.id))
        db.session.commit()
        flash("Bad product transfer approved.", "success")
    except BadProductError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("bad_products.view_transfer", transfer_id=transfer_id))


@bp.route("/transfers/<int:transfer_id>/reject", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def reject_transfer_route(transfer_id):
    t = BadProductTransfer.query.get_or_404(transfer_id)
    require_location_access(t.source_location_id)
    try:
        approve_bad_transfer(transfer_id, current_user.id, approve=False, comment=request.form.get("comment"))
        log_action("REJECT_BAD_PRODUCT_TRANSFER", "BadProductTransfer", entity_id=t.id, new_value=t.transfer_code)
        notify_user(t.requested_by, "Bad Product Transfer Rejected", f"{t.transfer_code} was rejected.",
                   link=url_for("bad_products.view_transfer", transfer_id=t.id))
        db.session.commit()
        flash("Bad product transfer rejected.", "info")
    except BadProductError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("bad_products.view_transfer", transfer_id=transfer_id))


@bp.route("/transfers/<int:transfer_id>/dispatch", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def dispatch_transfer_route(transfer_id):
    t = BadProductTransfer.query.get_or_404(transfer_id)
    require_location_access(t.source_location_id)
    try:
        dispatch_bad_transfer(transfer_id, current_user.id)
        log_action("DISPATCH_BAD_PRODUCT_TRANSFER", "BadProductTransfer", entity_id=t.id, new_value=t.transfer_code)
        notify_location_managers(t.dest_location_id, "Bad Product Transfer Dispatched",
                                 f"{t.transfer_code} is on its way.",
                                 link=url_for("bad_products.view_transfer", transfer_id=t.id))
        db.session.commit()
        flash("Bad product transfer dispatched.", "success")
    except BadProductError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("bad_products.view_transfer", transfer_id=transfer_id))


@bp.route("/transfers/<int:transfer_id>/receive", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def receive_transfer_route(transfer_id):
    t = BadProductTransfer.query.get_or_404(transfer_id)
    require_location_access(t.dest_location_id)
    try:
        receive_bad_transfer(transfer_id, current_user.id)
        log_action("RECEIVE_BAD_PRODUCT_TRANSFER", "BadProductTransfer", entity_id=t.id, new_value=t.transfer_code)
        notify_user(t.requested_by, "Bad Product Transfer Completed", f"{t.transfer_code} has been received.",
                   link=url_for("bad_products.view_transfer", transfer_id=t.id))
        db.session.commit()
        flash("Bad product transfer received. Bad product stock updated.", "success")
    except BadProductError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("bad_products.view_transfer", transfer_id=transfer_id))


@bp.route("/transfers/<int:transfer_id>/cancel", methods=["POST"])
@login_required
def cancel_transfer_route(transfer_id):
    t = BadProductTransfer.query.get_or_404(transfer_id)
    if t.requested_by != current_user.id and not current_user.is_main_admin():
        abort(403)
    try:
        cancel_bad_transfer(transfer_id, current_user.id)
        log_action("CANCEL_BAD_PRODUCT_TRANSFER", "BadProductTransfer", entity_id=t.id, new_value=t.transfer_code)
        db.session.commit()
        flash("Bad product transfer cancelled.", "info")
    except BadProductError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("bad_products.view_transfer", transfer_id=transfer_id))


# ---------------------------------------------------------------------------
# BAD PRODUCT HISTORY (ledger - never mixed with normal Stock History)
# ---------------------------------------------------------------------------

@bp.route("/history")
@login_required
def history():
    loc_ids = accessible_location_ids(current_user)
    location_filter = request.args.get("location_id", type=int)
    product_filter = request.args.get("product_id", type=int)
    movement_type = request.args.get("movement_type", "")

    query = BadProductMovement.query
    if loc_ids is not None:
        query = query.filter(BadProductMovement.location_id.in_(loc_ids))
    if location_filter:
        require_location_access(location_filter)
        query = query.filter(BadProductMovement.location_id == location_filter)
    if product_filter:
        query = query.filter(BadProductMovement.product_id == product_filter)
    if movement_type:
        query = query.filter(BadProductMovement.movement_type == movement_type)

    movements = query.order_by(BadProductMovement.created_at.desc()).limit(300).all()

    if request.args.get("export") == "csv":
        return _export_movements_csv(movements)

    locations = Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids is not None else Location.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    return render_template("bad_products/history.html", movements=movements, locations=locations, products=products,
                           location_filter=location_filter, product_filter=product_filter, movement_type=movement_type)


def _export_movements_csv(movements):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Product", "SKU", "Location", "Type", "Qty Before", "Change", "Qty After", "User", "Remarks"])
    for m in movements:
        writer.writerow([
            m.created_at.strftime("%Y-%m-%d %H:%M:%S"), m.product.name, m.product.sku, m.location.name,
            m.movement_type, m.quantity_before, m.quantity_change, m.quantity_after, m.user.full_name, m.remarks or "",
        ])
    resp = Response(output.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=bad_product_history.csv"
    return resp
