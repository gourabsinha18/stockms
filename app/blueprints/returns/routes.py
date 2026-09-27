from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import StockReturn, Location, Product
from app.services.permission_service import accessible_location_ids, require_location_access, can_access_location
from app.services.stock_service import create_return_request, stock_manager_review_return, admin_review_return, StockError
from app.services.notification_service import notify_main_admins, notify_location_managers, notify_user
from app.services.audit_service import log_action
from .forms import ReturnForm

bp = Blueprint("returns", __name__)


@bp.route("/")
@login_required
def list_returns():
    loc_ids = accessible_location_ids(current_user)
    query = StockReturn.query
    if loc_ids is not None:
        query = query.filter(StockReturn.source_location_id.in_(loc_ids))
    status_filter = request.args.get("status", "")
    if status_filter:
        query = query.filter(StockReturn.status == status_filter)
    returns = query.order_by(StockReturn.requested_at.desc()).all()
    return render_template("returns/list.html", returns=returns, status_filter=status_filter)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_return():
    loc_ids = accessible_location_ids(current_user)
    locations = Location.query.filter_by(is_active=True).all() if loc_ids is None else Location.query.filter(Location.id.in_(loc_ids)).all()
    all_locations = Location.query.filter_by(is_active=True).all()

    form = ReturnForm()
    form.source_location_id.choices = [(l.id, f"{l.code} - {l.name}") for l in locations]
    # Return destination is configurable rather than hard-coded, but default to Bolpur HQ if present.
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
            ret = create_return_request(
                form.source_location_id.data, form.dest_location_id.data, items,
                form.reason.data, current_user.id,
            )
            notify_location_managers(form.source_location_id.data, "New Return Request",
                                     f"{ret.return_code} awaiting your review.",
                                     link=url_for("returns.view_return", return_id=ret.id))
            db.session.commit()
            flash(f"Return request {ret.return_code} submitted.", "success")
            return redirect(url_for("returns.view_return", return_id=ret.id))
        except (StockError, ValueError) as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("returns/form.html", form=form, products=products)


@bp.route("/<int:return_id>")
@login_required
def view_return(return_id):
    ret = StockReturn.query.get_or_404(return_id)
    if not can_access_location(current_user, ret.source_location_id):
        abort(403)
    return render_template("returns/view.html", ret=ret)


@bp.route("/<int:return_id>/sm-review", methods=["POST"])
@login_required
def sm_review(return_id):
    ret = StockReturn.query.get_or_404(return_id)
    require_location_access(ret.source_location_id)
    if not (current_user.is_main_admin() or current_user.is_stock_manager()):
        abort(403)
    approve = request.form.get("decision") == "approve"
    try:
        stock_manager_review_return(return_id, current_user.id, approve=approve, comment=request.form.get("comment"))
        log_action("SM_REVIEW", "StockReturn", entity_id=ret.id, new_value=f"{ret.return_code} approve={approve}")
        if approve:
            notify_main_admins("Return Awaiting Final Approval", f"{ret.return_code} approved by Stock Manager, needs Main Admin sign-off.",
                               link=url_for("returns.view_return", return_id=ret.id))
        else:
            notify_user(ret.requested_by, "Return Rejected", f"{ret.return_code} was rejected.",
                       link=url_for("returns.view_return", return_id=ret.id))
        db.session.commit()
        flash("Return reviewed.", "success")
    except StockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("returns.view_return", return_id=return_id))


@bp.route("/<int:return_id>/admin-review", methods=["POST"])
@login_required
def admin_review(return_id):
    ret = StockReturn.query.get_or_404(return_id)
    if not current_user.is_main_admin():
        abort(403)
    approve = request.form.get("decision") == "approve"
    try:
        admin_review_return(return_id, current_user.id, approve=approve, comment=request.form.get("comment"))
        log_action("ADMIN_REVIEW", "StockReturn", entity_id=ret.id, new_value=f"{ret.return_code} approve={approve}")
        notify_user(ret.requested_by, "Return " + ("Completed" if approve else "Rejected"),
                   f"{ret.return_code} final decision recorded.", link=url_for("returns.view_return", return_id=ret.id))
        db.session.commit()
        flash("Return finalized.", "success")
    except StockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("returns.view_return", return_id=return_id))
