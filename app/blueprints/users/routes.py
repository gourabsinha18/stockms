from flask import Blueprint, render_template, redirect, url_for, flash, abort, request
from flask_login import login_required, current_user
from sqlalchemy import or_
from app.extensions import db
from app.models import (
    User, Employee, StockManagerAssignment, Location, EmployeeStock, EmployeeStockTransaction,
    EmployeeReturnRequest, ROLE_STOCK_MANAGER, ROLE_EMPLOYEE, EMP_RETURN_STATUS_PENDING,
    gen_employee_code,
)
from app.services.audit_service import log_action
from app.services.permission_service import admin_required, accessible_location_ids, require_location_access, can_access_location
from .forms import NewStockManagerForm, NewEmployeeForm, EditEmployeeForm

bp = Blueprint("users", __name__)


# ---------------- Stock Managers ----------------

@bp.route("/stock-managers")
@login_required
@admin_required
def list_stock_managers():
    managers = User.query.filter_by(role=ROLE_STOCK_MANAGER).order_by(User.full_name).all()
    return render_template("users/managers_list.html", managers=managers)


@bp.route("/stock-managers/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_stock_manager():
    form = NewStockManagerForm()
    form.location_ids.choices = [(l.id, f"{l.code} - {l.name}") for l in Location.query.filter_by(is_active=True).order_by(Location.name)]

    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash("Username already exists.", "danger")
        elif User.query.filter_by(email=form.email.data).first():
            flash("Email already registered.", "danger")
        else:
            user = User(username=form.username.data, email=form.email.data, full_name=form.full_name.data,
                       role=ROLE_STOCK_MANAGER)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()
            for loc_id in form.location_ids.data:
                db.session.add(StockManagerAssignment(user_id=user.id, location_id=loc_id))
            log_action("CREATE", "User", entity_id=user.id, new_value=f"{user.username} (STOCK_MANAGER)")
            db.session.commit()
            flash(f"Stock Manager '{user.full_name}' created.", "success")
            return redirect(url_for("users.list_stock_managers"))

    return render_template("users/manager_form.html", form=form)


@bp.route("/stock-managers/<int:user_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_manager(user_id):
    user = User.query.filter_by(id=user_id, role=ROLE_STOCK_MANAGER).first_or_404()
    prev = user.is_active
    user.is_active = not user.is_active
    log_action("UPDATE", "User", entity_id=user.id, previous_value=f"active={prev}", new_value=f"active={user.is_active}")
    db.session.commit()
    flash(f"Stock Manager {'activated' if user.is_active else 'deactivated'}.", "success")
    return redirect(url_for("users.list_stock_managers"))


# ---------------- Employee Directory ----------------

def _employee_base_query():
    """Every employee list/search entry point starts here so location scoping can never be
    accidentally skipped (Phase 3 - location security must be enforced server-side, not just by
    hiding UI elements)."""
    if current_user.is_main_admin():
        return Employee.query.join(User, Employee.user_id == User.id)
    elif current_user.is_stock_manager():
        loc_ids = accessible_location_ids(current_user) or []
        return Employee.query.filter(Employee.location_id.in_(loc_ids)).join(User, Employee.user_id == User.id)
    else:
        abort(403)


@bp.route("/employees")
@login_required
def list_employees():
    if current_user.is_employee():
        # An employee has no "directory" access - only their own profile.
        if current_user.employee_profile:
            return redirect(url_for("users.employee_detail", employee_id=current_user.employee_profile.id))
        abort(403)

    query = _employee_base_query()

    location_id = request.args.get("location_id", type=int)
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "")
    designation_filter = request.args.get("designation", "").strip()
    department_filter = request.args.get("department", "").strip()
    page = request.args.get("page", 1, type=int)

    if location_id:
        require_location_access(location_id)
        query = query.filter(Employee.location_id == location_id)
    if status_filter == "active":
        query = query.filter(Employee.is_active.is_(True))
    elif status_filter == "inactive":
        query = query.filter(Employee.is_active.is_(False))
    if designation_filter:
        query = query.filter(Employee.designation == designation_filter)
    if department_filter:
        query = query.filter(Employee.department == department_filter)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Employee.employee_code.ilike(like), User.full_name.ilike(like),
            Employee.phone.ilike(like), User.email.ilike(like), Employee.designation.ilike(like),
        ))

    query = query.order_by(User.full_name)
    pagination = query.paginate(page=page, per_page=25, error_out=False)
    employees = pagination.items

    # Group the current page by location for the "grouped by location" list view.
    grouped = {}
    for e in employees:
        grouped.setdefault(e.location.name, []).append(e)

    loc_ids = accessible_location_ids(current_user)
    locations = Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids is not None else Location.query.filter_by(is_active=True).order_by(Location.name).all()

    # Employee counts by location (Phase 4) - scoped the same way as the directory itself.
    counts_query = _employee_base_query()
    location_counts = {}
    for e in counts_query.all():
        location_counts[e.location.name] = location_counts.get(e.location.name, 0) + 1

    designations = sorted({d[0] for d in db.session.query(Employee.designation).filter(Employee.designation.isnot(None)).distinct() if d[0]})
    departments = sorted({d[0] for d in db.session.query(Employee.department).filter(Employee.department.isnot(None)).distinct() if d[0]})

    return render_template(
        "users/employees_list.html", grouped=grouped, pagination=pagination, locations=locations,
        location_id=location_id, q=q, status_filter=status_filter,
        designation_filter=designation_filter, department_filter=department_filter,
        designations=designations, departments=departments, location_counts=location_counts,
    )


@bp.route("/employees/new", methods=["GET", "POST"])
@login_required
def new_employee():
    if not (current_user.is_main_admin() or current_user.is_stock_manager()):
        abort(403)

    form = NewEmployeeForm()
    if current_user.is_main_admin():
        locations = Location.query.filter_by(is_active=True).order_by(Location.name).all()
    else:
        loc_ids = accessible_location_ids(current_user) or []
        locations = Location.query.filter(Location.id.in_(loc_ids)).all()
    form.location_id.choices = [(l.id, f"{l.code} - {l.name}") for l in locations]
    form.stock_manager_id.choices = [(0, "-- None --")] + [
        (u.id, u.full_name) for u in User.query.filter_by(role=ROLE_STOCK_MANAGER, is_active=True).order_by(User.full_name)
    ]

    if form.validate_on_submit():
        if not current_user.is_main_admin():
            require_location_access(form.location_id.data)
        code = form.employee_code.data.strip() if form.employee_code.data else None
        if code and Employee.query.filter_by(employee_code=code).first():
            flash("Employee ID already exists.", "danger")
        elif User.query.filter_by(username=form.username.data).first():
            flash("Username already exists.", "danger")
        elif User.query.filter_by(email=form.email.data).first():
            flash("Email already registered.", "danger")
        else:
            user = User(username=form.username.data, email=form.email.data, full_name=form.full_name.data,
                       role=ROLE_EMPLOYEE)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()
            sm_id = form.stock_manager_id.data if form.stock_manager_id.data and form.stock_manager_id.data != 0 else None
            employee = Employee(
                employee_code=code or gen_employee_code(), user_id=user.id, location_id=form.location_id.data,
                stock_manager_id=sm_id, phone=form.phone.data or None,
                designation=form.designation.data or None, department=form.department.data or None,
            )
            db.session.add(employee)
            log_action("CREATE", "Employee", entity_id=user.id, new_value=f"{user.username} ({employee.employee_code})")
            db.session.commit()
            flash(f"Employee '{user.full_name}' created.", "success")
            return redirect(url_for("users.list_employees"))

    return render_template("users/employee_form.html", form=form, mode="new")


@bp.route("/employees/<int:employee_id>")
@login_required
def employee_detail(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    if current_user.is_employee():
        if not current_user.employee_profile or current_user.employee_profile.id != employee.id:
            abort(403)
    elif not can_access_location(current_user, employee.location_id):
        abort(403)

    current_stock = EmployeeStock.query.filter_by(employee_id=employee.id).filter(EmployeeStock.quantity > 0).all()
    transactions = EmployeeStockTransaction.query.filter_by(employee_id=employee.id).order_by(
        EmployeeStockTransaction.created_at.desc()
    ).limit(50).all()
    pending_returns = EmployeeReturnRequest.query.filter_by(
        employee_id=employee.id, status=EMP_RETURN_STATUS_PENDING
    ).all()
    return_history = EmployeeReturnRequest.query.filter_by(employee_id=employee.id).filter(
        EmployeeReturnRequest.status != EMP_RETURN_STATUS_PENDING
    ).order_by(EmployeeReturnRequest.requested_at.desc()).limit(20).all()

    return render_template(
        "users/employee_detail.html", employee=employee, current_stock=current_stock,
        transactions=transactions, pending_returns=pending_returns, return_history=return_history,
    )


@bp.route("/employees/<int:employee_id>/edit", methods=["GET", "POST"])
@login_required
def edit_employee(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    if not (current_user.is_main_admin() or current_user.is_stock_manager()):
        abort(403)
    if not can_access_location(current_user, employee.location_id):
        abort(403)

    form = EditEmployeeForm(obj=employee)
    if request.method == "GET":
        form.full_name.data = employee.user.full_name
        form.email.data = employee.user.email
        form.is_active.data = employee.is_active

    if current_user.is_main_admin():
        locations = Location.query.filter_by(is_active=True).order_by(Location.name).all()
    else:
        loc_ids = accessible_location_ids(current_user) or []
        locations = Location.query.filter(Location.id.in_(loc_ids)).all()
    form.location_id.choices = [(l.id, f"{l.code} - {l.name}") for l in locations]
    form.stock_manager_id.choices = [(0, "-- None --")] + [
        (u.id, u.full_name) for u in User.query.filter_by(role=ROLE_STOCK_MANAGER, is_active=True).order_by(User.full_name)
    ]

    if form.validate_on_submit():
        require_location_access(form.location_id.data)  # covers the "moved to a location I can't access" case too
        dup_code = Employee.query.filter(Employee.employee_code == form.employee_code.data, Employee.id != employee.id).first()
        dup_email = User.query.filter(User.email == form.email.data, User.id != employee.user_id).first()
        if dup_code:
            flash("Employee ID already exists.", "danger")
        elif dup_email:
            flash("Email already registered to another user.", "danger")
        else:
            prev = f"code={employee.employee_code}, location={employee.location_id}, active={employee.is_active}"
            employee.employee_code = form.employee_code.data
            employee.phone = form.phone.data or None
            employee.designation = form.designation.data or None
            employee.department = form.department.data or None
            employee.location_id = form.location_id.data
            employee.stock_manager_id = form.stock_manager_id.data if form.stock_manager_id.data and form.stock_manager_id.data != 0 else None
            employee.is_active = form.is_active.data
            employee.user.full_name = form.full_name.data
            employee.user.email = form.email.data
            new_val = f"code={employee.employee_code}, location={employee.location_id}, active={employee.is_active}"
            log_action("UPDATE", "Employee", entity_id=employee.id, previous_value=prev, new_value=new_val)
            db.session.commit()
            flash(f"Employee '{employee.user.full_name}' updated.", "success")
            return redirect(url_for("users.employee_detail", employee_id=employee.id))

    return render_template("users/employee_form.html", form=form, mode="edit", employee=employee)


@bp.route("/employees/<int:employee_id>/toggle", methods=["POST"])
@login_required
def toggle_employee(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    if not (current_user.is_main_admin() or current_user.is_stock_manager()):
        abort(403)
    if not current_user.is_main_admin():
        require_location_access(employee.location_id)
    prev = employee.is_active
    employee.is_active = not employee.is_active
    log_action("UPDATE", "Employee", entity_id=employee.id, previous_value=f"active={prev}", new_value=f"active={employee.is_active}")
    db.session.commit()
    flash(f"Employee {'activated' if employee.is_active else 'deactivated'}.", "success")
    return redirect(url_for("users.list_employees"))
