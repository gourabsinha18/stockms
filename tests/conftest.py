"""
Shared pytest fixtures for the Bad Product module test suite (Fix 3).

Each test gets a fresh Flask app bound to a brand-new in-memory SQLite
database (created via db.create_all() and torn down via db.drop_all()), so
tests never touch the real stockms.db and never leak state between tests.
"""
import pytest
from sqlalchemy.pool import StaticPool

from app import create_app
from app.extensions import db as _db
from config import Config


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }
    RATELIMIT_ENABLED = False


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def seed(app, db):
    """A minimal baseline: two locations, one Main Admin, one Stock Manager (assigned to
    both locations), one Employee (assigned to Location A), and one product."""
    from app.models import (
        User, Location, Unit, Brand, Category, Product, Employee, StockManagerAssignment,
        ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER, ROLE_EMPLOYEE,
    )

    loc_a = Location(code="LOC-A", name="Location A")
    loc_b = Location(code="LOC-B", name="Location B")
    db.session.add_all([loc_a, loc_b])
    db.session.flush()

    admin = User(username="admin1", email="admin1@example.com", full_name="Admin One", role=ROLE_MAIN_ADMIN)
    admin.set_password("password123")
    mgr = User(username="mgr1", email="mgr1@example.com", full_name="Manager One", role=ROLE_STOCK_MANAGER)
    mgr.set_password("password123")
    emp_user = User(username="emp1", email="emp1@example.com", full_name="Employee One", role=ROLE_EMPLOYEE)
    emp_user.set_password("password123")
    emp_user2 = User(username="emp2", email="emp2@example.com", full_name="Employee Two", role=ROLE_EMPLOYEE)
    emp_user2.set_password("password123")
    db.session.add_all([admin, mgr, emp_user, emp_user2])
    db.session.flush()

    db.session.add(StockManagerAssignment(user_id=mgr.id, location_id=loc_a.id))
    db.session.add(StockManagerAssignment(user_id=mgr.id, location_id=loc_b.id))
    emp = Employee(employee_code="EMP0001", user_id=emp_user.id, location_id=loc_a.id)
    emp2 = Employee(employee_code="EMP0002", user_id=emp_user2.id, location_id=loc_b.id)
    db.session.add_all([emp, emp2])
    db.session.flush()

    unit = Unit(code="U1", name="Unit 1")
    db.session.add(unit)
    db.session.flush()
    brand = Brand(unit_id=unit.id, code="BR1", name="Brand 1")
    db.session.add(brand)
    db.session.flush()
    category = Category(brand_id=brand.id, code="CAT1", name="Category 1")
    db.session.add(category)
    db.session.flush()
    product = Product(sku="ABC-001", name="Product A", category_id=category.id)
    db.session.add(product)
    db.session.flush()

    db.session.commit()

    return {
        "loc_a": loc_a.id,
        "loc_b": loc_b.id,
        "admin": admin.id,
        "mgr": mgr.id,
        "emp_user": emp_user.id,
        "emp_user2": emp_user2.id,
        "emp": emp.id,
        "emp2": emp2.id,
        "product": product.id,
    }


def assert_normal_stock_unchanged(location_id, product_id, expected_quantity):
    """Reusable assertion (Fix 3 / spec Test 12) documenting the core invariant under test:

        BAD PRODUCT OPERATIONS MUST NEVER CHANGE LocationStock.

    Call this after every Bad Product Recovery / Transfer operation with the quantity that
    was present in LocationStock BEFORE the bad-product operation ran.
    """
    from app.models import LocationStock
    row = LocationStock.query.filter_by(location_id=location_id, product_id=product_id).first()
    actual = row.quantity if row else 0
    assert actual == expected_quantity, (
        f"NORMAL STOCK SEPARATION VIOLATED: LocationStock for product {product_id} at location "
        f"{location_id} is {actual}, expected it to remain {expected_quantity}. A Bad Product "
        f"operation must never read from or write to LocationStock."
    )
