import csv
import io
from flask import Blueprint, render_template, request, Response
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models import (
    LocationStock, Product, Location, Unit, Brand, Category, StockMovement,
    StockTransfer, StockAdjustment, StockReturn, StockReceipt,
    BadProductStock, BadProductMovement, BadProductRecovery, BadProductTransfer,
    Employee, EmployeeStock, EmployeeStockTransaction, EmployeeReturnRequest,
    User, ROLE_EMPLOYEE,
)
from app.services.permission_service import accessible_location_ids

bp = Blueprint("reports", __name__)


@bp.route("/")
@login_required
def index():
    return render_template("reports/index.html")


def _csv_response(filename, header, rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    resp = Response(output.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return resp


@bp.route("/stock-by-location")
@login_required
def stock_by_location():
    loc_ids = accessible_location_ids(current_user)
    query = (
        db.session.query(Location.name, func.coalesce(func.sum(LocationStock.quantity), 0), func.count(LocationStock.id))
        .outerjoin(LocationStock, LocationStock.location_id == Location.id)
        .filter(Location.is_active == True)
    )
    if loc_ids is not None:
        query = query.filter(Location.id.in_(loc_ids))
    rows = query.group_by(Location.id).order_by(Location.name).all()

    if request.args.get("export") == "csv":
        return _csv_response("stock_by_location.csv", ["Location", "Total Quantity", "Distinct Products"], rows)
    return render_template("reports/stock_by_location.html", rows=rows)


@bp.route("/stock-by-product")
@login_required
def stock_by_product():
    loc_ids = accessible_location_ids(current_user)
    query = (
        db.session.query(Product.sku, Product.name, func.coalesce(func.sum(LocationStock.quantity), 0))
        .join(LocationStock, LocationStock.product_id == Product.id)
    )
    if loc_ids is not None:
        query = query.filter(LocationStock.location_id.in_(loc_ids))
    rows = query.group_by(Product.id).order_by(Product.name).all()

    if request.args.get("export") == "csv":
        return _csv_response("stock_by_product.csv", ["SKU", "Product", "Total Quantity"], rows)
    return render_template("reports/stock_by_product.html", rows=rows)


@bp.route("/low-stock")
@login_required
def low_stock():
    loc_ids = accessible_location_ids(current_user)
    query = (
        db.session.query(LocationStock, Product, Location)
        .join(Product, LocationStock.product_id == Product.id)
        .join(Location, LocationStock.location_id == Location.id)
        .filter(LocationStock.quantity <= Product.reorder_level, Product.is_active == True)
    )
    if loc_ids is not None:
        query = query.filter(LocationStock.location_id.in_(loc_ids))
    rows = query.order_by(Location.name, Product.name).all()

    if request.args.get("export") == "csv":
        data = [(l.name, p.sku, p.name, s.quantity, p.reorder_level) for s, p, l in rows]
        return _csv_response("low_stock.csv", ["Location", "SKU", "Product", "Quantity", "Reorder Level"], data)
    return render_template("reports/low_stock.html", rows=rows)


@bp.route("/unit-brand-category")
@login_required
def unit_brand_category():
    loc_ids = accessible_location_ids(current_user)
    q = (
        db.session.query(Unit.name, Brand.name, Category.name, func.coalesce(func.sum(LocationStock.quantity), 0))
        .join(Brand, Brand.unit_id == Unit.id)
        .join(Category, Category.brand_id == Brand.id)
        .join(Product, Product.category_id == Category.id)
        .outerjoin(LocationStock, LocationStock.product_id == Product.id)
    )
    if loc_ids is not None:
        q = q.filter((LocationStock.location_id.in_(loc_ids)) | (LocationStock.location_id.is_(None)))
    rows = q.group_by(Unit.id, Brand.id, Category.id).order_by(Unit.name, Brand.name, Category.name).all()

    if request.args.get("export") == "csv":
        return _csv_response("unit_brand_category.csv", ["Unit", "Brand", "Category", "Total Quantity"], rows)
    return render_template("reports/unit_brand_category.html", rows=rows)


@bp.route("/movements")
@login_required
def movement_report():
    loc_ids = accessible_location_ids(current_user)
    movement_type = request.args.get("movement_type", "")
    query = StockMovement.query
    if loc_ids is not None:
        query = query.filter(StockMovement.location_id.in_(loc_ids))
    if movement_type:
        query = query.filter(StockMovement.movement_type == movement_type)
    rows = query.order_by(StockMovement.created_at.desc()).limit(500).all()

    if request.args.get("export") == "csv":
        data = [(m.created_at.strftime("%Y-%m-%d %H:%M"), m.product.name, m.location.name, m.movement_type,
                 m.qty_before, m.qty_change, m.qty_after, m.user.full_name) for m in rows]
        return _csv_response("movement_report.csv",
                             ["Date", "Product", "Location", "Type", "Before", "Change", "After", "User"], data)
    return render_template("reports/movements.html", rows=rows, movement_type=movement_type)


@bp.route("/transfers")
@login_required
def transfer_report():
    loc_ids = accessible_location_ids(current_user)
    query = StockTransfer.query
    if loc_ids is not None:
        query = query.filter((StockTransfer.source_location_id.in_(loc_ids)) | (StockTransfer.dest_location_id.in_(loc_ids)))
    rows = query.order_by(StockTransfer.requested_at.desc()).all()

    if request.args.get("export") == "csv":
        data = [(t.transfer_code, t.source_location.name, t.dest_location.name, t.status,
                 t.requester.full_name, t.requested_at.strftime("%Y-%m-%d")) for t in rows]
        return _csv_response("transfer_report.csv", ["Code", "Source", "Destination", "Status", "Requested By", "Date"], data)
    return render_template("reports/transfers.html", rows=rows)


@bp.route("/adjustments")
@login_required
def adjustment_report():
    loc_ids = accessible_location_ids(current_user)
    query = StockAdjustment.query
    if loc_ids is not None:
        query = query.filter(StockAdjustment.location_id.in_(loc_ids))
    rows = query.order_by(StockAdjustment.requested_at.desc()).all()

    if request.args.get("export") == "csv":
        data = [(a.adjustment_code, a.location.name, a.product.name, a.previous_qty, a.adjustment_qty,
                 a.new_qty, a.reason, a.status) for a in rows]
        return _csv_response("adjustment_report.csv",
                             ["Code", "Location", "Product", "Previous", "Change", "New", "Reason", "Status"], data)
    return render_template("reports/adjustments.html", rows=rows)


@bp.route("/returns")
@login_required
def return_report():
    loc_ids = accessible_location_ids(current_user)
    query = StockReturn.query
    if loc_ids is not None:
        query = query.filter(StockReturn.source_location_id.in_(loc_ids))
    rows = query.order_by(StockReturn.requested_at.desc()).all()

    if request.args.get("export") == "csv":
        data = [(r.return_code, r.source_location.name, r.dest_location.name, r.reason, r.status) for r in rows]
        return _csv_response("return_report.csv", ["Code", "Source", "Destination", "Reason", "Status"], data)
    return render_template("reports/returns.html", rows=rows)


@bp.route("/stock-in")
@login_required
def stock_in_report():
    loc_ids = accessible_location_ids(current_user)
    query = StockReceipt.query
    if loc_ids is not None:
        query = query.filter(StockReceipt.location_id.in_(loc_ids))
    rows = query.order_by(StockReceipt.created_at.desc()).all()

    if request.args.get("export") == "csv":
        data = [(r.receipt_code, r.location.name, r.supplier_source or "", r.reference_number or "",
                 r.receiver.full_name, r.created_at.strftime("%Y-%m-%d")) for r in rows]
        return _csv_response("stock_in_report.csv", ["Code", "Location", "Supplier", "Reference", "Received By", "Date"], data)
    return render_template("reports/stock_in.html", rows=rows)


# ---------------------------------------------------------------------------
# BAD PRODUCT REPORTS (Fix 2)
#
# These read ONLY from BadProductStock / BadProductRecovery / BadProductTransfer /
# BadProductMovement. Normal stock (LocationStock/StockMovement) is never
# included in the quantities shown here.
# ---------------------------------------------------------------------------

@bp.route("/bad-product-stock")
@login_required
def bad_product_stock_report():
    loc_ids = accessible_location_ids(current_user)
    location_id = request.args.get("location_id", type=int)
    product_id = request.args.get("product_id", type=int)

    query = (
        db.session.query(BadProductStock, Product, Location)
        .join(Product, BadProductStock.product_id == Product.id)
        .join(Location, BadProductStock.location_id == Location.id)
    )
    if loc_ids is not None:
        query = query.filter(BadProductStock.location_id.in_(loc_ids))
    if location_id:
        query = query.filter(BadProductStock.location_id == location_id)
    if product_id:
        query = query.filter(BadProductStock.product_id == product_id)
    rows = query.order_by(Location.name, Product.name).all()

    if request.args.get("export") == "csv":
        data = [(l.name, p.name, p.sku, s.quantity) for s, p, l in rows]
        return _csv_response("bad_product_stock_report.csv", ["Location", "Product", "SKU", "Bad Product Quantity"], data)

    locations = Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids is not None else Location.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    return render_template("reports/bad_product_stock.html", rows=rows, locations=locations, products=products,
                           location_id=location_id, product_id=product_id)


@bp.route("/bad-product-recoveries")
@login_required
def bad_product_recovery_report():
    loc_ids = accessible_location_ids(current_user)
    location_id = request.args.get("location_id", type=int)
    employee_id = request.args.get("employee_id", type=int)
    product_id = request.args.get("product_id", type=int)
    status_filter = request.args.get("status", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    query = BadProductRecovery.query
    if loc_ids is not None:
        query = query.filter(BadProductRecovery.location_id.in_(loc_ids))
    if location_id:
        query = query.filter(BadProductRecovery.location_id == location_id)
    if employee_id:
        query = query.filter(BadProductRecovery.requested_by == employee_id)
    if product_id:
        query = query.filter(BadProductRecovery.items.any(product_id=product_id))
    if status_filter:
        query = query.filter(BadProductRecovery.status == status_filter)
    if date_from:
        query = query.filter(BadProductRecovery.recovery_date >= date_from)
    if date_to:
        query = query.filter(BadProductRecovery.recovery_date <= date_to)
    rows = query.order_by(BadProductRecovery.requested_at.desc()).all()

    if request.args.get("export") == "csv":
        data = [(
            r.recovery_code, r.requester.full_name, r.location.name,
            ", ".join(i.product.name for i in r.items), sum(i.quantity for i in r.items),
            r.service_reference, r.recovery_date.strftime("%Y-%m-%d"), r.status,
            r.requested_at.strftime("%Y-%m-%d"),
            r.approver.full_name if r.approver else "", r.approved_at.strftime("%Y-%m-%d") if r.approved_at else "",
        ) for r in rows]
        return _csv_response("bad_product_recovery_report.csv", [
            "Recovery Code", "Employee", "Location", "Product", "Quantity", "Service Reference",
            "Recovery Date", "Status", "Requested Date", "Approved By", "Approved Date",
        ], data)

    locations = Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids is not None else Location.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    employees = User.query.filter_by(role=ROLE_EMPLOYEE, is_active=True).order_by(User.full_name).all()
    return render_template("reports/bad_product_recoveries.html", rows=rows, locations=locations, products=products,
                           employees=employees, location_id=location_id, employee_id=employee_id,
                           product_id=product_id, status_filter=status_filter, date_from=date_from, date_to=date_to)


@bp.route("/bad-product-transfers")
@login_required
def bad_product_transfer_report():
    loc_ids = accessible_location_ids(current_user)
    source_id = request.args.get("source_id", type=int)
    dest_id = request.args.get("dest_id", type=int)
    product_id = request.args.get("product_id", type=int)
    status_filter = request.args.get("status", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    query = BadProductTransfer.query
    if loc_ids is not None:
        query = query.filter(
            (BadProductTransfer.source_location_id.in_(loc_ids)) | (BadProductTransfer.dest_location_id.in_(loc_ids))
        )
    if source_id:
        query = query.filter(BadProductTransfer.source_location_id == source_id)
    if dest_id:
        query = query.filter(BadProductTransfer.dest_location_id == dest_id)
    if product_id:
        query = query.filter(BadProductTransfer.items.any(product_id=product_id))
    if status_filter:
        query = query.filter(BadProductTransfer.status == status_filter)
    if date_from:
        query = query.filter(BadProductTransfer.requested_at >= date_from)
    if date_to:
        query = query.filter(BadProductTransfer.requested_at <= date_to)
    rows = query.order_by(BadProductTransfer.requested_at.desc()).all()

    if request.args.get("export") == "csv":
        data = [(
            t.transfer_code, t.source_location.name, t.dest_location.name,
            ", ".join(i.product.name for i in t.items), sum(i.quantity for i in t.items),
            t.requester.full_name, t.status, t.requested_at.strftime("%Y-%m-%d"),
            t.approved_at.strftime("%Y-%m-%d") if t.approved_at else "",
            t.dispatched_at.strftime("%Y-%m-%d") if t.dispatched_at else "",
            t.completed_at.strftime("%Y-%m-%d") if t.completed_at else "",
        ) for t in rows]
        return _csv_response("bad_product_transfer_report.csv", [
            "Transfer Code", "Source", "Destination", "Product", "Quantity", "Requested By", "Status",
            "Requested Date", "Approved Date", "Dispatch Date", "Receive/Completion Date",
        ], data)

    locations = Location.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    return render_template("reports/bad_product_transfers.html", rows=rows, locations=locations, products=products,
                           source_id=source_id, dest_id=dest_id, product_id=product_id,
                           status_filter=status_filter, date_from=date_from, date_to=date_to)


@bp.route("/bad-product-history")
@login_required
def bad_product_history_report():
    """Uses ONLY BadProductMovement - never StockMovement."""
    loc_ids = accessible_location_ids(current_user)
    location_id = request.args.get("location_id", type=int)
    product_id = request.args.get("product_id", type=int)
    movement_type = request.args.get("movement_type", "")

    query = BadProductMovement.query
    if loc_ids is not None:
        query = query.filter(BadProductMovement.location_id.in_(loc_ids))
    if location_id:
        query = query.filter(BadProductMovement.location_id == location_id)
    if product_id:
        query = query.filter(BadProductMovement.product_id == product_id)
    if movement_type:
        query = query.filter(BadProductMovement.movement_type == movement_type)
    rows = query.order_by(BadProductMovement.created_at.desc()).limit(500).all()

    if request.args.get("export") == "csv":
        data = [(
            m.created_at.strftime("%Y-%m-%d %H:%M"), m.location.name, m.product.name, m.movement_type,
            m.quantity_before, m.quantity_change, m.quantity_after,
            f"{m.reference_type} #{m.reference_id}" if m.reference_type else "", m.user.full_name, m.remarks or "",
        ) for m in rows]
        return _csv_response("bad_product_history_report.csv", [
            "Date", "Location", "Product", "Movement Type", "Quantity Before", "Quantity Change",
            "Quantity After", "Reference", "User", "Remarks",
        ], data)

    locations = Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids is not None else Location.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    return render_template("reports/bad_product_history.html", rows=rows, locations=locations, products=products,
                           location_id=location_id, product_id=product_id, movement_type=movement_type)


# ---------------------------------------------------------------------------
# EMPLOYEE STOCK REPORT
#
# Reads ONLY from EmployeeStockTransaction / EmployeeReturnRequest - the
# employee-accountability ledger is independent of both StockMovement and
# BadProductMovement, and this report never mixes them together.
# ---------------------------------------------------------------------------

@bp.route("/employee-stock")
@login_required
def employee_stock_report():
    loc_ids = accessible_location_ids(current_user)
    location_id = request.args.get("location_id", type=int)
    employee_id = request.args.get("employee_id", type=int)
    product_id = request.args.get("product_id", type=int)
    txn_type = request.args.get("type", "")
    status_filter = request.args.get("status", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    txn_query = EmployeeStockTransaction.query.join(Employee, EmployeeStockTransaction.employee_id == Employee.id)
    ret_query = EmployeeReturnRequest.query
    if loc_ids is not None:
        txn_query = txn_query.filter(Employee.location_id.in_(loc_ids))
        ret_query = ret_query.filter(EmployeeReturnRequest.location_id.in_(loc_ids))
    if location_id:
        require_location_access(location_id)
        txn_query = txn_query.filter(Employee.location_id == location_id)
        ret_query = ret_query.filter(EmployeeReturnRequest.location_id == location_id)
    if employee_id:
        txn_query = txn_query.filter(EmployeeStockTransaction.employee_id == employee_id)
        ret_query = ret_query.filter(EmployeeReturnRequest.employee_id == employee_id)
    if product_id:
        txn_query = txn_query.filter(EmployeeStockTransaction.product_id == product_id)
        ret_query = ret_query.filter(EmployeeReturnRequest.product_id == product_id)
    if txn_type:
        txn_query = txn_query.filter(EmployeeStockTransaction.transaction_type == txn_type)
    if status_filter:
        ret_query = ret_query.filter(EmployeeReturnRequest.status == status_filter)
    if date_from:
        txn_query = txn_query.filter(EmployeeStockTransaction.created_at >= date_from)
        ret_query = ret_query.filter(EmployeeReturnRequest.requested_at >= date_from)
    if date_to:
        txn_query = txn_query.filter(EmployeeStockTransaction.created_at <= date_to)
        ret_query = ret_query.filter(EmployeeReturnRequest.requested_at <= date_to)

    transactions = txn_query.order_by(EmployeeStockTransaction.created_at.desc()).limit(500).all()
    returns = ret_query.order_by(EmployeeReturnRequest.requested_at.desc()).limit(500).all()

    if request.args.get("export") == "csv":
        data = [(
            t.created_at.strftime("%Y-%m-%d %H:%M"), t.employee.employee_code, t.employee.user.full_name,
            t.employee.location.name, t.product.name, t.transaction_type,
            t.quantity_before, t.quantity_change, t.quantity_after, t.performer.full_name, t.reason or "",
        ) for t in transactions]
        return _csv_response("employee_stock_report.csv", [
            "Date", "Employee ID", "Employee", "Location", "Product", "Type",
            "Qty Before", "Change", "Qty After", "Performed By", "Reason",
        ], data)

    locations = Location.query.filter(Location.id.in_(loc_ids)).all() if loc_ids is not None else Location.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.employee_code).all()
    return render_template(
        "reports/employee_stock.html", transactions=transactions, returns=returns,
        locations=locations, products=products, employees=employees,
        location_id=location_id, employee_id=employee_id, product_id=product_id,
        txn_type=txn_type, status_filter=status_filter, date_from=date_from, date_to=date_to,
    )
