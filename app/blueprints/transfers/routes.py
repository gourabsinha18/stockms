from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import StockTransfer, Location, Product, ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER, STATUS_PENDING_APPROVAL
from app.services.permission_service import accessible_location_ids, require_location_access, can_access_location, roles_required
from app.services.stock_service import (
    create_transfer_request, approve_transfer, dispatch_transfer, receive_transfer, cancel_transfer, StockError,
)
from app.services.notification_service import notify_location_managers, notify_main_admins, notify_user
from app.services.audit_service import log_action
from .forms import TransferForm

bp = Blueprint("transfers", __name__)


@bp.route("/")
@login_required
def list_transfers():
    loc_ids = accessible_location_ids(current_user)
    query = StockTransfer.query
    if loc_ids is not None:
        query = query.filter(
            (StockTransfer.source_location_id.in_(loc_ids)) | (StockTransfer.dest_location_id.in_(loc_ids))
        )
    status_filter = request.args.get("status", "")
    if status_filter:
        query = query.filter(StockTransfer.status == status_filter)
    transfers = query.order_by(StockTransfer.requested_at.desc()).all()
    return render_template("transfers/list.html", transfers=transfers, status_filter=status_filter)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_transfer():
    loc_ids = accessible_location_ids(current_user)
    locations = Location.query.filter_by(is_active=True).all() if loc_ids is None else Location.query.filter(Location.id.in_(loc_ids)).all()
    all_locations = Location.query.filter_by(is_active=True).all()

    form = TransferForm()
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
                raise StockError("Add at least one product line with a quantity.")
            transfer = create_transfer_request(
                form.source_location_id.data, form.dest_location_id.data, items,
                current_user.id, remarks=form.remarks.data,
            )
            notify_main_admins("New Transfer Request", f"{transfer.transfer_code} awaiting approval.",
                               link=url_for("transfers.view_transfer", transfer_id=transfer.id))
            db.session.commit()
            flash(f"Transfer request {transfer.transfer_code} submitted.", "success")
            return redirect(url_for("transfers.view_transfer", transfer_id=transfer.id))
        except (StockError, ValueError) as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("transfers/form.html", form=form, products=products)


@bp.route("/<int:transfer_id>")
@login_required
def view_transfer(transfer_id):
    t = StockTransfer.query.get_or_404(transfer_id)
    if not (can_access_location(current_user, t.source_location_id) or can_access_location(current_user, t.dest_location_id)):
        abort(403)
    return render_template("transfers/view.html", t=t)


@bp.route("/<int:transfer_id>/approve", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def approve(transfer_id):
    t = StockTransfer.query.get_or_404(transfer_id)
    require_location_access(t.source_location_id)
    try:
        approve_transfer(transfer_id, current_user.id, approve=True, comment=request.form.get("comment"))
        log_action("APPROVE", "StockTransfer", entity_id=t.id, new_value=t.transfer_code)
        notify_user(t.requested_by, "Transfer Approved", f"{t.transfer_code} was approved.",
                   link=url_for("transfers.view_transfer", transfer_id=t.id))
        db.session.commit()
        flash("Transfer approved.", "success")
    except StockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("transfers.view_transfer", transfer_id=transfer_id))


@bp.route("/<int:transfer_id>/reject", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def reject(transfer_id):
    t = StockTransfer.query.get_or_404(transfer_id)
    require_location_access(t.source_location_id)
    try:
        approve_transfer(transfer_id, current_user.id, approve=False, comment=request.form.get("comment"))
        log_action("REJECT", "StockTransfer", entity_id=t.id, new_value=t.transfer_code)
        notify_user(t.requested_by, "Transfer Rejected", f"{t.transfer_code} was rejected.",
                   link=url_for("transfers.view_transfer", transfer_id=t.id))
        db.session.commit()
        flash("Transfer rejected.", "info")
    except StockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("transfers.view_transfer", transfer_id=transfer_id))


@bp.route("/<int:transfer_id>/dispatch", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def dispatch(transfer_id):
    t = StockTransfer.query.get_or_404(transfer_id)
    require_location_access(t.source_location_id)
    try:
        dispatch_transfer(transfer_id, current_user.id)
        log_action("DISPATCH", "StockTransfer", entity_id=t.id, new_value=t.transfer_code)
        notify_location_managers(t.dest_location_id, "Transfer Dispatched", f"{t.transfer_code} is on its way.",
                                 link=url_for("transfers.view_transfer", transfer_id=t.id))
        db.session.commit()
        flash("Transfer dispatched.", "success")
    except StockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("transfers.view_transfer", transfer_id=transfer_id))


@bp.route("/<int:transfer_id>/receive", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def receive(transfer_id):
    t = StockTransfer.query.get_or_404(transfer_id)
    require_location_access(t.dest_location_id)
    try:
        receive_transfer(transfer_id, current_user.id)
        log_action("RECEIVE", "StockTransfer", entity_id=t.id, new_value=t.transfer_code)
        notify_user(t.requested_by, "Transfer Completed", f"{t.transfer_code} has been received.",
                   link=url_for("transfers.view_transfer", transfer_id=t.id))
        db.session.commit()
        flash("Transfer marked as received. Stock updated.", "success")
    except StockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("transfers.view_transfer", transfer_id=transfer_id))


@bp.route("/<int:transfer_id>/cancel", methods=["POST"])
@login_required
def cancel(transfer_id):
    t = StockTransfer.query.get_or_404(transfer_id)
    if t.requested_by != current_user.id and not current_user.is_main_admin():
        abort(403)
    try:
        cancel_transfer(transfer_id, current_user.id)
        log_action("CANCEL", "StockTransfer", entity_id=t.id, new_value=t.transfer_code)
        db.session.commit()
        flash("Transfer cancelled.", "info")
    except StockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("transfers.view_transfer", transfer_id=transfer_id))
