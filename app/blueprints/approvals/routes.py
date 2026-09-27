from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.models import (
    StockTransfer, StockAdjustment, StockReturn,
    BadProductTransfer,
    STATUS_PENDING_APPROVAL, STATUS_PROCESSING, ROLE_EMPLOYEE,
    BAD_TRANSFER_STATUS_REQUESTED,
)
from app.services.permission_service import accessible_location_ids

bp = Blueprint("approvals", __name__)


@bp.route("/")
@login_required
def pending():
    loc_ids = accessible_location_ids(current_user)

    if current_user.role == ROLE_EMPLOYEE:
        # Employees have nothing to approve; show their own pending requests instead.
        transfers = StockTransfer.query.filter_by(requested_by=current_user.id).filter(
            StockTransfer.status == STATUS_PENDING_APPROVAL
        ).all()
        adjustments = StockAdjustment.query.filter_by(requested_by=current_user.id).filter(
            StockAdjustment.status == STATUS_PENDING_APPROVAL
        ).all()
        returns = StockReturn.query.filter_by(requested_by=current_user.id).filter(
            StockReturn.status.in_([STATUS_PENDING_APPROVAL, STATUS_PROCESSING])
        ).all()
        bad_transfers = BadProductTransfer.query.filter_by(requested_by=current_user.id).filter(
            BadProductTransfer.status == BAD_TRANSFER_STATUS_REQUESTED
        ).all()
        return render_template("approvals/pending.html", transfers=transfers, adjustments=adjustments,
                               returns=returns, bad_transfers=bad_transfers, is_employee_view=True)

    t_query = StockTransfer.query.filter_by(status=STATUS_PENDING_APPROVAL)
    a_query = StockAdjustment.query.filter_by(status=STATUS_PENDING_APPROVAL)
    bt_query = BadProductTransfer.query.filter_by(status=BAD_TRANSFER_STATUS_REQUESTED)

    if current_user.is_main_admin():
        r_query = StockReturn.query.filter_by(status=STATUS_PROCESSING)  # awaiting Main Admin
    else:
        r_query = StockReturn.query.filter_by(status=STATUS_PENDING_APPROVAL)  # awaiting Stock Manager

    if loc_ids is not None:
        t_query = t_query.filter(StockTransfer.source_location_id.in_(loc_ids))
        a_query = a_query.filter(StockAdjustment.location_id.in_(loc_ids))
        r_query = r_query.filter(StockReturn.source_location_id.in_(loc_ids))
        # A Bad Product Transfer is actionable by anyone with access to its source location
        # (the location whose approval/authorization it awaits), mirroring normal StockTransfer.
        bt_query = bt_query.filter(BadProductTransfer.source_location_id.in_(loc_ids))

    transfers = t_query.order_by(StockTransfer.requested_at.desc()).all()
    adjustments = a_query.order_by(StockAdjustment.requested_at.desc()).all()
    returns = r_query.order_by(StockReturn.requested_at.desc()).all()
    bad_transfers = bt_query.order_by(BadProductTransfer.requested_at.desc()).all()

    return render_template("approvals/pending.html", transfers=transfers, adjustments=adjustments,
                           returns=returns, bad_transfers=bad_transfers, is_employee_view=False)
