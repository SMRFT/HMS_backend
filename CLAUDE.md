# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Django REST backend for a Hospital Management System (Shanmuga Hospital / HMS). Single Django app (`hospital`) exposing REST endpoints for patient registration, billing, pharmacy/inventory, admissions, rooms, insurance, HR, reporting, etc. MongoDB is the datastore, accessed through `djongo` (Django ORM syntax translated to Mongo) with some raw `pymongo`/`mongoengine` usage in places.

## Running the project

```bash
python manage.py runserver 0.0.0.0:2609       # dev server (project standard port is 2609, not 8000)
python manage.py makemigrations hospital
python manage.py migrate
```

`manage.py` picks the settings module from `ENV_CLASSIFICATION` (env var, loaded via `.env`/`dotenv`):
- unset or `local` → `shanmugahospital_backend.settings`
- `prod` → `shanmugahospital_backend.settings-prod`
- `test` → `shanmugahospital_backend.settings-test`

Required env vars (see `.env`, not committed): `GLOBAL_DB_HOST`, `HMS_DB_NAME`, `ALLOWED_HOSTS`, `EMAIL_HOST`/`EMAIL_PORT`/`EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD`, `HMS_HR_EMAIL`/`HMS_HR_EMAIL_PASSWORD`, `WHO_ICD_CLIENT_ID`/`WHO_ICD_CLIENT_SECRET` (WHO ICD-11 API integration), `BOTIFY_API_KEY`/`BOTIFY_TEMPLATE_NAME`/`WHATSAPP_SENDER_NUMBER` (WhatsApp messaging).

There is no real automated test suite — `hospital/tests.py` is the unmodified Django boilerplate. Don't assume `manage.py test` exercises meaningful coverage; verify behavior manually against the running server instead.

### Background workers

Two long-running management commands act as daemons (started alongside the web server, not via a task queue/celery):

```bash
python manage.py send_pending_payments_report --daemon    # daily internship-payment email report (10:00 AM IST)
python manage.py send_licence_expiry_emails --daemon --interval 86400
```

`start_services.sh` (Linux) and `run_all.ps1` (Windows) launch the Django server plus these workers together; that's the standard way this app is deployed on a box, not behind Docker/Celery in production.

### Docker

`Dockerfile` builds a Python 3.11 image with `tesseract-ocr` and `poppler-utils` (needed for the OCR feature in `chandra_ocr.py`, which reads scanned documents/PDFs via `pytesseract`/`pdf2image`). `docker-compose.yml` / `docker-compose.prod.yml` / `docker-compose.server.yml` / `docker-compose.libs.yml` are variants for different deployment targets.

## Architecture

### Routing

- `shanmugahospital_backend/urls.py` is the root URLconf. It mounts the same `hospital.urls` include twice: once at `/` and once at `/_b_a_c_k_e_n_d/HMS/` — the latter prefix is the one actually used by the frontend and by the permission map (see below). New endpoints only need to be added once in `hospital/urls.py`; both mounts pick them up automatically.
- `hospital/urls.py` imports view modules from `hospital/Views/` (note the capitalized directory) as well as the top-level `hospital/views.py`. When adding a new feature area, prefer adding a new module under `hospital/Views/` (optionally its own subpackage, e.g. `hospital/Views/Insurance/` with its own `models.py`/`serializer.py`) and wiring it into `hospital/urls.py`, following the existing pattern rather than growing `hospital/views.py` or `hospital/models.py` further.

### Data layer

- `hospital/models.py` holds the primary schema (~65 models) using `djongo.models`, all as MongoDB collections under one logical "HMS" database. Most inherit `AuditModel` (`hospital/models.py:10`), which provides `created_by`/`created_date`/`lastmodified_by`/`lastmodified_date` plus **multi-tenancy fields**: `branch_code`, `outlet_code`, `hospital_code`. Almost every query and write path is expected to be scoped by these codes — check how neighboring views filter before assuming a query is hospital/branch-agnostic.
- Some feature subpackages under `hospital/Views/<Feature>/` define their own `models.py`/`serializer.py` (e.g. `Assets`, `Insurance`, `Complaints`, `Stores`) rather than adding to the central `hospital/models.py`. These still subclass `AuditModel` from the parent `hospital.models`.
- `hospital/Views/mongo_utils.py` has small helpers (`serialize_mongo_doc(s)`) for converting raw pymongo `_id` fields to a JSON-friendly `id` field when a view bypasses the ORM and talks to `pymongo`/`mongoengine` directly.

### Auth & permissions

- Authentication/authorization is handled by an external package, `pyauth` (installed from `git+https://github.com/ashokkumarta/pyauth.git`, not part of this repo). Views use `@permission_classes([HasRoleAndDataPermission])` from `pyauth.auth`; some intentionally public endpoints use `AllowAny` instead (e.g. patient-facing endpoints).
- `hospital/auth/permissions_map.py` defines `PAGE_MAPPING`, a dict of URL regex → page code (e.g. `HMS-P-AIN`). `pyauth` loads this file by convention (log output confirms `Loading permissions from: ./hospital/auth/permissions_map.py`) to resolve which "page" a request belongs to, then checks the caller's role/page permissions against that code. When adding a new endpoint that should be permission-gated, add a matching regex entry here — otherwise `HasRoleAndDataPermission` won't know which page code to check.
- Request-level identity/tenancy is passed as conventionally-named fields, both as headers and as body/query params, e.g. `auth-user-id`, `auth-hospital-code`, `auth-branch-code`, `auth-outlet-code`, `auth-employee-name`. Views read these with an `or`-chained fallback (`request.data.get(...) or request.headers.get(...) or "system"`) — follow this pattern for new endpoints rather than trusting only one source.
- `hospital/middleware.py` (`SessionEnforcementMiddleware`) enforces single-device login by comparing an `X-Session-Token` header against a stored `UserSession` record and force-logging-out on mismatch; it fails open on DB errors. Note this middleware class is not currently wired into `MIDDLEWARE` in `shanmugahospital_backend/settings.py` — check whether it's actually active before relying on its behavior.

### Response conventions

Views generally return `rest_framework.response.Response` with a `{"success": bool, "data": ...}` or `{"success": bool, "error": str}` shape wrapped in a broad `try/except`. Follow this shape for consistency when adding new endpoints in the same module.

### Reporting/email

Several `Views/Reports/` and `Views/AccountsReport/` modules plus the management commands under `hospital/management/commands/` generate scheduled email reports (pending payments, licence expiry, marketing/room-occupancy reports) using `EMAIL_BACKEND = hospital.email_backend.Python312EmailBackend` (a custom backend, not Django's default SMTP backend — check there if outgoing email behaves unexpectedly).

## Notes on repo state

- `append_views.py` (repo root) and `hospital/temp_views_append.py` are one-off scratch scripts used to append generated code into `views.py`/model files during past feature additions — they are not part of the app's runtime and don't need to be kept in sync with anything.
- `db.sqlite3` and `db_info.txt` at the repo root are stale artifacts (the real database is MongoDB per `GLOBAL_DB_HOST`); don't treat them as sources of truth for schema.
