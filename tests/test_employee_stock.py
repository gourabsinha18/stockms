"""
Automated tests for the Employee Stock Issue & Return module (Phase 24).

Core invariant under test:

    EMPLOYEE RETURN -> STOCK MANAGER DECISION -> GOOD -> LocationStock
                                               -> BAD  -> BadProductStock
                                               -> REJECTED -> nothing moves

Every quantity change is mirrored 1:1 between EmployeeStock and exactly one
of LocationStock / BadProductStock - never both, never neither.
"""
from datetime import date
import pytest

from app.extensions import db
from app.models import (
    LocationStock, StockMovement, BadProductStock, BadProductMovement,
    EmployeeStock, EmployeeStockTransaction, EmployeeReturnRequest, Employee,
)
from app.services.stock_service import receive_stock
from app.services.employee_stock_service import (
    issue_stock_to_employee, create_return_request,
    approve_return_as_good, approve_return_as_bad, reject_return,
    EmployeeStockError,
)


def _emp_qty(employee_id, product_id):
    row = EmployeeStock.query.filter_by(employee_id=employee_id, product_id=product_id).first()
    return row.quantity if row else 0


def _normal_qty(location_id, product_id):
    row = LocationStock.query.filter_by(location_id=location_id, product_id=product_id).first()
    return row.quantity if row else 0


def _bad_qty(location_id, product_id):
    row = BadProductStock.query.filter_by(location_id=location_id, product_id=product_id).first()
    return row.quantity if row else 0


def _login(client, username, password="password123"):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=True)


# ---------------------------------------------------------------------------
# STOCK ISSUE
# ---------------------------------------------------------------------------

def test_issue_decreases_normal_stock_and_increases_employee_stock(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()

    issue_stock_to_employee(seed["emp"], seed["product"], 10, seed["mgr"], "Field kit")
    db.session.commit()

    assert _normal_qty(seed["loc_a"], seed["product"]) == 10
    assert _emp_qty(seed["emp"], seed["product"]) == 10

    txns = EmployeeStockTransaction.query.filter_by(employee_id=seed["emp"]).all()
    assert len(txns) == 1
    assert txns[0].transaction_type == "ISSUE"
    assert txns[0].quantity_change == 10


def test_issue_rejected_when_insufficient_normal_stock(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 5)], seed["admin"])
    db.session.commit()

    with pytest.raises(EmployeeStockError):
        issue_stock_to_employee(seed["emp"], seed["product"], 10, seed["mgr"], "too much")
    db.session.rollback()

    assert _normal_qty(seed["loc_a"], seed["product"]) == 5
    assert _emp_qty(seed["emp"], seed["product"]) == 0


def test_issue_uses_employees_own_location_not_a_passed_in_one(app, db, seed):
    """issue_stock_to_employee has no location_id parameter at all - proving the location can
    only ever come from the employee record, never from a caller/route argument."""
    import inspect
    sig = inspect.signature(issue_stock_to_employee)
    assert "location_id" not in sig.parameters


# ---------------------------------------------------------------------------
# GOOD RETURN
# ---------------------------------------------------------------------------

def test_good_return_moves_stock_from_employee_to_normal(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    issue_stock_to_employee(seed["emp"], seed["product"], 10, seed["mgr"], "issued")
    db.session.commit()
    assert _normal_qty(seed["loc_a"], seed["product"]) == 10
    assert _emp_qty(seed["emp"], seed["product"]) == 10

    sm_count_before = StockMovement.query.count()
    ret = create_return_request(seed["emp"], seed["product"], 3, "GOOD", reason="unused")
    db.session.commit()

    # Not yet approved: nothing should have moved.
    assert _normal_qty(seed["loc_a"], seed["product"]) == 10
    assert _emp_qty(seed["emp"], seed["product"]) == 10

    approve_return_as_good(ret.id, seed["mgr"], remarks="looks fine")
    db.session.commit()

    assert _normal_qty(seed["loc_a"], seed["product"]) == 13  # 10 + 3
    assert _emp_qty(seed["emp"], seed["product"]) == 7        # 10 - 3
    assert _bad_qty(seed["loc_a"], seed["product"]) == 0       # BAD bucket untouched

    sm_count_after = StockMovement.query.count()
    assert sm_count_after == sm_count_before + 1  # exactly one new normal-stock movement
    assert db.session.get(EmployeeReturnRequest, ret.id).status == "APPROVED_GOOD"


# ---------------------------------------------------------------------------
# BAD RETURN
# ---------------------------------------------------------------------------

def test_bad_return_moves_stock_from_employee_to_bad_product_stock_only(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    issue_stock_to_employee(seed["emp"], seed["product"], 10, seed["mgr"], "issued")
    db.session.commit()

    sm_count_before = StockMovement.query.count()
    ret = create_return_request(seed["emp"], seed["product"], 3, "BAD", reason="damaged in field")
    db.session.commit()

    approve_return_as_bad(ret.id, seed["mgr"], remarks="confirmed damaged")
    db.session.commit()

    # THE CRITICAL ASSERTION: normal stock must NOT have changed.
    assert _normal_qty(seed["loc_a"], seed["product"]) == 10
    assert _emp_qty(seed["emp"], seed["product"]) == 7
    assert _bad_qty(seed["loc_a"], seed["product"]) == 3

    sm_count_after = StockMovement.query.count()
    assert sm_count_after == sm_count_before, "A BAD return must never create a normal StockMovement row"

    bpm = BadProductMovement.query.filter_by(reference_type="EMPLOYEE_RETURN", reference_id=ret.id).all()
    assert len(bpm) == 1
    assert bpm[0].quantity_change == 3
    assert bpm[0].movement_type == "BAD_EMPLOYEE_RETURN"
    assert db.session.get(EmployeeReturnRequest, ret.id).status == "APPROVED_BAD"


def test_bad_product_module_is_reused_not_duplicated(app, db, seed):
    """The BAD path must go through the EXISTING bad_product_service primitive, not a
    second/parallel implementation."""
    from app.services import employee_stock_service
    import inspect
    source = inspect.getsource(employee_stock_service)
    assert "_apply_bad_movement" in source
    assert "from app.services.bad_product_service import" in source


# ---------------------------------------------------------------------------
# REJECTION
# ---------------------------------------------------------------------------

def test_rejected_return_changes_nothing(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    issue_stock_to_employee(seed["emp"], seed["product"], 10, seed["mgr"], "issued")
    db.session.commit()

    sm_count_before = StockMovement.query.count()
    bpm_count_before = BadProductMovement.query.count()

    ret = create_return_request(seed["emp"], seed["product"], 3, "GOOD", reason="changed my mind")
    db.session.commit()
    reject_return(ret.id, seed["mgr"], remarks="not eligible")
    db.session.commit()

    assert _normal_qty(seed["loc_a"], seed["product"]) == 10
    assert _emp_qty(seed["emp"], seed["product"]) == 10  # unchanged - stays with the employee
    assert _bad_qty(seed["loc_a"], seed["product"]) == 0
    assert StockMovement.query.count() == sm_count_before
    assert BadProductMovement.query.count() == bpm_count_before
    assert EmployeeStockTransaction.query.filter_by(employee_id=seed["emp"], transaction_type="GOOD_RETURN").count() == 0
    assert db.session.get(EmployeeReturnRequest, ret.id).status == "REJECTED"


# ---------------------------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------------------------

def test_cannot_return_more_than_owned(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    issue_stock_to_employee(seed["emp"], seed["product"], 10, seed["mgr"], "issued")
    db.session.commit()

    with pytest.raises(EmployeeStockError):
        create_return_request(seed["emp"], seed["product"], 11, "GOOD")
    db.session.rollback()
    assert _emp_qty(seed["emp"], seed["product"]) == 10


def test_partial_return_leaves_remainder_with_employee(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    issue_stock_to_employee(seed["emp"], seed["product"], 20, seed["mgr"], "issued")
    db.session.commit()

    ret = create_return_request(seed["emp"], seed["product"], 5, "GOOD")
    db.session.commit()
    approve_return_as_good(ret.id, seed["mgr"])
    db.session.commit()

    assert _emp_qty(seed["emp"], seed["product"]) == 15
    assert _normal_qty(seed["loc_a"], seed["product"]) == 5  # 0 remaining after full issue + 5 returned

    # A second, separate return against the same remaining balance.
    ret2 = create_return_request(seed["emp"], seed["product"], 15, "GOOD")
    db.session.commit()
    approve_return_as_good(ret2.id, seed["mgr"])
    db.session.commit()

    assert _emp_qty(seed["emp"], seed["product"]) == 0
    assert _normal_qty(seed["loc_a"], seed["product"]) == 20  # fully back


def test_double_approval_fails(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    issue_stock_to_employee(seed["emp"], seed["product"], 10, seed["mgr"], "issued")
    db.session.commit()
    ret = create_return_request(seed["emp"], seed["product"], 3, "GOOD")
    db.session.commit()
    approve_return_as_good(ret.id, seed["mgr"])
    db.session.commit()

    with pytest.raises(EmployeeStockError):
        approve_return_as_good(ret.id, seed["mgr"])
    db.session.rollback()

    assert _emp_qty(seed["emp"], seed["product"]) == 7  # not double-decremented
    assert _normal_qty(seed["loc_a"], seed["product"]) == 13  # not double-incremented


def test_self_approval_is_blocked(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    issue_stock_to_employee(seed["emp"], seed["product"], 10, seed["mgr"], "issued")
    db.session.commit()
    ret = create_return_request(seed["emp"], seed["product"], 3, "GOOD")
    db.session.commit()

    employee = db.session.get(Employee, seed["emp"])
    with pytest.raises(EmployeeStockError):
        approve_return_as_good(ret.id, employee.user_id)  # the employee trying to approve their own request
    db.session.rollback()
    assert db.session.get(EmployeeReturnRequest, ret.id).status == "PENDING"


# ---------------------------------------------------------------------------
# HTTP-LEVEL SECURITY
# ---------------------------------------------------------------------------

def test_employee_cannot_view_another_employees_directory_page(app, db, client, seed):
    _login(client, "emp1")
    resp = client.get(f"/users/employees/{seed['emp2']}")
    assert resp.status_code == 403


def test_employee_can_view_own_profile(app, db, client, seed):
    _login(client, "emp1")
    resp = client.get(f"/users/employees/{seed['emp']}")
    assert resp.status_code == 200


def test_direct_url_access_blocked_for_unauthorized_location(app, db, client, seed):
    """mgr1 is assigned to both loc_a and loc_b in the seed fixture; this test uses a manager
    with access to only ONE location to prove cross-location access is denied."""
    from app.models import User, StockManagerAssignment, ROLE_STOCK_MANAGER
    mgr2 = User(username="mgr2", email="mgr2@example.com", full_name="Manager Two", role=ROLE_STOCK_MANAGER)
    mgr2.set_password("password123")
    db.session.add(mgr2)
    db.session.flush()
    db.session.add(StockManagerAssignment(user_id=mgr2.id, location_id=seed["loc_a"]))  # loc_a only
    db.session.commit()

    _login(client, "mgr2")
    resp = client.get(f"/users/employees/{seed['emp2']}")  # emp2 is at loc_b
    assert resp.status_code == 403


def test_employee_cannot_issue_stock(app, db, client, seed):
    _login(client, "emp1")
    resp = client.get("/employee-stock/issue")
    assert resp.status_code == 403


def test_employee_cannot_approve_return(app, db, client, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    issue_stock_to_employee(seed["emp"], seed["product"], 10, seed["mgr"], "issued")
    db.session.commit()
    ret = create_return_request(seed["emp"], seed["product"], 3, "GOOD")
    db.session.commit()

    _login(client, "emp1")
    resp = client.post(f"/employee-stock/returns/{ret.id}/approve-good", data={})
    assert resp.status_code == 403


def test_employee_forged_ids_are_ignored(app, db, client, seed):
    """Even if an employee's return-submission POST included a forged employee_id/location_id,
    the route only ever uses current_user.employee_profile - there is no employee_id field on the
    return form at all."""
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    issue_stock_to_employee(seed["emp"], seed["product"], 10, seed["mgr"], "issued")
    db.session.commit()

    _login(client, "emp1")
    resp = client.post("/employee-stock/my-stock/return/new", data={
        "product_id": str(seed["product"]), "quantity": "2", "reported_condition": "GOOD",
        "reason": "test", "employee_id": str(seed["emp2"]),  # forged/irrelevant field
    }, follow_redirects=True)
    assert resp.status_code == 200

    ret = EmployeeReturnRequest.query.filter_by(reason="test").first()
    assert ret is not None
    assert ret.employee_id == seed["emp"], "Return must always be attributed to the logged-in employee, never a forged id"


def test_direct_url_access_to_issue_route_blocked_for_employee_role(app, db, client, seed):
    """Manually changing the URL / hitting the endpoint directly (not just hiding a button)."""
    _login(client, "emp1")
    resp = client.post("/employee-stock/issue", data={"employee_id": str(seed["emp"]), "product_id": str(seed["product"]),
                                                       "quantity": "1", "reason": "self-issue attempt"})
    assert resp.status_code == 403
