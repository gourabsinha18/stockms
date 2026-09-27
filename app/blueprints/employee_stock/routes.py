from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import (
    Employee, EmployeeStock, EmployeeStockTransaction, EmployeeReturnRequest, Product, Location,
    ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER, ROLE_EMPLOYEE,
    EMP_RETURN_STATUS_PENDING, EMP_RETURN_STATUS_APPROVED_GOOD, EMP_RETURN_STATUS_APPROVED_BAD,
    EMP_RETURN_STATUS_REJECTED,
)
from app.services.permission_service import roles_required, accessible_location_ids, require_location_access, can_access_location
from app.services.employee_stock_service import (
    issue_stock_to_employee, create_return_request,
    approve_return_as_good, approve_return_as_bad, reject_return,
    EmployeeStockError,
)
from app.services.notification_service import notify_user, notify_location_managers
from app.services.audit_service import log_action
from .forms import IssueStockForm, ReturnRequestForm, ReviewReturnForm

bp = Blueprint("employee_stock", __name__)


def _current_employee_or_404():
    if not current_user.is_employee() or not current_user.employee_profile:
        abort(403)
    return current_user.employee_profile


# ---------------------------------------------------------------------------
# STOCK MANAGER / MAIN ADMIN VIEWS
# ---------------------------------------------------------------------------

@bp.route("/issue", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def issue_stock():
    loc_ids = accessible_location_ids(current_user)
    emp_query = Employee.query.filter_by(is_active=True)
    if loc_ids is not None:
        emp_query = emp_query.filter(Employee.location_id.in_(loc_ids))
    employees = emp_query.join(Employee.user).order_by(Employee.employee_code).all()

    form = IssueStockForm()
    form.employee_id.choices = [(e.id, f"{e.employee_code} - {e.user.full_name} ({e.location.name})") for e in employees]
    form.product_id.choices = [(p.id, f"{p.sku} - {p.name}") for p in Product.query.filter_by(is_active=True).order_by(Product.name)]

    if form.validate_on_submit():
        employee = Employee.query.get(form.employee_id.data)
        if employee is None or (loc_ids is not None and employee.location_id not in loc_ids):
            abort(403)  # never trust the submitted employee_id belongs to an authorized location
        require_location_access(employee.location_id)
        try:
            txn = issue_stock_to_employee(employee.id, form.product_id.data, form.quantity.data,
                                          current_user.id, form.reason.data)
            log_action("ISSUE_STOCK_TO_EMPLOYEE", "EmployeeStock", entity_id=employee.id,
                      new_value=f"product={form.product_id.data} qty={form.quantity.data}")
            notify_user(employee.user_id, "Stock Issued",
                       f"{form.quantity.data} unit(s) issued to you. Reason: {form.reason.data}",
                       link=url_for("employee_stock.my_stock"))
            db.session.commit()
            flash(f"Issued {form.quantity.data} unit(s) to {employee.user.full_name}.", "success")
            return redirect(url_for("employee_stock.issue_stock"))
        except EmployeeStockError as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("employee_stock/issue_form.html", form=form)


@bp.route("/")
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def employee_stock_overview():
    loc_ids = accessible_location_ids(current_user)
    query = db.session.query(EmployeeStock, Employee, Product).join(
        Employee, EmployeeStock.employee_id == Employee.id
    ).join(Product, EmployeeStock.product_id == Product.id).filter(EmployeeStock.quantity > 0)
    if loc_ids is not None:
        query = query.filter(Employee.location_id.in_(loc_ids))

    location_id = request.args.get("location_id", type=int)
    if location_id:
        require_location_access(location_id)
        query = query.filter(Employee.location_id == location_id)

    rows = query.order_by(Employee.employee_code, Product.name).all()
    locations = Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids is not None else Location.query.filter_by(is_active=True).all()
    return render_template("employee_stock/overview.html", rows=rows, locations=locations, location_id=location_id)


@bp.route("/returns")
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def list_returns():
    loc_ids = accessible_location_ids(current_user)
    query = EmployeeReturnRequest.query
    if loc_ids is not None:
        query = query.filter(EmployeeReturnRequest.location_id.in_(loc_ids))

    status_filter = request.args.get("status", "")
    location_id = request.args.get("location_id", type=int)
    if status_filter:
        query = query.filter(EmployeeReturnRequest.status == status_filter)
    if location_id:
        require_location_access(location_id)
        query = query.filter(EmployeeReturnRequest.location_id == location_id)

    returns = query.order_by(EmployeeReturnRequest.requested_at.desc()).all()
    locations = Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids is not None else Location.query.filter_by(is_active=True).all()
    return render_template("employee_stock/returns_list.html", returns=returns, locations=locations,
                           status_filter=status_filter, location_id=location_id)


@bp.route("/returns/<int:return_id>")
@login_required
def view_return(return_id):
    ret = EmployeeReturnRequest.query.get_or_404(return_id)
    if current_user.is_employee():
        if not current_user.employee_profile or current_user.employee_profile.id != ret.employee_id:
            abort(403)
    elif not can_access_location(current_user, ret.location_id):
        abort(403)
    form = ReviewReturnForm()
    return render_template("employee_stock/return_detail.html", ret=ret, form=form)


@bp.route("/returns/<int:return_id>/approve-good", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def approve_good(return_id):
    ret = EmployeeReturnRequest.query.get_or_404(return_id)
    require_location_access(ret.location_id)
    try:
        approve_return_as_good(return_id, current_user.id, remarks=request.form.get("remarks"))
        log_action("APPROVE_EMPLOYEE_RETURN_GOOD", "EmployeeReturnRequest", entity_id=ret.id, new_value=ret.return_code)
        notify_user(ret.employee.user_id, "Return Approved (Good Stock)",
                   f"Your return {ret.return_code} was approved and added back to good stock.",
                   link=url_for("employee_stock.view_return", return_id=ret.id))
        db.session.commit()
        flash("Return approved as GOOD stock.", "success")
    except EmployeeStockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("employee_stock.view_return", return_id=return_id))


@bp.route("/returns/<int:return_id>/approve-bad", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def approve_bad(return_id):
    ret = EmployeeReturnRequest.query.get_or_404(return_id)
    require_location_access(ret.location_id)
    try:
        approve_return_as_bad(return_id, current_user.id, remarks=request.form.get("remarks"))
        log_action("APPROVE_EMPLOYEE_RETURN_BAD", "EmployeeReturnRequest", entity_id=ret.id, new_value=ret.return_code)
        notify_user(ret.employee.user_id, "Return Approved (Bad Stock)",
                   f"Your return {ret.return_code} was classified as bad product stock.",
                   link=url_for("employee_stock.view_return", return_id=ret.id))
        db.session.commit()
        flash("Return approved as BAD product stock.", "success")
    except EmployeeStockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("employee_stock.view_return", return_id=return_id))


@bp.route("/returns/<int:return_id>/reject", methods=["POST"])
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def reject(return_id):
    ret = EmployeeReturnRequest.query.get_or_404(return_id)
    require_location_access(ret.location_id)
    try:
        reject_return(return_id, current_user.id, remarks=request.form.get("remarks"))
        log_action("REJECT_EMPLOYEE_RETURN", "EmployeeReturnRequest", entity_id=ret.id, new_value=ret.return_code)
        notify_user(ret.employee.user_id, "Return Rejected",
                   f"Your return {ret.return_code} was rejected.",
                   link=url_for("employee_stock.view_return", return_id=ret.id))
        db.session.commit()
        flash("Return rejected.", "info")
    except EmployeeStockError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("employee_stock.view_return", return_id=return_id))


@bp.route("/history")
@login_required
@roles_required(ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER)
def history():
    loc_ids = accessible_location_ids(current_user)
    query = EmployeeStockTransaction.query.join(Employee, EmployeeStockTransaction.employee_id == Employee.id)
    if loc_ids is not None:
        query = query.filter(Employee.location_id.in_(loc_ids))

    employee_id = request.args.get("employee_id", type=int)
    if employee_id:
        query = query.filter(EmployeeStockTransaction.employee_id == employee_id)
    txn_type = request.args.get("type", "")
    if txn_type:
        query = query.filter(EmployeeStockTransaction.transaction_type == txn_type)

    transactions = query.order_by(EmployeeStockTransaction.created_at.desc()).limit(300).all()
    return render_template("employee_stock/history.html", transactions=transactions, employee_id=employee_id, txn_type=txn_type)


# ---------------------------------------------------------------------------
# EMPLOYEE SELF-SERVICE VIEWS ("My Stock")
# ---------------------------------------------------------------------------

@bp.route("/my-stock")
@login_required
@roles_required(ROLE_EMPLOYEE)
def my_stock():
    employee = _current_employee_or_404()
    current_stock = EmployeeStock.query.filter_by(employee_id=employee.id).filter(EmployeeStock.quantity > 0).all()
    received_history = EmployeeStockTransaction.query.filter_by(
        employee_id=employee.id, transaction_type="ISSUE"
    ).order_by(EmployeeStockTransaction.created_at.desc()).limit(30).all()
    return render_template("employee_stock/my_stock.html", employee=employee, current_stock=current_stock,
                           received_history=received_history)


@bp.route("/my-stock/return/new", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_EMPLOYEE)
def new_return():
    employee = _current_employee_or_404()
    owned = EmployeeStock.query.filter_by(employee_id=employee.id).filter(EmployeeStock.quantity > 0).all()

    form = ReturnRequestForm()
    form.product_id.choices = [(s.product.id, f"{s.product.sku} - {s.product.name} (you have {s.quantity})") for s in owned]

    if not owned:
        flash("You have no stock currently assigned to return.", "info")

    if form.validate_on_submit():
        try:
            ret = create_return_request(employee.id, form.product_id.data, form.quantity.data,
                                        form.reported_condition.data, reason=form.reason.data)
            log_action("CREATE_EMPLOYEE_RETURN", "EmployeeReturnRequest", entity_id=ret.id, new_value=ret.return_code)
            notify_location_managers(employee.location_id, "New Employee Return Request",
                               f"{employee.user.full_name} submitted return {ret.return_code} for review.",
                               link=url_for("employee_stock.view_return", return_id=ret.id))
            db.session.commit()
            flash(f"Return request {ret.return_code} submitted.", "success")
            return redirect(url_for("employee_stock.my_returns"))
        except EmployeeStockError as e:
            db.session.rollback()
            flash(str(e), "danger")

    return render_template("employee_stock/return_form.html", form=form)


@bp.route("/my-stock/returns")
@login_required
@roles_required(ROLE_EMPLOYEE)
def my_returns():
    employee = _current_employee_or_404()
    pending = EmployeeReturnRequest.query.filter_by(employee_id=employee.id, status=EMP_RETURN_STATUS_PENDING).order_by(
        EmployeeReturnRequest.requested_at.desc()
    ).all()
    history = EmployeeReturnRequest.query.filter_by(employee_id=employee.id).filter(
        EmployeeReturnRequest.status != EMP_RETURN_STATUS_PENDING
    ).order_by(EmployeeReturnRequest.requested_at.desc()).all()
    return render_template("employee_stock/my_returns.html", pending=pending, history=history)
