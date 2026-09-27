"""
Employee Stock Issue & Return - centralized mutation service.

EmployeeStock is a THIRD independent inventory bucket, alongside normal
LocationStock and BadProductStock:

    LocationStock  <---- issue_stock_to_employee() ----  EmployeeStock
    LocationStock  ---- approve_return_as_good()   ---->  EmployeeStock
    BadProductStock ---- approve_return_as_bad()   ----  EmployeeStock

Every quantity change is mirrored 1:1 in exactly one other bucket - nothing
here ever creates or destroys quantity, and nothing here ever touches more
than one "other" bucket per operation. This module reuses:

  - app.services.stock_service._apply_movement()        for LocationStock changes
  - app.services.bad_product_service._apply_bad_movement() for BadProductStock changes

so that EmployeeStock never becomes a backdoor around either existing
inventory's own ledger/locking rules.

TRANSACTION MODEL: exactly like bad_product_service.py, functions here do
NOT call db.session.commit(). The caller (the route) adds AuditLog/
Notification rows afterwards and issues ONE db.session.commit() so that
"stock update(s) + ledger row(s) + status change + audit + notification"
land in a single atomic transaction.
"""
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import (
    Employee, EmployeeStock, EmployeeStockTransaction, EmployeeReturnRequest,
    LocationStock, ApprovalLog,
    EMP_TXN_ISSUE, EMP_TXN_GOOD_RETURN, EMP_TXN_BAD_RETURN,
    EMP_RETURN_STATUS_PENDING, EMP_RETURN_STATUS_APPROVED_GOOD,
    EMP_RETURN_STATUS_APPROVED_BAD, EMP_RETURN_STATUS_REJECTED,
    EMP_CONDITION_GOOD, EMP_CONDITION_BAD,
    MOVEMENT_EMPLOYEE_ISSUE, MOVEMENT_EMPLOYEE_RETURN_GOOD, MOVEMENT_BAD_EMPLOYEE_RETURN,
    REQUEST_TYPE_EMPLOYEE_RETURN,
    gen_code,
)
from app.services.stock_service import _apply_movement as _apply_location_movement, StockError
from app.services.bad_product_service import _apply_bad_movement, BadProductError


class EmployeeStockError(Exception):
    """Raised for any business-rule violation in this module (insufficient stock, bad state, etc.)."""
    pass


def _get_or_create_employee_stock_row(employee_id, product_id, lock=True):
    """Concurrency-safe get-or-create, identical strategy to
    bad_product_service._get_or_create_bad_stock_row (see that function's docstring for why the
    naive `SELECT ... FOR UPDATE` + create pattern is unsafe for the very first row)."""
    q = EmployeeStock.query.filter_by(employee_id=employee_id, product_id=product_id)
    if lock:
        q = q.with_for_update()
    row = q.first()
    if row is not None:
        return row

    try:
        with db.session.begin_nested():
            row = EmployeeStock(employee_id=employee_id, product_id=product_id, quantity=0)
            db.session.add(row)
            db.session.flush()
        return row
    except IntegrityError:
        q2 = EmployeeStock.query.filter_by(employee_id=employee_id, product_id=product_id)
        if lock:
            q2 = q2.with_for_update()
        row = q2.first()
        if row is None:
            raise
        return row


def _apply_employee_stock_movement(employee_id, product_id, delta, transaction_type, performed_by_id,
                                    reference_type=None, reference_id=None, reason=None):
    """Change EmployeeStock quantity by `delta` and write an EmployeeStockTransaction ledger row.
    Raises EmployeeStockError on negative result."""
    row = _get_or_create_employee_stock_row(employee_id, product_id)
    quantity_before = row.quantity
    quantity_after = quantity_before + delta
    if quantity_after < 0:
        raise EmployeeStockError(
            f"Insufficient employee stock: employee {employee_id}, product {product_id} has "
            f"{quantity_before}, cannot apply change of {delta}."
        )
    row.quantity = quantity_after
    row.updated_at = datetime.utcnow()

    employee = Employee.query.get(employee_id)
    txn = EmployeeStockTransaction(
        employee_id=employee_id,
        product_id=product_id,
        location_id=employee.location_id,
        transaction_type=transaction_type,
        quantity_before=quantity_before,
        quantity_change=delta,
        quantity_after=quantity_after,
        reference_type=reference_type,
        reference_id=reference_id,
        performed_by=performed_by_id,
        reason=reason,
    )
    db.session.add(txn)
    return txn


def _log_approval(request_id, previous_status, new_status, action_by, comment=None):
    db.session.add(ApprovalLog(
        request_type=REQUEST_TYPE_EMPLOYEE_RETURN, request_id=request_id,
        previous_status=previous_status, new_status=new_status,
        action_by=action_by, comment=comment,
    ))


# ---------------------------------------------------------------------------
# STOCK ISSUE TO EMPLOYEE  (Stock Manager -> Employee, self-approving, mirrors receive_stock())
# ---------------------------------------------------------------------------

def issue_stock_to_employee(employee_id, product_id, quantity, issued_by_id, reason):
    """Decreases LocationStock at the employee's OWN location and increases EmployeeStock by the
    same amount. `location_id` is never taken from the caller - it is always derived from the
    employee record, so an issue can never silently move stock out of a location the employee
    doesn't belong to. Does NOT commit; caller commits once."""
    employee = Employee.query.get(employee_id)
    if employee is None or not employee.is_active:
        raise EmployeeStockError("Employee not found or inactive.")
    if quantity <= 0:
        raise EmployeeStockError("Quantity must be positive.")
    if not reason:
        raise EmployeeStockError("Reason is required.")

    location_id = employee.location_id  # authoritative - never trust a client-supplied location_id here

    row = LocationStock.query.filter_by(location_id=location_id, product_id=product_id).first()
    available = row.quantity if row else 0
    if quantity > available:
        raise EmployeeStockError(f"Requested quantity ({quantity}) exceeds available stock ({available}).")

    # 1) Normal stock decreases (reuses the existing StockMovement ledger - not a parallel one).
    try:
        _apply_location_movement(
            location_id, product_id, -quantity, MOVEMENT_EMPLOYEE_ISSUE, issued_by_id,
            reference_type="EMPLOYEE_ISSUE", reference_id=employee.id, reason=reason,
        )
    except StockError as e:
        raise EmployeeStockError(str(e))

    # 2) Employee stock increases (this module's own ledger).
    txn = _apply_employee_stock_movement(
        employee_id, product_id, quantity, EMP_TXN_ISSUE, issued_by_id,
        reference_type="EMPLOYEE_ISSUE", reference_id=employee.id, reason=reason,
    )
    return txn


# ---------------------------------------------------------------------------
# EMPLOYEE RETURN REQUEST  (PENDING -> APPROVED_GOOD | APPROVED_BAD | REJECTED)
# ---------------------------------------------------------------------------

def create_return_request(employee_id, product_id, quantity, reported_condition, reason=None):
    """The employee's own request. `reported_condition` is a REPORT ONLY (Phase 8/27): it never
    decides where the stock ends up - only the Stock Manager's decision does that.
    Does NOT commit; caller commits once."""
    if quantity <= 0:
        raise EmployeeStockError("Return quantity must be positive.")
    if reported_condition not in (EMP_CONDITION_GOOD, EMP_CONDITION_BAD):
        raise EmployeeStockError("Invalid reported condition.")

    employee = Employee.query.get(employee_id)
    if employee is None or not employee.is_active:
        raise EmployeeStockError("Employee not found or inactive.")

    row = EmployeeStock.query.filter_by(employee_id=employee_id, product_id=product_id).first()
    owned = row.quantity if row else 0
    if quantity > owned:
        raise EmployeeStockError(f"Return quantity ({quantity}) exceeds your current quantity ({owned}) of this product.")

    ret = EmployeeReturnRequest(
        return_code=gen_code("ERET"),
        employee_id=employee_id,
        product_id=product_id,
        location_id=employee.location_id,
        quantity=quantity,
        reported_condition=reported_condition,
        reason=reason,
        status=EMP_RETURN_STATUS_PENDING,
    )
    db.session.add(ret)
    db.session.flush()
    _log_approval(ret.id, None, EMP_RETURN_STATUS_PENDING, employee.user_id, comment="Employee return requested")
    return ret


def _load_pending_return_for_review(return_id, approver_id):
    ret = EmployeeReturnRequest.query.with_for_update().get(return_id)
    if ret is None:
        raise EmployeeStockError("Return request not found.")
    if ret.status != EMP_RETURN_STATUS_PENDING:
        raise EmployeeStockError(f"Return request cannot be actioned from status {ret.status}.")
    if ret.employee.user_id == approver_id:
        raise EmployeeStockError("An employee cannot approve/reject their own return request.")
    return ret


def approve_return_as_good(return_id, approver_id, remarks=None):
    """Employee stock decreases; normal LocationStock increases by the same amount (reuses the
    existing StockMovement ledger). Does NOT commit; caller commits once."""
    ret = _load_pending_return_for_review(return_id, approver_id)
    prev = ret.status

    _apply_employee_stock_movement(
        ret.employee_id, ret.product_id, -ret.quantity, EMP_TXN_GOOD_RETURN, approver_id,
        reference_type=REQUEST_TYPE_EMPLOYEE_RETURN, reference_id=ret.id, reason=ret.reason,
    )
    try:
        _apply_location_movement(
            ret.location_id, ret.product_id, ret.quantity, MOVEMENT_EMPLOYEE_RETURN_GOOD, approver_id,
            reference_type=REQUEST_TYPE_EMPLOYEE_RETURN, reference_id=ret.id, reason=ret.reason,
        )
    except StockError as e:
        raise EmployeeStockError(str(e))

    ret.status = EMP_RETURN_STATUS_APPROVED_GOOD
    ret.reviewed_by = approver_id
    ret.reviewed_at = datetime.utcnow()
    ret.completed_at = datetime.utcnow()
    ret.manager_remarks = remarks
    _log_approval(ret.id, prev, ret.status, approver_id, comment=remarks)
    return ret


def approve_return_as_bad(return_id, approver_id, remarks=None):
    """Employee stock decreases; BadProductStock increases by the same amount, using the EXISTING
    Bad Product module's own mutation primitive (_apply_bad_movement) - never a second bad-stock
    system, and never LocationStock/StockMovement. Does NOT commit; caller commits once."""
    ret = _load_pending_return_for_review(return_id, approver_id)
    prev = ret.status

    _apply_employee_stock_movement(
        ret.employee_id, ret.product_id, -ret.quantity, EMP_TXN_BAD_RETURN, approver_id,
        reference_type=REQUEST_TYPE_EMPLOYEE_RETURN, reference_id=ret.id, reason=ret.reason,
    )
    try:
        _apply_bad_movement(
            ret.location_id, ret.product_id, ret.quantity, MOVEMENT_BAD_EMPLOYEE_RETURN, approver_id,
            reference_type=REQUEST_TYPE_EMPLOYEE_RETURN, reference_id=ret.id,
            remarks=f"Employee return {ret.return_code} classified BAD by manager",
        )
    except BadProductError as e:
        raise EmployeeStockError(str(e))

    ret.status = EMP_RETURN_STATUS_APPROVED_BAD
    ret.reviewed_by = approver_id
    ret.reviewed_at = datetime.utcnow()
    ret.completed_at = datetime.utcnow()
    ret.manager_remarks = remarks
    _log_approval(ret.id, prev, ret.status, approver_id, comment=remarks)
    return ret


def reject_return(return_id, approver_id, remarks=None):
    """No inventory movement of any kind. Does NOT commit; caller commits once."""
    ret = _load_pending_return_for_review(return_id, approver_id)
    prev = ret.status
    ret.status = EMP_RETURN_STATUS_REJECTED
    ret.reviewed_by = approver_id
    ret.reviewed_at = datetime.utcnow()
    ret.manager_remarks = remarks
    _log_approval(ret.id, prev, ret.status, approver_id, comment=remarks)
    return ret
