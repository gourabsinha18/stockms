"""
Automated tests for the Bad Product module's core invariant (Fix 3):

    NORMAL STOCK (LocationStock / StockMovement) AND BAD PRODUCT STOCK
    (BadProductStock / BadProductMovement) MUST ALWAYS REMAIN COMPLETELY SEPARATE.

Every test below either:
  (a) drives the service layer directly (app.services.bad_product_service), or
  (b) drives the full HTTP stack (routes + forms + permissions),
and then calls `assert_normal_stock_unchanged()` (see conftest.py) - a single,
reusable, explicitly-documented assertion for the invariant - so the intent of
each test is unambiguous even years later.
"""
from datetime import date
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    LocationStock, StockMovement, BadProductStock, BadProductMovement,
    BadProductRecovery, BadProductTransfer,
)
from app.services.stock_service import receive_stock
from app.services.bad_product_service import (
    create_recovery_request, approve_recovery,
    create_bad_transfer_request, approve_bad_transfer, dispatch_bad_transfer, receive_bad_transfer,
    _get_or_create_bad_stock_row,
    BadProductError,
)
from tests.conftest import assert_normal_stock_unchanged


def _bad_qty(location_id, product_id):
    row = BadProductStock.query.filter_by(location_id=location_id, product_id=product_id).first()
    return row.quantity if row else 0


def _login(client, username, password="password123"):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=True)


# ---------------------------------------------------------------------------
# TEST 1 & TEST 2 — Bad Recovery does not touch normal stock / StockMovement
# ---------------------------------------------------------------------------

def test_recovery_approval_does_not_modify_normal_stock(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    assert_normal_stock_unchanged(seed["loc_a"], seed["product"], 20)
    assert _bad_qty(seed["loc_a"], seed["product"]) == 0

    recovery = create_recovery_request(
        seed["loc_a"], [(seed["product"], 2)], seed["emp_user"],
        service_reference="JOB-1", recovery_date=date.today(),
    )
    db.session.commit()
    # Not yet approved: nothing should have moved.
    assert_normal_stock_unchanged(seed["loc_a"], seed["product"], 20)

    approve_recovery(recovery.id, seed["mgr"], approve=True)
    db.session.commit()

    assert_normal_stock_unchanged(seed["loc_a"], seed["product"], 20)  # <-- the critical assertion
    assert _bad_qty(seed["loc_a"], seed["product"]) == 2


def test_recovery_approval_does_not_create_stock_movement(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()

    recovery = create_recovery_request(
        seed["loc_a"], [(seed["product"], 2)], seed["emp_user"],
        service_reference="JOB-2", recovery_date=date.today(),
    )
    db.session.commit()

    sm_count_before = StockMovement.query.count()
    approve_recovery(recovery.id, seed["mgr"], approve=True)
    db.session.commit()
    sm_count_after = StockMovement.query.count()

    assert sm_count_after == sm_count_before, "Approving a Bad Product Recovery must never create a StockMovement row"
    assert StockMovement.query.filter_by(reference_type="BAD_RECOVERY").count() == 0

    bpm = BadProductMovement.query.filter_by(reference_type="BAD_RECOVERY", reference_id=recovery.id).all()
    assert len(bpm) == 1
    assert bpm[0].quantity_change == 2
    assert bpm[0].movement_type == "BAD_RECOVERY_APPROVED"


# ---------------------------------------------------------------------------
# TEST 3, 4 & 5 — Bad Transfer OUT/IN does not touch normal stock / StockMovement
# ---------------------------------------------------------------------------

def _seed_bad_stock(seed, location_id, quantity):
    """Helper: get BadProductStock to `quantity` via an approved recovery (exercises real code path)."""
    if quantity <= 0:
        return
    recovery = create_recovery_request(
        location_id, [(seed["product"], quantity)], seed["emp_user"],
        service_reference="SEED", recovery_date=date.today(),
    )
    db.session.commit()
    approve_recovery(recovery.id, seed["mgr"], approve=True)
    db.session.commit()


def test_transfer_dispatch_does_not_modify_normal_stock(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    receive_stock(seed["loc_b"], [(seed["product"], 30)], seed["admin"])
    db.session.commit()
    _seed_bad_stock(seed, seed["loc_a"], 5)
    _seed_bad_stock(seed, seed["loc_b"], 1)

    assert_normal_stock_unchanged(seed["loc_a"], seed["product"], 20)
    assert_normal_stock_unchanged(seed["loc_b"], seed["product"], 30)
    assert _bad_qty(seed["loc_a"], seed["product"]) == 5
    assert _bad_qty(seed["loc_b"], seed["product"]) == 1

    transfer = create_bad_transfer_request(seed["loc_a"], seed["loc_b"], [(seed["product"], 2)], seed["mgr"])
    db.session.commit()
    approve_bad_transfer(transfer.id, seed["admin"], approve=True)
    db.session.commit()
    dispatch_bad_transfer(transfer.id, seed["mgr"])
    db.session.commit()

    assert_normal_stock_unchanged(seed["loc_a"], seed["product"], 20)
    assert_normal_stock_unchanged(seed["loc_b"], seed["product"], 30)
    assert _bad_qty(seed["loc_a"], seed["product"]) == 3
    assert _bad_qty(seed["loc_b"], seed["product"]) == 1  # unchanged until received


def test_transfer_receive_does_not_modify_normal_stock(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    receive_stock(seed["loc_b"], [(seed["product"], 30)], seed["admin"])
    db.session.commit()
    _seed_bad_stock(seed, seed["loc_a"], 5)
    _seed_bad_stock(seed, seed["loc_b"], 1)

    transfer = create_bad_transfer_request(seed["loc_a"], seed["loc_b"], [(seed["product"], 2)], seed["mgr"])
    db.session.commit()
    approve_bad_transfer(transfer.id, seed["admin"], approve=True)
    db.session.commit()
    dispatch_bad_transfer(transfer.id, seed["mgr"])
    db.session.commit()
    receive_bad_transfer(transfer.id, seed["mgr"])
    db.session.commit()

    assert_normal_stock_unchanged(seed["loc_a"], seed["product"], 20)
    assert_normal_stock_unchanged(seed["loc_b"], seed["product"], 30)
    assert _bad_qty(seed["loc_a"], seed["product"]) == 3
    assert _bad_qty(seed["loc_b"], seed["product"]) == 3

    refetched = db.session.get(BadProductTransfer, transfer.id)
    assert refetched.status == "COMPLETED"


def test_transfer_does_not_create_stock_movement(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    receive_stock(seed["loc_b"], [(seed["product"], 30)], seed["admin"])
    db.session.commit()
    _seed_bad_stock(seed, seed["loc_a"], 5)
    _seed_bad_stock(seed, seed["loc_b"], 1)

    sm_count_before = StockMovement.query.count()

    transfer = create_bad_transfer_request(seed["loc_a"], seed["loc_b"], [(seed["product"], 2)], seed["mgr"])
    db.session.commit()
    approve_bad_transfer(transfer.id, seed["admin"], approve=True)
    db.session.commit()
    dispatch_bad_transfer(transfer.id, seed["mgr"])
    db.session.commit()
    receive_bad_transfer(transfer.id, seed["mgr"])
    db.session.commit()

    sm_count_after = StockMovement.query.count()
    assert sm_count_after == sm_count_before, "Bad Product Transfer dispatch/receive must never create StockMovement rows"

    out_moves = BadProductMovement.query.filter_by(reference_type="BAD_TRANSFER", reference_id=transfer.id,
                                                     movement_type="BAD_TRANSFER_OUT").all()
    in_moves = BadProductMovement.query.filter_by(reference_type="BAD_TRANSFER", reference_id=transfer.id,
                                                   movement_type="BAD_TRANSFER_IN").all()
    assert len(out_moves) == 1 and out_moves[0].quantity_change == -2
    assert len(in_moves) == 1 and in_moves[0].quantity_change == 2


# ---------------------------------------------------------------------------
# TEST 6 — Rejected recovery changes nothing
# ---------------------------------------------------------------------------

def test_rejected_recovery_changes_nothing(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    sm_count_before = StockMovement.query.count()

    recovery = create_recovery_request(
        seed["loc_a"], [(seed["product"], 2)], seed["emp_user"],
        service_reference="JOB-REJ", recovery_date=date.today(),
    )
    db.session.commit()
    approve_recovery(recovery.id, seed["mgr"], approve=False)
    db.session.commit()

    assert_normal_stock_unchanged(seed["loc_a"], seed["product"], 20)
    assert _bad_qty(seed["loc_a"], seed["product"]) == 0
    assert StockMovement.query.count() == sm_count_before
    assert BadProductMovement.query.count() == 0
    assert db.session.get(BadProductRecovery, recovery.id).status == "REJECTED"


# ---------------------------------------------------------------------------
# TEST 7 — Insufficient bad stock
# ---------------------------------------------------------------------------

def test_insufficient_bad_stock_transfer_fails(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    _seed_bad_stock(seed, seed["loc_a"], 2)
    sm_count_before = StockMovement.query.count()
    bpm_count_before = BadProductMovement.query.count()

    with pytest.raises(BadProductError):
        create_bad_transfer_request(seed["loc_a"], seed["loc_b"], [(seed["product"], 3)], seed["mgr"])
    db.session.rollback()

    assert _bad_qty(seed["loc_a"], seed["product"]) == 2
    assert_normal_stock_unchanged(seed["loc_a"], seed["product"], 20)
    assert StockMovement.query.count() == sm_count_before
    assert BadProductMovement.query.count() == bpm_count_before
    assert BadProductTransfer.query.count() == 0


# ---------------------------------------------------------------------------
# TEST 8 — Double dispatch
# ---------------------------------------------------------------------------

def test_double_dispatch_fails(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    _seed_bad_stock(seed, seed["loc_a"], 5)

    transfer = create_bad_transfer_request(seed["loc_a"], seed["loc_b"], [(seed["product"], 2)], seed["mgr"])
    db.session.commit()
    approve_bad_transfer(transfer.id, seed["admin"], approve=True)
    db.session.commit()
    dispatch_bad_transfer(transfer.id, seed["mgr"])
    db.session.commit()

    assert _bad_qty(seed["loc_a"], seed["product"]) == 3

    with pytest.raises(BadProductError):
        dispatch_bad_transfer(transfer.id, seed["mgr"])
    db.session.rollback()

    # Stock must only have been reduced once.
    assert _bad_qty(seed["loc_a"], seed["product"]) == 3
    assert_normal_stock_unchanged(seed["loc_a"], seed["product"], 20)


# ---------------------------------------------------------------------------
# TEST 9 — Double receive
# ---------------------------------------------------------------------------

def test_double_receive_fails(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    receive_stock(seed["loc_b"], [(seed["product"], 30)], seed["admin"])
    db.session.commit()
    _seed_bad_stock(seed, seed["loc_a"], 5)

    transfer = create_bad_transfer_request(seed["loc_a"], seed["loc_b"], [(seed["product"], 2)], seed["mgr"])
    db.session.commit()
    approve_bad_transfer(transfer.id, seed["admin"], approve=True)
    db.session.commit()
    dispatch_bad_transfer(transfer.id, seed["mgr"])
    db.session.commit()
    receive_bad_transfer(transfer.id, seed["mgr"])
    db.session.commit()

    assert _bad_qty(seed["loc_b"], seed["product"]) == 2

    with pytest.raises(BadProductError):
        receive_bad_transfer(transfer.id, seed["mgr"])
    db.session.rollback()

    # Destination BadProductStock must only have increased once.
    assert _bad_qty(seed["loc_b"], seed["product"]) == 2
    assert_normal_stock_unchanged(seed["loc_b"], seed["product"], 30)


# ---------------------------------------------------------------------------
# TEST 10 — Double approval (recovery)
# ---------------------------------------------------------------------------

def test_double_approval_recovery_fails(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()

    recovery = create_recovery_request(
        seed["loc_a"], [(seed["product"], 2)], seed["emp_user"],
        service_reference="JOB-DBL", recovery_date=date.today(),
    )
    db.session.commit()
    approve_recovery(recovery.id, seed["mgr"], approve=True)
    db.session.commit()
    assert _bad_qty(seed["loc_a"], seed["product"]) == 2

    with pytest.raises(BadProductError):
        approve_recovery(recovery.id, seed["mgr"], approve=True)
    db.session.rollback()

    assert _bad_qty(seed["loc_a"], seed["product"]) == 2  # no duplicate stock movement
    assert_normal_stock_unchanged(seed["loc_a"], seed["product"], 20)
    assert BadProductMovement.query.filter_by(reference_type="BAD_RECOVERY", reference_id=recovery.id).count() == 1


def test_double_approval_transfer_fails(app, db, seed):
    receive_stock(seed["loc_a"], [(seed["product"], 20)], seed["admin"])
    db.session.commit()
    _seed_bad_stock(seed, seed["loc_a"], 5)

    transfer = create_bad_transfer_request(seed["loc_a"], seed["loc_b"], [(seed["product"], 2)], seed["mgr"])
    db.session.commit()
    approve_bad_transfer(transfer.id, seed["admin"], approve=True)
    db.session.commit()

    with pytest.raises(BadProductError):
        approve_bad_transfer(transfer.id, seed["admin"], approve=True)
    db.session.rollback()

    assert db.session.get(BadProductTransfer, transfer.id).status == "APPROVED"


# ---------------------------------------------------------------------------
# TEST 11 — Location security: employee cannot create a recovery for another location
# ---------------------------------------------------------------------------

def test_employee_cannot_create_recovery_for_other_location(app, db, client, seed):
    """The server must derive the recovery's location from the employee's OWN assigned
    location - it must never trust a client-supplied location_id. There is no location
    field on the recovery form at all; this test proves that even a raw POST including a
    forged `location_id` field is ignored."""
    _login(client, "emp1")
    resp = client.post("/bad-products/recoveries/new", data={
        "product_id": str(seed["product"]), "quantity": "1",
        "service_reference": "JOB-HACK", "recovery_date": "2026-01-01",
        "location_id": str(seed["loc_b"]),  # forged/irrelevant field - route must ignore it
    }, follow_redirects=True)
    assert resp.status_code == 200

    recovery = BadProductRecovery.query.filter_by(service_reference="JOB-HACK").first()
    assert recovery is not None
    assert recovery.location_id == seed["loc_a"], (
        "Recovery location must always be the employee's OWN assigned location "
        "(Location A for emp1), never a client-supplied value."
    )
    assert recovery.location_id != seed["loc_b"]


def test_employee_cannot_view_another_employees_recovery(app, db, client, seed):
    _login(client, "emp1")
    client.post("/bad-products/recoveries/new", data={
        "product_id": str(seed["product"]), "quantity": "1",
        "service_reference": "JOB-PRIVATE", "recovery_date": "2026-01-01",
    }, follow_redirects=True)
    recovery = BadProductRecovery.query.filter_by(service_reference="JOB-PRIVATE").first()
    client.get("/logout")

    _login(client, "emp2")
    resp = client.get(f"/bad-products/recoveries/{recovery.id}")
    assert resp.status_code == 403


def test_employee_cannot_approve_recovery(app, db, client, seed):
    _login(client, "emp1")
    client.post("/bad-products/recoveries/new", data={
        "product_id": str(seed["product"]), "quantity": "1",
        "service_reference": "JOB-NOAPPROVE", "recovery_date": "2026-01-01",
    }, follow_redirects=True)
    recovery = BadProductRecovery.query.filter_by(service_reference="JOB-NOAPPROVE").first()

    resp = client.post(f"/bad-products/recoveries/{recovery.id}/approve", data={})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Fix 6 — concurrency-safe first BadProductStock row creation
# ---------------------------------------------------------------------------

def test_bad_product_stock_unique_constraint_is_enforced_at_db_level(app, db, seed):
    """The safety net Fix 6 relies on: the DB itself refuses a second row for the same
    (location_id, product_id) pair, regardless of application-level races."""
    row1 = BadProductStock(location_id=seed["loc_a"], product_id=seed["product"], quantity=0)
    db.session.add(row1)
    db.session.commit()

    row2 = BadProductStock(location_id=seed["loc_a"], product_id=seed["product"], quantity=0)
    db.session.add(row2)
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_get_or_create_bad_stock_row_reuses_existing_row(app, db, seed):
    row = _get_or_create_bad_stock_row(seed["loc_a"], seed["product"])
    row.quantity = 9
    db.session.commit()

    row_again = _get_or_create_bad_stock_row(seed["loc_a"], seed["product"])
    assert row_again.id == row.id
    assert row_again.quantity == 9
    assert BadProductStock.query.filter_by(location_id=seed["loc_a"], product_id=seed["product"]).count() == 1
