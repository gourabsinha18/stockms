from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import StockAdjustment, Location, Product, STATUS_PENDING_APPROVAL
from app.services.permission_service import accessible_location_ids, require_location_access, can_access_location
from app.services.stock_service import create_adjustment_request, approve_adjustment, StockError
from app.services.notification_service import notify_main_admins, notify_location_managers, notify_user
from app.services.audit_service import log_action
from .forms import AdjustmentForm

bp = Blueprint("adjustments", __name__)


@bp.route("/")
@login_required
def list_adjustments():
    loc_ids = accessible_location_ids(current_user)
    query = StockAdjustment.query
    if loc_ids is not None:
        query = query.filter(StockAdjustment.location_id.in_(loc_ids))
    status_filter = request.args.get("status", "")
    if status_filter:
        query = query.filter(StockAdjustment.status == status_filter)
    adjustments = query.order_by(StockAdjustment.requested_at.desc()).all()
    return render_template("adjustments/list.html", adjustments=adjustments, status_filter=status_filter)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_adjustment():
    loc_ids = accessible_location_ids(current_user)
    locations = Location.query.filter_by(is_active=True).all() if loc_ids is None else Location.query.filter(Location.id.in_(loc_ids)).all()
    form = AdjustmentForm()
    form.location_id.choices = [(l.id, f"{l.code} - {l.name}") for l in locations]
    form.product_id.choices = [(p.id, f"{p.sku} - {p.name}") for p in Product.query.filter_by(is_active=True).order_by(Product.name)]

    if form.validate_on_submit():
        require_location_access(form.location_id.data)
        try:
            adj = create_adjustment_request(
                form.location_id.data, form.product_id.data, form.adjustment_qty.data,
                form.reason.data, current_user.id, remarks=form.remarks.data,
            )
            notify_main_admins("New Adjustment Request", f"{adj.adjustment_code} awaiting approval.",
                               link=url_for("adjustments.view_adjustment", adjustment_id=adj.id))
            db.session.commit()
            flash(f"Adjustment request {adj.adjustment_code} submitted for approval.", "success")
            return redirect(url_for("adjustments.view_adjustment", adjustment_id=adj.id))
        except StockError as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("adjustments/form.html", form=form)


@bp.route("/<int:adjustment_id>")
@login_required
def view_adjustment(adjustment_id):
    adj = StockAdjustment.query.get_or_404(adjustment_id)
    if not can_access_location(current_user, adj.location_id):
        abort(403)
    return render_template("adjustments/view.html", adj=adj)


@bp.route("/<int:adjustment_id>/approve", methods=["POST"])
@login_required
def approve(adjustment_id):
    adj = StockAdjustment.query.get_or_404(adjustment_id)
    require_location_access(adj.location_id)
    if not (current_user.is_main_admin() or current_user.is_stock_manager()):
        abort(403)
    try:
        approve_adjustment(adjustment_id, current_user.id, approve=True, comment=request.form.get("comment"))
        log_action("APPROVE", "StockAdjustment", entity_id=adj.id, new_value=adj.adjustment_code)
        notify_user(adj.requested_by, "Adjustment Approved", f"{adj.adjustment_code} was approved.",
                   link=url_for("adjustments.view_adjustment", adjustment_id=adj.id))
        db.session.commit()
        flash("Adjustment approved and stock updated.", "success")
    except StockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("adjustments.view_adjustment", adjustment_id=adjustment_id))


@bp.route("/<int:adjustment_id>/reject", methods=["POST"])
@login_required
def reject(adjustment_id):
    adj = StockAdjustment.query.get_or_404(adjustment_id)
    require_location_access(adj.location_id)
    if not (current_user.is_main_admin() or current_user.is_stock_manager()):
        abort(403)
    try:
        approve_adjustment(adjustment_id, current_user.id, approve=False, comment=request.form.get("comment"))
        log_action("REJECT", "StockAdjustment", entity_id=adj.id, new_value=adj.adjustment_code)
        notify_user(adj.requested_by, "Adjustment Rejected", f"{adj.adjustment_code} was rejected.",
                   link=url_for("adjustments.view_adjustment", adjustment_id=adj.id))
        db.session.commit()
        flash("Adjustment rejected.", "info")
    except StockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("adjustments.view_adjustment", adjustment_id=adjustment_id))
