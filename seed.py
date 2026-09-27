"""
Seed the database with initial data:
  - Locations: Bolpur, Suri, Rampurhat, Islampur, Others
  - Main Admin user
  - Sample Unit/Brand/Category hierarchy (EFL / Aquaguard etc.) as a starting example
  - One sample Stock Manager and Employee for testing

Run with: ./venv/bin/python seed.py
Safe to re-run: skips creation if data already exists.
"""
from app import create_app
from app.extensions import db
from app.models import (
    User, Location, Unit, Brand, Category, Product,
    StockManagerAssignment, Employee,
    ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER, ROLE_EMPLOYEE,
    gen_employee_code,
)

app = create_app()

with app.app_context():
    db.create_all()

    # --- Locations ---
    location_defs = [
        ("BOL", "Bolpur", "Bolpur Head Office"),
        ("SUR", "Suri", "Suri Branch"),
        ("RPH", "Rampurhat", "Rampurhat Branch"),
        ("ISP", "Islampur", "Islampur Branch"),
        ("OTH", "Others", "Other Locations"),
    ]
    locations = {}
    for code, name, address in location_defs:
        loc = Location.query.filter_by(code=code).first()
        if not loc:
            loc = Location(code=code, name=name, address=address, is_active=True)
            db.session.add(loc)
            db.session.flush()
            print(f"Created location: {code} - {name}")
        locations[code] = loc

    # --- Main Admin ---
    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(username="admin", email="admin@bolpur-hq.example", full_name="Main Administrator",
                    role=ROLE_MAIN_ADMIN, is_active=True)
        admin.set_password("Admin@12345")
        db.session.add(admin)
        db.session.flush()
        print("Created Main Admin user -> username: admin / password: Admin@12345 (CHANGE THIS IMMEDIATELY)")

    # --- Sample Stock Manager (Suri) ---
    manager = User.query.filter_by(username="suri_manager").first()
    if not manager:
        manager = User(username="suri_manager", email="suri.manager@bolpur-hq.example", full_name="Suri Stock Manager",
                       role=ROLE_STOCK_MANAGER, is_active=True)
        manager.set_password("Manager@12345")
        db.session.add(manager)
        db.session.flush()
        db.session.add(StockManagerAssignment(user_id=manager.id, location_id=locations["SUR"].id))
        print("Created Stock Manager -> username: suri_manager / password: Manager@12345")

    # --- Sample Employee (Suri) ---
    employee_user = User.query.filter_by(username="suri_employee").first()
    if not employee_user:
        employee_user = User(username="suri_employee", email="suri.employee@bolpur-hq.example",
                             full_name="Suri Employee", role=ROLE_EMPLOYEE, is_active=True)
        employee_user.set_password("Employee@12345")
        db.session.add(employee_user)
        db.session.flush()
        db.session.add(Employee(user_id=employee_user.id, location_id=locations["SUR"].id, stock_manager_id=manager.id if manager else None, employee_code=gen_employee_code()))
        print("Created Employee -> username: suri_employee / password: Employee@12345")

    db.session.commit()

    # --- Sample catalog: EFL / Eumexia Forben Ltd. hierarchy ---
    efl = Unit.query.filter_by(code="EFL").first()
    if not efl:
        efl = Unit(code="EFL", name="EFL - Eumexia Forben Ltd.", description="Eumexia Forben Ltd. unit", is_active=True)
        db.session.add(efl)
        db.session.flush()
        print("Created unit: EFL")

    kitchen_unit = Unit.query.filter_by(code="KCH").first()
    if not kitchen_unit:
        kitchen_unit = Unit(code="KCH", name="Kitchen Chimney", description="Kitchen chimney product line", is_active=True)
        db.session.add(kitchen_unit)
        db.session.flush()
        print("Created unit: Kitchen Chimney")

    aquaguard = Brand.query.filter_by(unit_id=efl.id, code="AQG").first()
    if not aquaguard:
        aquaguard = Brand(unit_id=efl.id, code="AQG", name="Aquaguard", is_active=True)
        db.session.add(aquaguard)
        db.session.flush()
        print("Created brand: Aquaguard (under EFL)")

    vacuum_brand = Brand.query.filter_by(unit_id=efl.id, code="VAC").first()
    if not vacuum_brand:
        vacuum_brand = Brand(unit_id=efl.id, code="VAC", name="Vacuum Cleaner", is_active=True)
        db.session.add(vacuum_brand)
        db.session.flush()
        print("Created brand: Vacuum Cleaner (under EFL)")

    db.session.commit()

    cat_commercial = Category.query.filter_by(brand_id=aquaguard.id, code="COMM").first()
    if not cat_commercial:
        cat_commercial = Category(brand_id=aquaguard.id, code="COMM", name="Commercial Series", is_active=True)
        db.session.add(cat_commercial)
        db.session.flush()
        print("Created category: Commercial Series (under Aquaguard)")

    cat_others = Category.query.filter_by(brand_id=aquaguard.id, code="OTH").first()
    if not cat_others:
        cat_others = Category(brand_id=aquaguard.id, code="OTH", name="Others", is_active=True)
        db.session.add(cat_others)
        db.session.flush()
        print("Created category: Others (under Aquaguard)")

    db.session.commit()

    sample_product = Product.query.filter_by(sku="AQG-COMM-001").first()
    if not sample_product:
        sample_product = Product(
            sku="AQG-COMM-001", name="Aquaguard Commercial RO 50L", category_id=cat_commercial.id,
            model="AC-50L", description="Commercial-grade RO water purifier, 50 litre capacity.",
            min_stock_level=2, reorder_level=5, cost_price=18500.00, is_active=True,
        )
        db.session.add(sample_product)
        print("Created sample product: AQG-COMM-001")

    db.session.commit()
    print("\nSeed complete.")
    print("Log in as Main Admin: admin / Admin@12345")
    print("IMPORTANT: change all default passwords before any real/production use.")
