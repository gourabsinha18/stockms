# Multi-Branch Stock Management System

A production-oriented inventory/stock management platform for a Bolpur-headquartered
multi-branch business (Bolpur, Suri, Rampurhat, Islampur, and future locations).
**No sales/POS/customer functionality** — stock only, per spec.

Built with Flask + SQLAlchemy + Jinja2 + Bootstrap 5.

## What's implemented

- **Roles & access control**: Main Admin, Stock Manager (location-scoped), Employee
  (location-scoped). All authorization is enforced server-side (`permission_service.py`),
  never just hidden in the UI.
- **Product hierarchy**: Unit → Company/Brand → Category → Product, fully database-driven
  (no hard-coded EFL/Aquaguard/etc. — those are seeded as *example* data you can edit/delete).
- **Stock operations**, each with its own approval lifecycle where the spec calls for it:
  - Stock In / Receiving
  - Stock Transfer: `Requested → Approved → Dispatched → Received → Completed` (or `Rejected`)
  - Stock Adjustment: request → approve/reject, full previous/new quantity trail
  - Stock Return: Employee → Stock Manager → Main Admin → stock updated
- **Immutable stock ledger** (`StockMovement`) — every quantity change anywhere in the
  system is ledgered. Corrections happen via new adjustments, never edits to history.
- **Centralized stock service** (`app/services/stock_service.py`) is the *only* code
  path allowed to change `LocationStock.quantity`. It's atomic, revalidates stock at
  approval time, and refuses to let anything go negative.
- **Approval engine**: generic `ApprovalLog` table + per-module status fields, so new
  request types can be added without inventing new approval logic.
- **Audit log**: separate from the approval log; records logins, CRUD on
  locations/catalog/users, and every approve/reject/dispatch/receive action.
- **Notifications**: in-app, per-user, triggered on request creation/approval/rejection.
- **Reports**: location-wise, product-wise, unit/brand/category, low-stock, movement,
  stock-in, transfer, adjustment, return — each with CSV export.
- **Security basics**: password hashing (Werkzeug), CSRF protection (Flask-WTF) on every
  mutating form, login rate-limiting (Flask-Limiter), session cookies set HttpOnly/SameSite,
  basic security headers, and location/role checks re-validated on every server-side action
  (never trusting an ID from the client).

## What's intentionally out of scope for now

These weren't built yet — happy to add them next:

- Concurrency-hardening beyond SQLAlchemy's `with_for_update()` (works well on
  Postgres/MySQL; SQLite ignores row locks, fine for dev/demo, not for concurrent
  production writes — see "Moving to Postgres" below)
- Automated tests (pytest) — everything so far has been verified manually end-to-end
  via curl (see "What was tested" below), but there's no test suite yet
  - PDF export (CSV is done everywhere reports support export)
- Email delivery for notifications (currently in-app only)
- Password reset via email (accounts are admin-provisioned; there's a change-password
  flow but no self-serve "forgot password" email flow yet)
- Bulk import/export of catalog data

## Getting started

```bash
cd stockms
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python seed.py     # creates DB, locations, roles, sample users & catalog
./venv/bin/python run.py      # starts dev server on http://127.0.0.1:5000
```

### Seeded logins (change these immediately — they're for first login only)

| Role          | Username        | Password         | Scope           |
|---------------|-----------------|------------------|-----------------|
| Main Admin    | `admin`         | `Admin@12345`    | All locations   |
| Stock Manager | `suri_manager`  | `Manager@12345`  | Suri only       |
| Employee      | `suri_employee` | `Employee@12345` | Suri only       |

The seed script also creates the five locations (Bolpur, Suri, Rampurhat, Islampur,
Others) and a sample Unit → Brand → Category → Product chain (EFL → Aquaguard →
Commercial Series → one sample product) purely as a working example — all of it is
editable/deletable through the UI, none of it is hard-coded into the app logic.

## What was tested

Everything below was run against a real running instance in this environment
(not just eyeballed):

- Login / logout / CSRF-protected forms across every module
- Stock In: receiving increases the ledger and current stock correctly
- Full transfer lifecycle: request → approve → dispatch (source decreases) → receive
  (destination increases) — verified total quantity is conserved at every step
- Stock adjustment: approval correctly applies signed quantity change and updates the ledger
- Two-stage stock return: verified stock does **not** move after the Stock Manager's
  review, and only moves after the Main Admin's final approval
- Negative-stock protection: an over-large transfer and an over-large negative
  adjustment were both rejected with a clean error message and zero state change
- Location-level isolation: logged in as the Suri Stock Manager and confirmed
  403 Forbidden on Bolpur's location page and on Main-Admin-only pages
- Role restrictions: logged in as an Employee and confirmed 403 on Stock In and
  Audit Logs
- Audit log: confirmed LOGIN, CREATE, APPROVE, DISPATCH, RECEIVE entries are all
  recorded with user, timestamp, and before/after values
- CSV export on the stock movement history report

## Moving to PostgreSQL for production

The schema was written in plain SQLAlchemy with no SQLite-specific types, so switching
is a one-line config change:

```bash
export DATABASE_URL="postgresql://user:password@host:5432/stockms"
```

`config.py` already reads `DATABASE_URL` from the environment. On Postgres,
`with_for_update()` calls in `stock_service.py` will start taking real row locks,
which is what makes concurrent transfer/adjustment/return approvals safe under load —
on SQLite they're currently a no-op (fine for single-user dev/testing).

## Project layout

```
stockms/
  config.py                  # env-driven config (SECRET_KEY, DATABASE_URL, ...)
  run.py                     # dev entrypoint
  seed.py                    # creates schema + seed data
  requirements.txt
  app/
    __init__.py               # app factory, blueprint registration, error handlers
    extensions.py              # db, login_manager, csrf, limiter
    models.py                  # every table in the spec's Section 19 list
    services/
      stock_service.py         # THE place stock quantities change (atomic, ledgered)
      permission_service.py    # role + location authorization
      audit_service.py
      notification_service.py
    blueprints/                # one per sidebar section: auth, main, locations,
                                # catalog, stock, transfers, adjustments, returns,
                                # approvals, users, reports, notifications, audit
    templates/                 # Jinja2 + Bootstrap 5, mirrors blueprint structure
    static/css/app.css
```

## Suggested next steps

1. Add a pytest suite covering the `stock_service` functions directly (they're pure
   enough to unit test without spinning up the Flask app).
2. Add PDF export for reports (the pdf skill/library can slot into the existing
   CSV-export pattern in `reports/routes.py`).
3. Wire up email notifications (Flask-Mail) alongside the existing in-app ones.
4. Add a proper "forgot password" flow.
5. If you want barcode/QR scanning or a mobile app later (Section 24), the current
   service-layer separation means those can hit `stock_service.py` directly without
   touching the web routes.
