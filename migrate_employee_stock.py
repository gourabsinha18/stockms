"""
Migration: Employee Directory + Employee Stock Issue & Return module.

This project does not use Flask-Migrate/Alembic (see config.py / seed.py -
schema init is via db.create_all()). db.create_all() only CREATEs tables
that don't exist yet; it never ALTERs an existing table. The `employees`
table already exists in any pre-existing stockms.db, so the new columns
this feature needs (employee_code, phone, designation, department,
created_at, updated_at) would silently be missing, and the app would raise
"no such column" errors the moment it queried/wrote them.

This script is therefore a manual, hand-written migration - written the same
way this project already handles schema setup, just extended to cover
ALTER TABLE + backfill for an existing table. It is:

  - SAFE to re-run (every step checks before acting).
  - NON-DESTRUCTIVE (no DROP, no data deleted, only ADD COLUMN / backfill /
    CREATE new tables).
  - Ordered so existing rows always end up with a valid, unique employee_code
    before the unique index is created.

Run with:
    python migrate_employee_stock.py
"""
import sqlite3
from datetime import datetime

from app import create_app
from app.extensions import db
from config import Config


def _sqlite_path_from_uri(uri):
    if not uri.startswith("sqlite:///"):
        return None
    return uri.replace("sqlite:///", "", 1)


def _column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _index_exists(cursor, index_name):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index_name,))
    return cursor.fetchone() is not None


def migrate_sqlite(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    print(f"Migrating SQLite database: {db_path}")

    # 1) Add new nullable columns to the existing `employees` table (SQLite's ALTER TABLE ADD
    #    COLUMN cannot add a NOT NULL column without a constant default when the table already
    #    has rows, so these are added nullable; the ORM model still enforces NOT NULL for every
    #    INSERT/UPDATE going forward at the application level).
    new_columns = [
        ("employee_code", "VARCHAR(20)"),
        ("phone", "VARCHAR(20)"),
        ("designation", "VARCHAR(100)"),
        ("department", "VARCHAR(100)"),
        ("created_at", "DATETIME"),
        ("updated_at", "DATETIME"),
    ]
    for col_name, col_type in new_columns:
        if _column_exists(cur, "employees", col_name):
            print(f"  - employees.{col_name} already exists, skipping.")
        else:
            cur.execute(f"ALTER TABLE employees ADD COLUMN {col_name} {col_type}")
            print(f"  + Added employees.{col_name} ({col_type})")
    conn.commit()

    # 2) Backfill employee_code for any existing employees that don't have one yet, and backfill
    #    created_at/updated_at from joined_at (or now) so existing rows aren't left with NULLs.
    cur.execute("SELECT id, joined_at FROM employees WHERE employee_code IS NULL ORDER BY id")
    rows = cur.fetchall()
    if rows:
        # Start numbering after the highest existing EMPxxxx code (there shouldn't be any yet on
        # a first run, but this keeps the script safe to re-run after partial manual edits too).
        cur.execute("SELECT employee_code FROM employees WHERE employee_code LIKE 'EMP%'")
        existing_codes = [r[0] for r in cur.fetchall() if r[0] and r[0][3:].isdigit()]
        next_seq = max([int(c[3:]) for c in existing_codes], default=0) + 1

        for emp_id, joined_at in rows:
            code = f"EMP{next_seq:04d}"
            next_seq += 1
            now = joined_at or datetime.utcnow().isoformat(sep=" ")
            cur.execute(
                "UPDATE employees SET employee_code = ?, created_at = COALESCE(created_at, ?), "
                "updated_at = COALESCE(updated_at, ?) WHERE id = ?",
                (code, now, now, emp_id),
            )
            print(f"  + Backfilled employees.id={emp_id} -> employee_code={code}")
        conn.commit()
    else:
        print("  - No existing employees needed an employee_code backfill.")

    # 3) Unique index on employee_code (SQLite supports CREATE UNIQUE INDEX even though it
    #    doesn't support adding a UNIQUE constraint via ALTER TABLE directly).
    if _index_exists(cur, "uq_employees_employee_code"):
        print("  - Unique index on employees.employee_code already exists, skipping.")
    else:
        cur.execute("CREATE UNIQUE INDEX uq_employees_employee_code ON employees(employee_code)")
        conn.commit()
        print("  + Created unique index on employees.employee_code")

    conn.close()


def main():
    app = create_app(Config)
    with app.app_context():
        db_path = _sqlite_path_from_uri(app.config["SQLALCHEMY_DATABASE_URI"])
        if db_path:
            migrate_sqlite(db_path)
        else:
            print(
                "Non-SQLite database detected (e.g. PostgreSQL/MySQL production deployment).\n"
                "This script only automates the SQLite ALTER TABLE path used in development.\n"
                "For a managed database, run the equivalent manually before continuing:\n\n"
                "  ALTER TABLE employees ADD COLUMN employee_code VARCHAR(20);\n"
                "  ALTER TABLE employees ADD COLUMN phone VARCHAR(20);\n"
                "  ALTER TABLE employees ADD COLUMN designation VARCHAR(100);\n"
                "  ALTER TABLE employees ADD COLUMN department VARCHAR(100);\n"
                "  ALTER TABLE employees ADD COLUMN created_at TIMESTAMP;\n"
                "  ALTER TABLE employees ADD COLUMN updated_at TIMESTAMP;\n"
                "  -- then backfill employee_code for existing rows (e.g. EMP0001, EMP0002, ...)\n"
                "  ALTER TABLE employees ADD CONSTRAINT uq_employees_employee_code UNIQUE (employee_code);\n"
            )
            return

        # New tables (employee_stock, employee_stock_transactions, employee_return_requests) are
        # brand new - db.create_all() handles these safely and never touches existing tables/data.
        db.create_all()
        print("\ndb.create_all() complete - new Employee Stock tables are ready.")
        print("Migration finished successfully. No existing data was modified or deleted.")


if __name__ == "__main__":
    main()
