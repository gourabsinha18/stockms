"""
Centralized stock mutation service.

RULE: No other part of the application may write to LocationStock.quantity
directly. Every change MUST go through _apply_movement() so that:
  1. Stock never goes negative.
  2. A StockMovement ledger row is always created.
  3. The change happens inside a single DB transaction (atomic).
"""
from datetime import datetime
from app.extensions import db
from app.models import (
    LocationStock, StockMovement, Product, Location,
    StockReceipt, StockReceiptItem,
    StockTransfer, StockTransferItem,
    StockAdjustment,
    StockReturn, StockReturnItem,
    ApprovalLog,
    STATUS_DRAFT, STATUS_PENDING_APPROVAL, STATUS_APPROVED, STATUS_REJECTED,
    STATUS_PROCESSING, STATUS_COMPLETED, STATUS_CANCELLED,
    MOVEMENT_STOCK_IN, MOVEMENT_TRANSFER_OUT, MOVEMENT_TRANSFER_IN,
    MOVEMENT_ADJUSTMENT_IN, MOVEMENT_ADJUSTMENT_OUT,
    MOVEMENT_RETURN_OUT, MOVEMENT_RETURN_IN,
    REQUEST_TYPE_TRANSFER, REQUEST_TYPE_ADJUSTMENT, REQUEST_TYPE_RETURN, REQUEST_TYPE_STOCK_IN,
    gen_code,
)


class StockError(Exception):
    """Raised for any business-rule violation (insufficient stock, bad state, etc.)."""
    pass


def _get_or_create_stock_row(location_id, product_id, lock=True):
    q = LocationStock.query.filter_by(location_id=location_id, product_id=product_id)
    if lock:
        # SELECT ... FOR UPDATE where the backend supports it (Postgres/MySQL).
        # SQLite ignores with_for_update but the outer transaction still serializes writes.
        q = q.with_for_update()
    row = q.first()
    if row is None:
        row = LocationStock(location_id=location_id, product_id=product_id, quantity=0)
        db.session.add(row)
        db.session.flush()
    return row


def _apply_movement(location_id, product_id, delta, movement_type, user_id,
                     reference_type=None, reference_id=None, reason=None, remarks=None):
    """Change quantity by `delta` (can be negative) and write a ledger row. Raises StockError on negative result."""
    row = _get_or_create_stock_row(location_id, product_id)
    qty_before = row.quantity
    qty_after = qty_before + delta
    if qty_after < 0:
        raise StockError(
            f"Insufficient stock: product {product_id} at location {location_id} "
            f"has {qty_before}, cannot apply change of {delta}."
        )
    row.quantity = qty_after
    row.updated_at = datetime.utcnow()

    movement = StockMovement(
        product_id=product_id,
        location_id=location_id,
        movement_type=movement_type,
        qty_before=qty_before,
        qty_change=delta,
        qty_after=qty_after,
        reference_type=reference_type,
        reference_id=reference_id,
        user_id=user_id,
        reason=reason,
        remarks=remarks,
    )
    db.session.add(movement)
    return movement


def _log_approval(request_type, request_id, previous_status, new_status, action_by, comment=None):
    db.session.add(ApprovalLog(
        request_type=request_type, request_id=request_id,
        previous_status=previous_status, new_status=new_status,
        action_by=action_by, comment=comment,
    ))


# ---------------------------------------------------------------------------
# STOCK IN / RECEIVING
# ---------------------------------------------------------------------------

def receive_stock(location_id, items, received_by_id, supplier_source=None, reference_number=None, remarks=None):
    """items: list of (product_id, quantity). Stock updates immediately (receiving is self-approving by the
    person authorized to receive; Main Admin/Stock Manager only, enforced at the route layer)."""
    if not items:
        raise StockError("At least one product line is required.")

    receipt = StockReceipt(
        receipt_code=gen_code("RCV"),
        location_id=location_id,
        supplier_source=supplier_source,
        reference_number=reference_number,
        status=STATUS_COMPLETED,
        received_by=received_by_id,
        remarks=remarks,
    )
    db.session.add(receipt)
    db.session.flush()

    for product_id, qty in items:
        if qty <= 0:
            raise StockError("Quantity must be positive.")
        db.session.add(StockReceiptItem(receipt_id=receipt.id, product_id=product_id, quantity=qty))
        _apply_movement(
            location_id, product_id, qty, MOVEMENT_STOCK_IN, received_by_id,
            reference_type=REQUEST_TYPE_STOCK_IN, reference_id=receipt.id, remarks=remarks,
        )

    db.session.commit()
    return receipt


# ---------------------------------------------------------------------------
# STOCK TRANSFER  (Draft -> Requested -> Approved -> Dispatched -> Received -> Completed | Rejected)
# ---------------------------------------------------------------------------

def create_transfer_request(source_location_id, dest_location_id, items, requested_by_id, remarks=None):
    if source_location_id == dest_location_id:
        raise StockError("Source and destination locations must differ.")
    if not items:
        raise StockError("At least one product line is required.")

    transfer = StockTransfer(
        transfer_code=gen_code("TRF"),
        source_location_id=source_location_id,
        dest_location_id=dest_location_id,
        status=STATUS_PENDING_APPROVAL,
        requested_by=requested_by_id,
        remarks=remarks,
    )
    db.session.add(transfer)
    db.session.flush()

    for product_id, qty in items:
        if qty <= 0:
            raise StockError("Quantity must be positive.")
        # Validate enough stock exists at source at request time (soft check; re-checked again on approval).
        row = LocationStock.query.filter_by(location_id=source_location_id, product_id=product_id).first()
        available = row.quantity if row else 0
        if qty > available:
            raise StockError(f"Requested quantity ({qty}) exceeds available stock ({available}) for product {product_id}.")
        db.session.add(StockTransferItem(transfer_id=transfer.id, product_id=product_id, quantity=qty))

    _log_approval(REQUEST_TYPE_TRANSFER, transfer.id, None, STATUS_PENDING_APPROVAL, requested_by_id, comment="Transfer requested")
    db.session.commit()
    return transfer


def approve_transfer(transfer_id, approver_id, approve=True, comment=None):
    transfer = StockTransfer.query.with_for_update().get(transfer_id)
    if transfer is None:
        raise StockError("Transfer not found.")
    if transfer.status != STATUS_PENDING_APPROVAL:
        raise StockError(f"Transfer cannot be approved/rejected from status {transfer.status}.")

    prev = transfer.status
    if approve:
        # Re-validate stock right before committing (protects against concurrent depletion).
        for item in transfer.items:
            row = LocationStock.query.filter_by(
                location_id=transfer.source_location_id, product_id=item.product_id
            ).with_for_update().first()
            available = row.quantity if row else 0
            if item.quantity > available:
                raise StockError(f"Insufficient stock for product {item.product_id} at approval time.")
        transfer.status = STATUS_APPROVED
        transfer.approved_by = approver_id
        transfer.approved_at = datetime.utcnow()
    else:
        transfer.status = STATUS_REJECTED
        transfer.approved_by = approver_id
        transfer.approved_at = datetime.utcnow()

    _log_approval(REQUEST_TYPE_TRANSFER, transfer.id, prev, transfer.status, approver_id, comment=comment)
    db.session.commit()
    return transfer


def dispatch_transfer(transfer_id, dispatcher_id, comment=None):
    """Deducts stock from source location (TRANSFER_OUT) and marks as dispatched/in-transit."""
    transfer = StockTransfer.query.with_for_update().get(transfer_id)
    if transfer is None:
        raise StockError("Transfer not found.")
    if transfer.status != STATUS_APPROVED:
        raise StockError(f"Transfer must be APPROVED before dispatch (currently {transfer.status}).")

    for item in transfer.items:
        _apply_movement(
            transfer.source_location_id, item.product_id, -item.quantity, MOVEMENT_TRANSFER_OUT,
            dispatcher_id, reference_type=REQUEST_TYPE_TRANSFER, reference_id=transfer.id,
            remarks=f"Dispatch to location {transfer.dest_location_id}",
        )

    prev = transfer.status
    transfer.status = STATUS_PROCESSING
    transfer.dispatched_at = datetime.utcnow()
    _log_approval(REQUEST_TYPE_TRANSFER, transfer.id, prev, transfer.status, dispatcher_id, comment=comment or "Dispatched")
    db.session.commit()
    return transfer


def receive_transfer(transfer_id, receiver_id, comment=None):
    """Adds stock to destination location (TRANSFER_IN) and marks transfer COMPLETED."""
    transfer = StockTransfer.query.with_for_update().get(transfer_id)
    if transfer is None:
        raise StockError("Transfer not found.")
    if transfer.status != STATUS_PROCESSING:
        raise StockError(f"Transfer must be dispatched (PROCESSING) before it can be received (currently {transfer.status}).")

    for item in transfer.items:
        _apply_movement(
            transfer.dest_location_id, item.product_id, item.quantity, MOVEMENT_TRANSFER_IN,
            receiver_id, reference_type=REQUEST_TYPE_TRANSFER, reference_id=transfer.id,
            remarks=f"Received from location {transfer.source_location_id}",
        )

    prev = transfer.status
    transfer.status = STATUS_COMPLETED
    transfer.received_by = receiver_id
    transfer.received_at = datetime.utcnow()
    transfer.completed_at = datetime.utcnow()
    _log_approval(REQUEST_TYPE_TRANSFER, transfer.id, prev, transfer.status, receiver_id, comment=comment or "Received")
    db.session.commit()
    return transfer


def cancel_transfer(transfer_id, user_id, comment=None):
    transfer = StockTransfer.query.with_for_update().get(transfer_id)
    if transfer is None:
        raise StockError("Transfer not found.")
    if transfer.status in (STATUS_COMPLETED, STATUS_CANCELLED, STATUS_REJECTED):
        raise StockError(f"Transfer in status {transfer.status} cannot be cancelled.")
    if transfer.status == STATUS_PROCESSING:
        raise StockError("Transfer already dispatched; it must be received or otherwise reconciled, not cancelled.")
    prev = transfer.status
    transfer.status = STATUS_CANCELLED
    _log_approval(REQUEST_TYPE_TRANSFER, transfer.id, prev, transfer.status, user_id, comment=comment or "Cancelled")
    db.session.commit()
    return transfer


# ---------------------------------------------------------------------------
# STOCK ADJUSTMENT
# ---------------------------------------------------------------------------

def create_adjustment_request(location_id, product_id, adjustment_qty, reason, requested_by_id, remarks=None):
    row = LocationStock.query.filter_by(location_id=location_id, product_id=product_id).first()
    previous_qty = row.quantity if row else 0
    new_qty = previous_qty + adjustment_qty
    if new_qty < 0:
        raise StockError("Adjustment would result in negative stock.")

    adj = StockAdjustment(
        adjustment_code=gen_code("ADJ"),
        location_id=location_id,
        product_id=product_id,
        previous_qty=previous_qty,
        adjustment_qty=adjustment_qty,
        new_qty=new_qty,
        reason=reason,
        status=STATUS_PENDING_APPROVAL,
        requested_by=requested_by_id,
        remarks=remarks,
    )
    db.session.add(adj)
    db.session.flush()
    _log_approval(REQUEST_TYPE_ADJUSTMENT, adj.id, None, STATUS_PENDING_APPROVAL, requested_by_id, comment="Adjustment requested")
    db.session.commit()
    return adj


def approve_adjustment(adjustment_id, approver_id, approve=True, comment=None):
    adj = StockAdjustment.query.with_for_update().get(adjustment_id)
    if adj is None:
        raise StockError("Adjustment not found.")
    if adj.status != STATUS_PENDING_APPROVAL:
        raise StockError(f"Adjustment cannot be actioned from status {adj.status}.")

    prev = adj.status
    if approve:
        movement_type = MOVEMENT_ADJUSTMENT_IN if adj.adjustment_qty >= 0 else MOVEMENT_ADJUSTMENT_OUT
        _apply_movement(
            adj.location_id, adj.product_id, adj.adjustment_qty, movement_type, approver_id,
            reference_type=REQUEST_TYPE_ADJUSTMENT, reference_id=adj.id, reason=adj.reason,
        )
        adj.status = STATUS_COMPLETED
    else:
        adj.status = STATUS_REJECTED
    adj.approved_by = approver_id
    adj.approved_at = datetime.utcnow()

    _log_approval(REQUEST_TYPE_ADJUSTMENT, adj.id, prev, adj.status, approver_id, comment=comment)
    db.session.commit()
    return adj


# ---------------------------------------------------------------------------
# STOCK RETURN  (Employee -> Stock Manager -> [Main Admin] -> stock updated)
# ---------------------------------------------------------------------------

def create_return_request(source_location_id, dest_location_id, items, reason, requested_by_id, remarks=None):
    if not items:
        raise StockError("At least one product line is required.")

    ret = StockReturn(
        return_code=gen_code("RET"),
        source_location_id=source_location_id,
        dest_location_id=dest_location_id,
        status=STATUS_PENDING_APPROVAL,
        reason=reason,
        requested_by=requested_by_id,
        remarks=remarks,
    )
    db.session.add(ret)
    db.session.flush()

    for product_id, qty in items:
        if qty <= 0:
            raise StockError("Quantity must be positive.")
        row = LocationStock.query.filter_by(location_id=source_location_id, product_id=product_id).first()
        available = row.quantity if row else 0
        if qty > available:
            raise StockError(f"Return quantity ({qty}) exceeds eligible stock ({available}) for product {product_id}.")
        db.session.add(StockReturnItem(return_id=ret.id, product_id=product_id, quantity=qty))

    _log_approval(REQUEST_TYPE_RETURN, ret.id, None, STATUS_PENDING_APPROVAL, requested_by_id, comment="Return requested")
    db.session.commit()
    return ret


def stock_manager_review_return(return_id, approver_id, approve=True, comment=None, requires_admin=True):
    ret = StockReturn.query.with_for_update().get(return_id)
    if ret is None:
        raise StockError("Return not found.")
    if ret.status != STATUS_PENDING_APPROVAL:
        raise StockError(f"Return cannot be reviewed from status {ret.status}.")

    prev = ret.status
    ret.sm_approved_by = approver_id
    ret.sm_approved_at = datetime.utcnow()

    if not approve:
        ret.status = STATUS_REJECTED
    elif requires_admin:
        ret.status = STATUS_PROCESSING  # awaiting Main Admin final approval
    else:
        _finalize_return(ret, approver_id)

    _log_approval(REQUEST_TYPE_RETURN, ret.id, prev, ret.status, approver_id, comment=comment)
    db.session.commit()
    return ret


def admin_review_return(return_id, approver_id, approve=True, comment=None):
    ret = StockReturn.query.with_for_update().get(return_id)
    if ret is None:
        raise StockError("Return not found.")
    if ret.status != STATUS_PROCESSING:
        raise StockError(f"Return is not awaiting Main Admin approval (status {ret.status}).")

    prev = ret.status
    ret.admin_approved_by = approver_id
    ret.admin_approved_at = datetime.utcnow()

    if approve:
        _finalize_return(ret, approver_id)
    else:
        ret.status = STATUS_REJECTED

    _log_approval(REQUEST_TYPE_RETURN, ret.id, prev, ret.status, approver_id, comment=comment)
    db.session.commit()
    return ret


def _finalize_return(ret, actor_id):
    """Move stock: OUT of source location, IN to destination location. Called once, at final approval."""
    for item in ret.items:
        _apply_movement(
            ret.source_location_id, item.product_id, -item.quantity, MOVEMENT_RETURN_OUT, actor_id,
            reference_type=REQUEST_TYPE_RETURN, reference_id=ret.id, reason=ret.reason,
        )
        _apply_movement(
            ret.dest_location_id, item.product_id, item.quantity, MOVEMENT_RETURN_IN, actor_id,
            reference_type=REQUEST_TYPE_RETURN, reference_id=ret.id, reason=ret.reason,
        )
    ret.status = STATUS_COMPLETED
    ret.completed_at = datetime.utcnow()
