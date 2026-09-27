from flask import Blueprint, render_template
from flask_login import login_required, current_user
from sqlalchemy import func
from datetime import datetime
from app.extensions import db
from app.models import (
    Location, User, Employee, Product, LocationStock, StockMovement,
    StockTransfer, StockAdjustment, StockReturn,
    BadProductStock, BadProductRecovery,
    EmployeeStock, EmployeeReturnRequest, EmployeeStockTransaction,
    ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER,
    STATUS_PENDING_APPROVAL, STATUS_PROCESSING,
    BAD_RECOVERY_STATUS_PENDING,
    EMP_RETURN_STATUS_PENDING, EMP_RETURN_STATUS_APPROVED_GOOD, EMP_RETURN_STATUS_APPROVED_BAD,
    EMP_TXN_ISSUE, EMP_TXN_GOOD_RETURN, EMP_TXN_BAD_RETURN,
)
from app.services.permission_service import accessible_location_ids

bp = Blueprint("main", __name__)


@bp.route("/")
@bp.route("/dashboard")
@login_required
def dashboard():
    if current_user.is_main_admin():
        return _admin_dashboard()
    elif current_user.is_stock_manager():
        return _manager_dashboard()
    else:
        return _employee_dashboard()


def _admin_dashboard():
    total_locations = Location.query.filter_by(is_active=True).count()
    total_managers = User.query.filter_by(role=ROLE_STOCK_MANAGER, is_active=True).count()
    total_employees = Employee.query.filter_by(is_active=True).count()
    total_products = Product.query.filter_by(is_active=True).count()
    total_stock = db.session.query(func.coalesce(func.sum(LocationStock.quantity), 0)).scalar()

    low_stock = (
        db.session.query(LocationStock, Product, Location)
        .join(Product, LocationStock.product_id == Product.id)
        .join(Location, LocationStock.location_id == Location.id)
        .filter(LocationStock.quantity <= Product.reorder_level, Product.is_active == True)
        .limit(10).all()
    )

    pending_transfers = StockTransfer.query.filter_by(status=STATUS_PENDING_APPROVAL).count()
    pending_adjustments = StockAdjustment.query.filter_by(status=STATUS_PENDING_APPROVAL).count()
    pending_returns = StockReturn.query.filter(
        StockReturn.status.in_([STATUS_PENDING_APPROVAL, STATUS_PROCESSING])
    ).count()

    # Bad Product Stock is a separate inventory category - never added to total_stock above.
    total_bad_stock = db.session.query(func.coalesce(func.sum(BadProductStock.quantity), 0)).scalar()
    pending_bad_recoveries = BadProductRecovery.query.filter_by(status=BAD_RECOVERY_STATUS_PENDING).count()

    # Employee stock KPIs - a third, separate inventory bucket (never merged into total_stock).
    employees_by_location = (
        db.session.query(Location.name, func.count(Employee.id))
        .join(Employee, Employee.location_id == Location.id)
        .filter(Employee.is_active == True)
        .group_by(Location.id).all()
    )
    pending_employee_returns = EmployeeReturnRequest.query.filter_by(status=EMP_RETURN_STATUS_PENDING).count()
    good_returns_count = EmployeeReturnRequest.query.filter_by(status=EMP_RETURN_STATUS_APPROVED_GOOD).count()
    bad_returns_count = EmployeeReturnRequest.query.filter_by(status=EMP_RETURN_STATUS_APPROVED_BAD).count()

    recent_movements = StockMovement.query.order_by(StockMovement.created_at.desc()).limit(10).all()

    location_summary = (
        db.session.query(Location.name, func.coalesce(func.sum(LocationStock.quantity), 0))
        .outerjoin(LocationStock, LocationStock.location_id == Location.id)
        .filter(Location.is_active == True)
        .group_by(Location.id).all()
    )

    return render_template(
        "main/dashboard_admin.html",
        total_locations=total_locations, total_managers=total_managers,
        total_employees=total_employees, total_products=total_products,
        total_stock=total_stock, low_stock=low_stock,
        pending_transfers=pending_transfers, pending_adjustments=pending_adjustments,
        pending_returns=pending_returns, recent_movements=recent_movements,
        location_summary=location_summary,
        total_bad_stock=total_bad_stock, pending_bad_recoveries=pending_bad_recoveries,
        employees_by_location=employees_by_location, pending_employee_returns=pending_employee_returns,
        good_returns_count=good_returns_count, bad_returns_count=bad_returns_count,
    )


def _manager_dashboard():
    loc_ids = accessible_location_ids(current_user) or []

    total_products = Product.query.filter_by(is_active=True).count()
    total_qty = (
        db.session.query(func.coalesce(func.sum(LocationStock.quantity), 0))
        .filter(LocationStock.location_id.in_(loc_ids)).scalar()
    ) if loc_ids else 0

    low_stock = (
        db.session.query(LocationStock, Product, Location)
        .join(Product, LocationStock.product_id == Product.id)
        .join(Location, LocationStock.location_id == Location.id)
        .filter(LocationStock.location_id.in_(loc_ids), LocationStock.quantity <= Product.reorder_level)
        .limit(10).all()
    ) if loc_ids else []

    pending_transfers = StockTransfer.query.filter(
        StockTransfer.status == STATUS_PENDING_APPROVAL,
        StockTransfer.source_location_id.in_(loc_ids)
    ).count() if loc_ids else 0

    pending_returns = StockReturn.query.filter(
        StockReturn.status == STATUS_PENDING_APPROVAL,
        StockReturn.source_location_id.in_(loc_ids)
    ).count() if loc_ids else 0

    recent_movements = StockMovement.query.filter(
        StockMovement.location_id.in_(loc_ids)
    ).order_by(StockMovement.created_at.desc()).limit(10).all() if loc_ids else []

    employees = Employee.query.filter(Employee.location_id.in_(loc_ids), Employee.is_active == True).all() if loc_ids else []

    # Employee stock KPIs, scoped to this manager's authorized locations only.
    employees_with_stock = 0
    pending_employee_returns = 0
    today_issues = 0
    today_returns = 0
    bad_returns_today = 0
    if loc_ids:
        emp_ids = [e.id for e in employees]
        if emp_ids:
            employees_with_stock = (
                db.session.query(EmployeeStock.employee_id)
                .filter(EmployeeStock.employee_id.in_(emp_ids), EmployeeStock.quantity > 0)
                .distinct().count()
            )
        pending_employee_returns = EmployeeReturnRequest.query.filter(
            EmployeeReturnRequest.location_id.in_(loc_ids), EmployeeReturnRequest.status == EMP_RETURN_STATUS_PENDING
        ).count()
        today = datetime.utcnow().date()
        today_issues = EmployeeStockTransaction.query.join(Employee, EmployeeStockTransaction.employee_id == Employee.id).filter(
            Employee.location_id.in_(loc_ids), EmployeeStockTransaction.transaction_type == EMP_TXN_ISSUE,
            func.date(EmployeeStockTransaction.created_at) == today,
        ).count()
        today_returns = EmployeeStockTransaction.query.join(Employee, EmployeeStockTransaction.employee_id == Employee.id).filter(
            Employee.location_id.in_(loc_ids),
            EmployeeStockTransaction.transaction_type.in_([EMP_TXN_GOOD_RETURN, EMP_TXN_BAD_RETURN]),
            func.date(EmployeeStockTransaction.created_at) == today,
        ).count()
        bad_returns_today = EmployeeStockTransaction.query.join(Employee, EmployeeStockTransaction.employee_id == Employee.id).filter(
            Employee.location_id.in_(loc_ids), EmployeeStockTransaction.transaction_type == EMP_TXN_BAD_RETURN,
            func.date(EmployeeStockTransaction.created_at) == today,
        ).count()

    return render_template(
        "main/dashboard_manager.html",
        total_products=total_products, total_qty=total_qty, low_stock=low_stock,
        pending_transfers=pending_transfers, pending_returns=pending_returns,
        recent_movements=recent_movements, employees=employees,
        locations=Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids else [],
        employees_with_stock=employees_with_stock, pending_employee_returns=pending_employee_returns,
        today_issues=today_issues, today_returns=today_returns, bad_returns_today=bad_returns_today,
    )


def _employee_dashboard():
    profile = current_user.employee_profile
    location = profile.location if profile else None

    stock = []
    if location:
        stock = (
            db.session.query(LocationStock, Product)
            .join(Product, LocationStock.product_id == Product.id)
            .filter(LocationStock.location_id == location.id, Product.is_active == True)
            .limit(10).all()
        )

    from app.models import StockTransfer as ST
    my_requests_count = 0
    if location:
        my_requests_count = ST.query.filter_by(requested_by=current_user.id).count()

    recent = StockMovement.query.filter(
        StockMovement.location_id == (location.id if location else -1)
    ).order_by(StockMovement.created_at.desc()).limit(10).all() if location else []

    return render_template(
        "main/dashboard_employee.html",
        location=location, stock=stock, my_requests_count=my_requests_count, recent=recent,
    )
