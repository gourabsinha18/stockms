"""
Bad Product Recovery / Bad Products - centralized mutation service.

RULE: No other part of the application may write to BadProductStock.quantity
directly. Every change MUST go through _apply_bad_movement() so that:
  1. Bad product stock never goes negative.
  2. A BadProductMovement ledger row is always created.
  3. The change happens inside a single DB transaction (atomic).

ABSOLUTE RULE: This module NEVER reads from or writes to LocationStock or
StockMovement (the normal stock tables/ledger), and never calls into
stock_service. Normal stock and bad-product stock are fully independent
inventories that happen to share Location/Product master data.

TRANSACTION MODEL (Fix 5): these functions do NOT call db.session.commit()
themselves. Every function here only adds/mutates ORM objects and uses
db.session.flush() when it needs a generated ID before continuing. The
caller (normally the route) is responsible for the single, final
db.session.commit() that also persists the AuditLog/Notification rows the
route adds afterwards - so "stock update + BadProductMovement + status
change + audit + notification" all land in ONE atomic transaction. If the
caller's commit fails, everything (including the stock/status change made
here) rolls back together; nothing can be partially applied.
"""
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import (
    BadProductStock, BadProductMovement,
    BadProductRecovery, BadProductRecoveryItem,
    BadProductTransfer, BadProductTransferItem,
    ApprovalLog, Location,
    BAD_RECOVERY_STATUS_PENDING, BAD_RECOVERY_STATUS_REJECTED, BAD_RECOVERY_STATUS_COMPLETED,
    BAD_TRANSFER_STATUS_REQUESTED, BAD_TRANSFER_STATUS_APPROVED, BAD_TRANSFER_STATUS_DISPATCHED,
    BAD_TRANSFER_STATUS_COMPLETED, BAD_TRANSFER_STATUS_REJECTED, BAD_TRANSFER_STATUS_CANCELLED,
    MOVEMENT_BAD_RECOVERY_APPROVED, MOVEMENT_BAD_TRANSFER_OUT, MOVEMENT_BAD_TRANSFER_IN,
    REQUEST_TYPE_BAD_RECOVERY, REQUEST_TYPE_BAD_TRANSFER,
    gen_code,
)


class BadProductError(Exception):
    """Raised for any business-rule violation (insufficient bad stock, bad state, etc.)."""
    pass


def _get_or_create_bad_stock_row(location_id, product_id, lock=True):
    """Concurrency-safe get-or-create (Fix 6).

    `SELECT ... FOR UPDATE` cannot lock a row that does not exist yet, so under
    the previous implementation two simultaneous first-time requests for the
    same (location_id, product_id) could both pass the "not found" check and
    both try to INSERT, racing against the unique constraint.

    This version still tries the locked SELECT first (the fast, common path
    once a row exists). If no row exists, it attempts the INSERT inside a
    SAVEPOINT (db.session.begin_nested()). The database-level unique
    constraint on (location_id, product_id) is the real guarantee: if a
    concurrent transaction wins the race, our INSERT raises IntegrityError,
    the SAVEPOINT is rolled back automatically (the outer transaction is
    untouched), and we simply re-SELECT (now with the lock) to pick up the
    winner's row. This works the same way on SQLite and PostgreSQL/MySQL,
    so it does not require a dialect-specific `INSERT ... ON CONFLICT`.
    """
    q = BadProductStock.query.filter_by(location_id=location_id, product_id=product_id)
    if lock:
        q = q.with_for_update()
    row = q.first()
    if row is not None:
        return row

    try:
        with db.session.begin_nested():
            row = BadProductStock(location_id=location_id, product_id=product_id, quantity=0)
            db.session.add(row)
            db.session.flush()
        return row
    except IntegrityError:
        # Lost the race to a concurrent request that created the row first.
        # The SAVEPOINT above was already rolled back; the outer transaction
        # is still valid. Re-select (with the lock this time) and use that row.
        q2 = BadProductStock.query.filter_by(location_id=location_id, product_id=product_id)
        if lock:
            q2 = q2.with_for_update()
        row = q2.first()
        if row is None:
            raise  # Genuinely unexpected - re-raise the original integrity error.
        return row


def _apply_bad_movement(location_id, product_id, delta, movement_type, user_id,
                         reference_type=None, reference_id=None, remarks=None):
    """Change BadProductStock quantity by `delta` and write a ledger row.
    Raises BadProductError on negative result. Never touches LocationStock/StockMovement."""
    row = _get_or_create_bad_stock_row(location_id, product_id)
    quantity_before = row.quantity
    quantity_after = quantity_before + delta
    if quantity_after < 0:
        raise BadProductError(
            f"Insufficient bad product stock: product {product_id} at location {location_id} "
            f"has {quantity_before}, cannot apply change of {delta}."
        )
    row.quantity = quantity_after
    row.updated_at = datetime.utcnow()

    movement = BadProductMovement(
        location_id=location_id,
        product_id=product_id,
        movement_type=movement_type,
        quantity_before=quantity_before,
        quantity_change=delta,
        quantity_after=quantity_after,
        reference_type=reference_type,
        reference_id=reference_id,
        user_id=user_id,
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


def _validate_location(location_id, field_name):
    """Defense-in-depth (Fix 7): never trust that a location_id from a form/client is real,
    even though WTForms SelectField choices already constrain it in the normal UI flow."""
    loc = Location.query.get(location_id)
    if loc is None or not loc.is_active:
        raise BadProductError(f"{field_name} is not a valid, active location.")
    return loc


# ---------------------------------------------------------------------------
# BAD PRODUCT RECOVERY  (PENDING -> COMPLETED | REJECTED)
# ---------------------------------------------------------------------------

def create_recovery_request(location_id, items, requested_by_id, service_reference, recovery_date, remarks=None):
    """items: list of (product_id, quantity). Does NOT touch stock yet - PENDING until approved.
    Does NOT commit; caller commits once (see module docstring)."""
    _validate_location(location_id, "Location")
    if not items:
        raise BadProductError("At least one product line is required.")
    if not service_reference:
        raise BadProductError("Service / Job Reference is required.")

    recovery = BadProductRecovery(
        recovery_code=gen_code("BREC"),
        location_id=location_id,
        requested_by=requested_by_id,
        service_reference=service_reference,
        recovery_date=recovery_date,
        remarks=remarks,
        status=BAD_RECOVERY_STATUS_PENDING,
    )
    db.session.add(recovery)
    db.session.flush()

    for product_id, qty in items:
        if qty <= 0:
            raise BadProductError("Quantity must be positive.")
        db.session.add(BadProductRecoveryItem(recovery_id=recovery.id, product_id=product_id, quantity=qty))

    _log_approval(REQUEST_TYPE_BAD_RECOVERY, recovery.id, None, BAD_RECOVERY_STATUS_PENDING, requested_by_id,
                  comment="Bad product recovery requested")
    return recovery


def approve_recovery(recovery_id, approver_id, approve=True, comment=None):
    """Atomic: validate -> (if approved) increase BadProductStock + ledger -> mark COMPLETED, or REJECTED.
    Never touches LocationStock or StockMovement. Does NOT commit; caller commits once."""
    recovery = BadProductRecovery.query.with_for_update().get(recovery_id)
    if recovery is None:
        raise BadProductError("Recovery not found.")
    if recovery.status != BAD_RECOVERY_STATUS_PENDING:
        raise BadProductError(f"Recovery cannot be approved/rejected from status {recovery.status}.")

    prev = recovery.status
    recovery.approved_by = approver_id
    recovery.approved_at = datetime.utcnow()

    if approve:
        for item in recovery.items:
            _apply_bad_movement(
                recovery.location_id, item.product_id, item.quantity, MOVEMENT_BAD_RECOVERY_APPROVED,
                approver_id, reference_type=REQUEST_TYPE_BAD_RECOVERY, reference_id=recovery.id,
                remarks=f"Recovery {recovery.recovery_code} approved",
            )
        recovery.status = BAD_RECOVERY_STATUS_COMPLETED
        recovery.completed_at = datetime.utcnow()
    else:
        recovery.status = BAD_RECOVERY_STATUS_REJECTED

    _log_approval(REQUEST_TYPE_BAD_RECOVERY, recovery.id, prev, recovery.status, approver_id, comment=comment)
    return recovery


# ---------------------------------------------------------------------------
# BAD PRODUCT TRANSFER  (REQUESTED -> APPROVED -> DISPATCHED -> COMPLETED[=received] | REJECTED | CANCELLED)
# ---------------------------------------------------------------------------

def create_bad_transfer_request(source_location_id, dest_location_id, items, requested_by_id, remarks=None):
    """Validates against BadProductStock ONLY - never checks or touches LocationStock.
    Does NOT commit; caller commits once."""
    _validate_location(source_location_id, "Source location")
    _validate_location(dest_location_id, "Destination location")
    if source_location_id == dest_location_id:
        raise BadProductError("Source and destination locations must differ.")
    if not items:
        raise BadProductError("At least one product line is required.")

    transfer = BadProductTransfer(
        transfer_code=gen_code("BTRF"),
        source_location_id=source_location_id,
        dest_location_id=dest_location_id,
        status=BAD_TRANSFER_STATUS_REQUESTED,
        requested_by=requested_by_id,
        remarks=remarks,
    )
    db.session.add(transfer)
    db.session.flush()

    for product_id, qty in items:
        if qty <= 0:
            raise BadProductError("Quantity must be positive.")
        row = BadProductStock.query.filter_by(location_id=source_location_id, product_id=product_id).first()
        available = row.quantity if row else 0
        if qty > available:
            raise BadProductError(
                f"Requested quantity ({qty}) exceeds available bad product stock ({available}) for product {product_id}."
            )
        db.session.add(BadProductTransferItem(transfer_id=transfer.id, product_id=product_id, quantity=qty))

    _log_approval(REQUEST_TYPE_BAD_TRANSFER, transfer.id, None, BAD_TRANSFER_STATUS_REQUESTED, requested_by_id,
                  comment="Bad product transfer requested")
    return transfer


def approve_bad_transfer(transfer_id, approver_id, approve=True, comment=None):
    """Does NOT commit; caller commits once."""
    transfer = BadProductTransfer.query.with_for_update().get(transfer_id)
    if transfer is None:
        raise BadProductError("Bad product transfer not found.")
    if transfer.status != BAD_TRANSFER_STATUS_REQUESTED:
        raise BadProductError(f"Transfer cannot be approved/rejected from status {transfer.status}.")

    prev = transfer.status
    if approve:
        # Re-validate bad stock right before committing (protects against concurrent depletion).
        for item in transfer.items:
            row = BadProductStock.query.filter_by(
                location_id=transfer.source_location_id, product_id=item.product_id
            ).with_for_update().first()
            available = row.quantity if row else 0
            if item.quantity > available:
                raise BadProductError(f"Insufficient bad product stock for product {item.product_id} at approval time.")
        transfer.status = BAD_TRANSFER_STATUS_APPROVED
    else:
        transfer.status = BAD_TRANSFER_STATUS_REJECTED
    transfer.approved_by = approver_id
    transfer.approved_at = datetime.utcnow()

    _log_approval(REQUEST_TYPE_BAD_TRANSFER, transfer.id, prev, transfer.status, approver_id, comment=comment)
    return transfer


def dispatch_bad_transfer(transfer_id, dispatcher_id, comment=None):
    """Deducts BadProductStock at source (BAD_TRANSFER_OUT). Never touches LocationStock.
    Does NOT commit; caller commits once."""
    transfer = BadProductTransfer.query.with_for_update().get(transfer_id)
    if transfer is None:
        raise BadProductError("Bad product transfer not found.")
    if transfer.status != BAD_TRANSFER_STATUS_APPROVED:
        raise BadProductError(f"Transfer must be APPROVED before dispatch (currently {transfer.status}).")

    for item in transfer.items:
        _apply_bad_movement(
            transfer.source_location_id, item.product_id, -item.quantity, MOVEMENT_BAD_TRANSFER_OUT,
            dispatcher_id, reference_type=REQUEST_TYPE_BAD_TRANSFER, reference_id=transfer.id,
            remarks=f"Dispatch to location {transfer.dest_location_id}",
        )

    prev = transfer.status
    transfer.status = BAD_TRANSFER_STATUS_DISPATCHED
    transfer.dispatched_at = datetime.utcnow()
    _log_approval(REQUEST_TYPE_BAD_TRANSFER, transfer.id, prev, transfer.status, dispatcher_id,
                  comment=comment or "Dispatched")
    return transfer


def receive_bad_transfer(transfer_id, receiver_id, comment=None):
    """Adds BadProductStock at destination (BAD_TRANSFER_IN) and marks transfer COMPLETED.
    Never touches LocationStock. Does NOT commit; caller commits once."""
    transfer = BadProductTransfer.query.with_for_update().get(transfer_id)
    if transfer is None:
        raise BadProductError("Bad product transfer not found.")
    if transfer.status != BAD_TRANSFER_STATUS_DISPATCHED:
        raise BadProductError(
            f"Transfer must be dispatched before it can be received (currently {transfer.status})."
        )

    for item in transfer.items:
        _apply_bad_movement(
            transfer.dest_location_id, item.product_id, item.quantity, MOVEMENT_BAD_TRANSFER_IN,
            receiver_id, reference_type=REQUEST_TYPE_BAD_TRANSFER, reference_id=transfer.id,
            remarks=f"Received from location {transfer.source_location_id}",
        )

    prev = transfer.status
    transfer.status = BAD_TRANSFER_STATUS_COMPLETED
    transfer.received_by = receiver_id
    transfer.received_at = datetime.utcnow()
    transfer.completed_at = datetime.utcnow()
    _log_approval(REQUEST_TYPE_BAD_TRANSFER, transfer.id, prev, transfer.status, receiver_id,
                  comment=comment or "Received")
    return transfer


def cancel_bad_transfer(transfer_id, user_id, comment=None):
    """Does NOT commit; caller commits once."""
    transfer = BadProductTransfer.query.with_for_update().get(transfer_id)
    if transfer is None:
        raise BadProductError("Bad product transfer not found.")
    if transfer.status in (BAD_TRANSFER_STATUS_COMPLETED, BAD_TRANSFER_STATUS_CANCELLED, BAD_TRANSFER_STATUS_REJECTED):
        raise BadProductError(f"Transfer in status {transfer.status} cannot be cancelled.")
    if transfer.status == BAD_TRANSFER_STATUS_DISPATCHED:
        raise BadProductError("Transfer already dispatched; it must be received, not cancelled.")
    prev = transfer.status
    transfer.status = BAD_TRANSFER_STATUS_CANCELLED
    _log_approval(REQUEST_TYPE_BAD_TRANSFER, transfer.id, prev, transfer.status, user_id, comment=comment or "Cancelled")
    return transfer

