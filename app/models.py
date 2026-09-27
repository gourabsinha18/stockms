from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

# ---------------------------------------------------------------------------
# Constants / enums (stored as plain strings for SQLite portability)
# ---------------------------------------------------------------------------

ROLE_MAIN_ADMIN = "MAIN_ADMIN"
ROLE_STOCK_MANAGER = "STOCK_MANAGER"
ROLE_EMPLOYEE = "EMPLOYEE"
ROLES = [ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER, ROLE_EMPLOYEE]

STATUS_DRAFT = "DRAFT"
STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_PROCESSING = "PROCESSING"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"

MOVEMENT_STOCK_IN = "STOCK_IN"
MOVEMENT_TRANSFER_OUT = "TRANSFER_OUT"
MOVEMENT_TRANSFER_IN = "TRANSFER_IN"
MOVEMENT_ADJUSTMENT_IN = "ADJUSTMENT_IN"
MOVEMENT_ADJUSTMENT_OUT = "ADJUSTMENT_OUT"
MOVEMENT_RETURN_OUT = "RETURN_OUT"
MOVEMENT_RETURN_IN = "RETURN_IN"

REQUEST_TYPE_TRANSFER = "TRANSFER"
REQUEST_TYPE_ADJUSTMENT = "ADJUSTMENT"
REQUEST_TYPE_RETURN = "RETURN"
REQUEST_TYPE_STOCK_IN = "STOCK_IN"

# ---------------------------------------------------------------------------
# Bad Product Recovery / Bad Products module constants
#
# This is a completely separate inventory category from normal stock
# (LocationStock / StockMovement). Nothing in this module ever reads from or
# writes to LocationStock / StockMovement, and nothing in the normal stock
# code paths reads from or writes to the Bad Product tables below.
# ---------------------------------------------------------------------------

BAD_RECOVERY_STATUS_PENDING = "PENDING"
BAD_RECOVERY_STATUS_REJECTED = "REJECTED"
BAD_RECOVERY_STATUS_COMPLETED = "COMPLETED"

# Bad Product Transfer workflow. RECEIVED is represented as COMPLETED with
# received_at populated, mirroring how the existing StockTransfer collapses
# "received" straight into COMPLETED rather than keeping a separate
# persisted state.
BAD_TRANSFER_STATUS_REQUESTED = "REQUESTED"
BAD_TRANSFER_STATUS_APPROVED = "APPROVED"
BAD_TRANSFER_STATUS_DISPATCHED = "DISPATCHED"
BAD_TRANSFER_STATUS_COMPLETED = "COMPLETED"
BAD_TRANSFER_STATUS_REJECTED = "REJECTED"
BAD_TRANSFER_STATUS_CANCELLED = "CANCELLED"

MOVEMENT_BAD_RECOVERY_APPROVED = "BAD_RECOVERY_APPROVED"
MOVEMENT_BAD_TRANSFER_OUT = "BAD_TRANSFER_OUT"
MOVEMENT_BAD_TRANSFER_IN = "BAD_TRANSFER_IN"

REQUEST_TYPE_BAD_RECOVERY = "BAD_RECOVERY"
REQUEST_TYPE_BAD_TRANSFER = "BAD_TRANSFER"

# ---------------------------------------------------------------------------
# Employee Stock Issue & Return module constants
#
# Employee stock is a THIRD independent quantity bucket (alongside normal
# LocationStock and BadProductStock): stock that has been handed to a named
# employee and is their personal accountability until it is returned.
# ---------------------------------------------------------------------------

EMP_TXN_ISSUE = "ISSUE"
EMP_TXN_GOOD_RETURN = "GOOD_RETURN"
EMP_TXN_BAD_RETURN = "BAD_RETURN"

EMP_RETURN_STATUS_PENDING = "PENDING"
EMP_RETURN_STATUS_APPROVED_GOOD = "APPROVED_GOOD"
EMP_RETURN_STATUS_APPROVED_BAD = "APPROVED_BAD"
EMP_RETURN_STATUS_REJECTED = "REJECTED"

EMP_CONDITION_GOOD = "GOOD"
EMP_CONDITION_BAD = "BAD"

REQUEST_TYPE_EMPLOYEE_RETURN = "EMPLOYEE_RETURN"

# Normal-stock ledger movement types used when stock crosses the
# LocationStock <-> Employee boundary (still recorded in the existing,
# single StockMovement ledger - reusing it, not duplicating it).
MOVEMENT_EMPLOYEE_ISSUE = "EMPLOYEE_ISSUE"              # LocationStock -> Employee
MOVEMENT_EMPLOYEE_RETURN_GOOD = "EMPLOYEE_RETURN_GOOD"  # Employee -> LocationStock

# Bad-product ledger movement type used when an employee return is classified
# BAD by the Stock Manager. Recorded in the existing BadProductMovement
# ledger (reusing app.services.bad_product_service._apply_bad_movement),
# never in a second/parallel bad-stock system.
MOVEMENT_BAD_EMPLOYEE_RETURN = "BAD_EMPLOYEE_RETURN"


def gen_code(prefix):
    """Human readable reference code e.g. TRF-20260819-0001 (uniqueness enforced by caller)."""
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"


def gen_employee_code():
    """Short sequential code like EMP0001, EMP0002, ... based on the current employee count.
    Collisions (e.g. two simultaneous creations) are handled by the caller retrying against the
    table's unique constraint, exactly like the Bad Product module's row-creation race handling."""
    count = Employee.query.count()
    return f"EMP{count + 1:04d}"


# ---------------------------------------------------------------------------
# Users / Roles / Locations / Employees
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_EMPLOYEE)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)

    manager_assignments = db.relationship(
        "StockManagerAssignment", back_populates="user", foreign_keys="StockManagerAssignment.user_id"
    )
    employee_profile = db.relationship(
        "Employee", back_populates="user", uselist=False, foreign_keys="Employee.user_id"
    )

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def is_main_admin(self):
        return self.role == ROLE_MAIN_ADMIN

    def is_stock_manager(self):
        return self.role == ROLE_STOCK_MANAGER

    def is_employee(self):
        return self.role == ROLE_EMPLOYEE

    def authorized_location_ids(self):
        """Locations this user is allowed to act on. Main Admin -> all (handled by caller)."""
        if self.role == ROLE_STOCK_MANAGER:
            return [a.location_id for a in self.manager_assignments if a.is_active]
        if self.role == ROLE_EMPLOYEE and self.employee_profile:
            return [self.employee_profile.location_id]
        return []

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class Location(db.Model):
    __tablename__ = "locations"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    manager_assignments = db.relationship("StockManagerAssignment", back_populates="location")
    employees = db.relationship("Employee", back_populates="location")

    def __repr__(self):
        return f"<Location {self.code}>"


class StockManagerAssignment(db.Model):
    """Links a STOCK_MANAGER user to one or more locations they are authorized for."""
    __tablename__ = "stock_managers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship("User", back_populates="manager_assignments", foreign_keys=[user_id])
    location = db.relationship("Location", back_populates="manager_assignments")

    __table_args__ = (db.UniqueConstraint("user_id", "location_id", name="uq_manager_location"),)


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    employee_code = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    stock_manager_id = db.Column(db.Integer, db.ForeignKey("users.id"))  # supervising manager
    phone = db.Column(db.String(20))
    designation = db.Column(db.String(100))
    department = db.Column(db.String(100))
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="employee_profile", foreign_keys=[user_id])
    location = db.relationship("Location", back_populates="employees")
    stock_manager = db.relationship("User", foreign_keys=[stock_manager_id])


# ---------------------------------------------------------------------------
# Product hierarchy: Unit -> Company/Brand -> Category -> Product
# ---------------------------------------------------------------------------

class Unit(db.Model):
    __tablename__ = "units"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    brands = db.relationship("Brand", back_populates="unit")


class Brand(db.Model):
    __tablename__ = "brands"

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=False)
    code = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    unit = db.relationship("Unit", back_populates="brands")
    categories = db.relationship("Category", back_populates="brand")

    __table_args__ = (db.UniqueConstraint("unit_id", "code", name="uq_brand_code_per_unit"),)


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"), nullable=False)
    code = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    brand = db.relationship("Brand", back_populates="categories")
    products = db.relationship("Product", back_populates="category")

    __table_args__ = (db.UniqueConstraint("brand_id", "code", name="uq_category_code_per_brand"),)


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    model = db.Column(db.String(80))
    description = db.Column(db.Text)
    min_stock_level = db.Column(db.Integer, default=0, nullable=False)
    reorder_level = db.Column(db.Integer, default=0, nullable=False)
    cost_price = db.Column(db.Numeric(12, 2))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = db.relationship("Category", back_populates="products")
    stock_entries = db.relationship("LocationStock", back_populates="product")

    @property
    def brand(self):
        return self.category.brand if self.category else None

    @property
    def unit(self):
        return self.category.brand.unit if self.category and self.category.brand else None


# ---------------------------------------------------------------------------
# Stock quantities + ledger
# ---------------------------------------------------------------------------

class LocationStock(db.Model):
    """Current on-hand quantity of a product at a location. Never edit directly outside StockService."""
    __tablename__ = "location_stock"

    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, default=0, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    location = db.relationship("Location")
    product = db.relationship("Product", back_populates="stock_entries")

    __table_args__ = (
        db.UniqueConstraint("location_id", "product_id", name="uq_location_product"),
        db.CheckConstraint("quantity >= 0", name="ck_location_stock_non_negative"),
    )


class StockMovement(db.Model):
    """Immutable ledger. Every quantity change anywhere in the system creates exactly one row here."""
    __tablename__ = "stock_movements"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    movement_type = db.Column(db.String(20), nullable=False)
    qty_before = db.Column(db.Integer, nullable=False)
    qty_change = db.Column(db.Integer, nullable=False)  # signed: + for in, - for out
    qty_after = db.Column(db.Integer, nullable=False)
    reference_type = db.Column(db.String(20))  # TRANSFER / ADJUSTMENT / RETURN / STOCK_IN
    reference_id = db.Column(db.Integer)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.String(255))
    remarks = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    product = db.relationship("Product")
    location = db.relationship("Location")
    user = db.relationship("User")


# ---------------------------------------------------------------------------
# Stock In / Receiving
# ---------------------------------------------------------------------------

class StockReceipt(db.Model):
    __tablename__ = "stock_receipts"

    id = db.Column(db.Integer, primary_key=True)
    receipt_code = db.Column(db.String(40), unique=True, nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    supplier_source = db.Column(db.String(150))
    reference_number = db.Column(db.String(80))
    status = db.Column(db.String(20), default=STATUS_COMPLETED, nullable=False)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    remarks = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    location = db.relationship("Location")
    receiver = db.relationship("User")
    items = db.relationship("StockReceiptItem", back_populates="receipt", cascade="all, delete-orphan")


class StockReceiptItem(db.Model):
    __tablename__ = "stock_receipt_items"

    id = db.Column(db.Integer, primary_key=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey("stock_receipts.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    receipt = db.relationship("StockReceipt", back_populates="items")
    product = db.relationship("Product")

    __table_args__ = (db.CheckConstraint("quantity > 0", name="ck_receipt_item_qty_positive"),)


# ---------------------------------------------------------------------------
# Stock Transfer
# ---------------------------------------------------------------------------

class StockTransfer(db.Model):
    __tablename__ = "stock_transfers"

    id = db.Column(db.Integer, primary_key=True)
    transfer_code = db.Column(db.String(40), unique=True, nullable=False)
    source_location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    dest_location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    status = db.Column(db.String(20), default=STATUS_DRAFT, nullable=False)

    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime)
    dispatched_at = db.Column(db.DateTime)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    received_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    remarks = db.Column(db.String(255))

    source_location = db.relationship("Location", foreign_keys=[source_location_id])
    dest_location = db.relationship("Location", foreign_keys=[dest_location_id])
    requester = db.relationship("User", foreign_keys=[requested_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    receiver = db.relationship("User", foreign_keys=[received_by])
    items = db.relationship("StockTransferItem", back_populates="transfer", cascade="all, delete-orphan")

    __table_args__ = (
        db.CheckConstraint("source_location_id != dest_location_id", name="ck_transfer_diff_locations"),
    )


class StockTransferItem(db.Model):
    __tablename__ = "stock_transfer_items"

    id = db.Column(db.Integer, primary_key=True)
    transfer_id = db.Column(db.Integer, db.ForeignKey("stock_transfers.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    transfer = db.relationship("StockTransfer", back_populates="items")
    product = db.relationship("Product")

    __table_args__ = (db.CheckConstraint("quantity > 0", name="ck_transfer_item_qty_positive"),)


# ---------------------------------------------------------------------------
# Stock Adjustment
# ---------------------------------------------------------------------------

class StockAdjustment(db.Model):
    __tablename__ = "stock_adjustments"

    id = db.Column(db.Integer, primary_key=True)
    adjustment_code = db.Column(db.String(40), unique=True, nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)

    previous_qty = db.Column(db.Integer, nullable=False)
    adjustment_qty = db.Column(db.Integer, nullable=False)  # signed
    new_qty = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default=STATUS_PENDING_APPROVAL, nullable=False)

    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime)
    remarks = db.Column(db.String(255))

    location = db.relationship("Location")
    product = db.relationship("Product")
    requester = db.relationship("User", foreign_keys=[requested_by])
    approver = db.relationship("User", foreign_keys=[approved_by])


# ---------------------------------------------------------------------------
# Stock Return
# ---------------------------------------------------------------------------

class StockReturn(db.Model):
    __tablename__ = "stock_returns"

    id = db.Column(db.Integer, primary_key=True)
    return_code = db.Column(db.String(40), unique=True, nullable=False)
    source_location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    dest_location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)  # configurable, e.g. Bolpur HQ
    status = db.Column(db.String(20), default=STATUS_PENDING_APPROVAL, nullable=False)
    reason = db.Column(db.String(255), nullable=False)

    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)

    sm_approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    sm_approved_at = db.Column(db.DateTime)

    admin_approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    admin_approved_at = db.Column(db.DateTime)

    completed_at = db.Column(db.DateTime)
    remarks = db.Column(db.String(255))

    source_location = db.relationship("Location", foreign_keys=[source_location_id])
    dest_location = db.relationship("Location", foreign_keys=[dest_location_id])
    requester = db.relationship("User", foreign_keys=[requested_by])
    sm_approver = db.relationship("User", foreign_keys=[sm_approved_by])
    admin_approver = db.relationship("User", foreign_keys=[admin_approved_by])
    items = db.relationship("StockReturnItem", back_populates="stock_return", cascade="all, delete-orphan")


class StockReturnItem(db.Model):
    __tablename__ = "stock_return_items"

    id = db.Column(db.Integer, primary_key=True)
    return_id = db.Column(db.Integer, db.ForeignKey("stock_returns.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    stock_return = db.relationship("StockReturn", back_populates="items")
    product = db.relationship("Product")

    __table_args__ = (db.CheckConstraint("quantity > 0", name="ck_return_item_qty_positive"),)


# ---------------------------------------------------------------------------
# Generic approval log (audit trail specific to the approval engine)
# ---------------------------------------------------------------------------

class ApprovalLog(db.Model):
    __tablename__ = "approvals"

    id = db.Column(db.Integer, primary_key=True)
    request_type = db.Column(db.String(20), nullable=False)  # TRANSFER / ADJUSTMENT / RETURN / STOCK_IN
    request_id = db.Column(db.Integer, nullable=False)
    previous_status = db.Column(db.String(20))
    new_status = db.Column(db.String(20), nullable=False)
    action_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action_at = db.Column(db.DateTime, default=datetime.utcnow)
    comment = db.Column(db.String(255))

    actor = db.relationship("User")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    link = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")


# ---------------------------------------------------------------------------
# Bad Product Recovery / Bad Products module
#
# Deliberately independent from LocationStock / StockMovement. There is no
# relationship, join, or computed property anywhere that adds bad-product
# quantity into normal/available stock.
# ---------------------------------------------------------------------------

class BadProductStock(db.Model):
    """Current on-hand BAD (defective/recovered) quantity of a product at a location.
    Completely independent of LocationStock. Never edit directly outside bad_product_service."""
    __tablename__ = "bad_product_stock"

    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    location = db.relationship("Location")
    product = db.relationship("Product")

    __table_args__ = (
        db.UniqueConstraint("location_id", "product_id", name="uq_bad_product_location_product"),
        db.CheckConstraint("quantity >= 0", name="ck_bad_product_stock_non_negative"),
    )


class BadProductMovement(db.Model):
    """Immutable ledger for bad-product stock changes only. Never written alongside StockMovement,
    and normal StockMovement rows are never created for bad-product operations."""
    __tablename__ = "bad_product_movements"

    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    movement_type = db.Column(db.String(30), nullable=False)
    quantity_before = db.Column(db.Integer, nullable=False)
    quantity_change = db.Column(db.Integer, nullable=False)  # signed: + for in, - for out
    quantity_after = db.Column(db.Integer, nullable=False)
    reference_type = db.Column(db.String(20))  # BAD_RECOVERY / BAD_TRANSFER
    reference_id = db.Column(db.Integer)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    remarks = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    location = db.relationship("Location")
    product = db.relationship("Product")
    user = db.relationship("User")


class BadProductRecovery(db.Model):
    """Employee-submitted recovery of a bad/defective product from a customer visit.
    Deliberately has no Condition / Repair Status / Customer fields (by explicit requirement)."""
    __tablename__ = "bad_product_recoveries"

    id = db.Column(db.Integer, primary_key=True)
    recovery_code = db.Column(db.String(40), unique=True, nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)

    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)

    service_reference = db.Column(db.String(120), nullable=False)
    recovery_date = db.Column(db.Date, nullable=False)
    remarks = db.Column(db.String(255))

    status = db.Column(db.String(20), default=BAD_RECOVERY_STATUS_PENDING, nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    location = db.relationship("Location")
    requester = db.relationship("User", foreign_keys=[requested_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    items = db.relationship("BadProductRecoveryItem", back_populates="recovery", cascade="all, delete-orphan")


class BadProductRecoveryItem(db.Model):
    __tablename__ = "bad_product_recovery_items"

    id = db.Column(db.Integer, primary_key=True)
    recovery_id = db.Column(db.Integer, db.ForeignKey("bad_product_recoveries.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    recovery = db.relationship("BadProductRecovery", back_populates="items")
    product = db.relationship("Product")

    __table_args__ = (db.CheckConstraint("quantity > 0", name="ck_bad_recovery_item_qty_positive"),)


class BadProductTransfer(db.Model):
    """Transfer of BadProductStock between locations. Operates ONLY on bad-product stock;
    never touches LocationStock and never calls the normal StockTransfer service."""
    __tablename__ = "bad_product_transfers"

    id = db.Column(db.Integer, primary_key=True)
    transfer_code = db.Column(db.String(40), unique=True, nullable=False)
    source_location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    dest_location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    status = db.Column(db.String(20), default=BAD_TRANSFER_STATUS_REQUESTED, nullable=False)

    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime)
    dispatched_at = db.Column(db.DateTime)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    received_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    remarks = db.Column(db.String(255))

    source_location = db.relationship("Location", foreign_keys=[source_location_id])
    dest_location = db.relationship("Location", foreign_keys=[dest_location_id])
    requester = db.relationship("User", foreign_keys=[requested_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    receiver = db.relationship("User", foreign_keys=[received_by])
    items = db.relationship("BadProductTransferItem", back_populates="transfer", cascade="all, delete-orphan")

    __table_args__ = (
        db.CheckConstraint("source_location_id != dest_location_id", name="ck_bad_transfer_diff_locations"),
    )


class BadProductTransferItem(db.Model):
    __tablename__ = "bad_product_transfer_items"

    id = db.Column(db.Integer, primary_key=True)
    transfer_id = db.Column(db.Integer, db.ForeignKey("bad_product_transfers.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    transfer = db.relationship("BadProductTransfer", back_populates="items")
    product = db.relationship("Product")

    __table_args__ = (db.CheckConstraint("quantity > 0", name="ck_bad_transfer_item_qty_positive"),)


# ---------------------------------------------------------------------------
# Employee Stock Issue & Return
#
# A THIRD independent inventory bucket. EmployeeStock is populated only by
# issue_stock_to_employee() (which decreases LocationStock) and drained only
# by an approved return (which increases LocationStock if GOOD, or increases
# BadProductStock if BAD). It never has its own parallel "movement into/out
# of nowhere" - every change is always mirrored by an equal-and-opposite
# change in exactly one of LocationStock or BadProductStock, and always goes
# through app.services.employee_stock_service.
# ---------------------------------------------------------------------------

class EmployeeStock(db.Model):
    """Current on-hand quantity of a product held by (issued to, not yet returned by) an employee."""
    __tablename__ = "employee_stock"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = db.relationship("Employee")
    product = db.relationship("Product")

    __table_args__ = (
        db.UniqueConstraint("employee_id", "product_id", name="uq_employee_stock_employee_product"),
        db.CheckConstraint("quantity >= 0", name="ck_employee_stock_non_negative"),
    )


class EmployeeStockTransaction(db.Model):
    """Immutable per-employee ledger. Every EmployeeStock quantity change writes exactly one row here -
    mirroring how StockMovement/BadProductMovement work for their respective inventories."""
    __tablename__ = "employee_stock_transactions"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # ISSUE / GOOD_RETURN / BAD_RETURN
    quantity_before = db.Column(db.Integer, nullable=False)
    quantity_change = db.Column(db.Integer, nullable=False)  # signed: + for issue, - for return
    quantity_after = db.Column(db.Integer, nullable=False)
    reference_type = db.Column(db.String(30))  # EMPLOYEE_ISSUE / EMPLOYEE_RETURN
    reference_id = db.Column(db.Integer)
    performed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    employee = db.relationship("Employee")
    product = db.relationship("Product")
    location = db.relationship("Location")
    performer = db.relationship("User")


class EmployeeReturnRequest(db.Model):
    """An employee's request to return previously-issued stock. `reported_condition` is only the
    employee's own report - it is NEVER used to decide where the stock ends up. Only the Stock
    Manager's decision (approve_return_as_good / approve_return_as_bad / reject_return) does that."""
    __tablename__ = "employee_return_requests"

    id = db.Column(db.Integer, primary_key=True)
    return_code = db.Column(db.String(40), unique=True, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    reported_condition = db.Column(db.String(10), nullable=False)  # employee's own report only (GOOD/BAD)
    reason = db.Column(db.String(255))
    status = db.Column(db.String(20), default=EMP_RETURN_STATUS_PENDING, nullable=False)

    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)
    manager_remarks = db.Column(db.String(255))
    completed_at = db.Column(db.DateTime)

    employee = db.relationship("Employee")
    product = db.relationship("Product")
    location = db.relationship("Location")
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

    __table_args__ = (db.CheckConstraint("quantity > 0", name="ck_employee_return_qty_positive"),)


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------

class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(50), nullable=False)  # CREATE / UPDATE / DELETE / LOGIN / LOGOUT / APPROVE / REJECT ...
    entity = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer)
    previous_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User")
