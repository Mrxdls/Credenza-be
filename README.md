# Poornima University Faculty Achievements & Accreditation Portal

A production-grade Django 5 + Django REST Framework platform for managing faculty achievements (Journal Publications, Conference Proceedings, Patents, and FDP/Workshops), designed for **NAAC AQAR Criteria 3 (3.4.3–3.4.6)** and **NIRF** institutional reporting.

---

## 🚀 Key Features

### 1. Library-First, Clean Architecture
- **Admin Theme:** [`django-unfold`](https://github.com/unfoldadmin/django-unfold) — modern, responsive Tailwind CSS admin interface.
- **Audit Logging:** [`django-simple-history`](https://github.com/jazzband/django-simple-history) — full temporal change tracking on User, Activity, and Document models.
- **Excel Processing:** [`openpyxl`](https://openpyxl.readthedocs.io/) & [`django-import-export`](https://django-import-export.readthedocs.io/) — high-throughput, in-memory parsing with wrapped-line stitching and auto-format detection.
- **Database Indexing:** PostgreSQL GIN indexing on polymorphic JSON metadata (`GinIndex(fields=['metadata'])`).

### 2. Multi-Cloud Storage Engine (Local, AWS S3 & Cloudflare R2)
- Switchable via `.env` flag `STORAGE_BACKEND=local`, `s3`, or `r2`, and dynamically toggled in Admin -> SystemConfiguration.
- **Local:** Files stored under `media/proofs/{activity_id}/` and served during development.
- **AWS S3:** Uses `django-storages` + `boto3` with private ACLs and expiring presigned URLs.
- **Cloudflare R2:** Zero-egress S3-compatible object storage with signed presigned URLs and transparent Zstandard (`.zst`) compression.

### 3. Cloudflare D1 Serverless SQL Database & Storage Engine
- **Edge SQLite / D1 Backend:** Runs on Cloudflare's serverless D1 SQLite database at the edge (`DB_ENGINE=d1`).
- **Direct API Database Management:** Pure Cloudflare REST API v4 execution for reads, writes, batch transactions, table inspection, and schema migrations (`python manage.py d1_cli`) authenticated via API key/token—no Wrangler CLI required.

### 3. Multi-Proof Document Verification Invariant
- **1:N Relational Attachments:** Multiple proof documents (PDF reprints, acceptance letters, indexing screenshots, gazette notifications) linked per achievement.
- **Approval Guardrail:** An activity **cannot** be transitioned to `approved` status unless at least one verified proof attachment is linked. Batch actions and API endpoints enforce this invariant.
- **In-Browser Previews:** Embedded preview buttons and image thumbnails directly in Unfold Admin inlines.

### 4. Layered Institutional RBAC
- Superusers (`is_superuser=True`) are reserved strictly for DevOps / Root Admin.
- University institutional roles (`Dean`, `Head of Department`, `Department Coordinator`, `Faculty Member`) have strict departmental and module scoping via `InstitutionalRBACBackend`.
- **Peer Benchmarking Privacy:** Faculty can view peer activity volume counts per department (`GET /api/activities/metrics/department-counts/`), but individual titles and proof URLs remain private.

### 5. 1-Click NAAC AQAR Criteria 3 Multi-Tab Excel Export
- Generates a styled 4-tab Excel workbook formatted strictly according to NAAC guidelines:
  1. `NAAC 3.4.3 (Journals)`
  2. `NAAC 3.4.4 (Conferences)`
  3. `NAAC 3.4.5 (Patents)`
  4. `NAAC 3.4.6 (Participation)`
- Features deep-navy headers, cell borders, auto-adjusted column widths, and clickable hyperlinks to proof documents.

### 6. On-Demand CrossRef Bibliographic Auto-Enrichment
- Non-blocking, on-demand DOI lookup (`POST /api/activities/auto-enrich-doi/`) that fetches journal name, publisher, publication year, ISSN/ISBN, and author list from CrossRef.

---

## 🛠️ Quick Start

### 1. Environment Setup
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Database & Environment
Copy or update `.env`:
```ini
DEBUG=True
SECRET_KEY=poornima-portal-secret-key-2026
ALLOWED_HOSTS=*

# PostgreSQL Database
DB_NAME=poornima_achievements
DB_USER=postgres
DB_PASSWORD=root
DB_HOST=localhost
DB_PORT=5432

# Storage Toggle: 'local' or 's3'
STORAGE_BACKEND=local

# AWS S3 Settings (if STORAGE_BACKEND=s3)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=ap-south-1
AWS_S3_BUCKET=faculty-achivements-data
AWS_S3_PRESIGNED_EXPIRY=3600
```

### 3. Run Migrations & Seed Default Data
```bash
./venv/bin/python manage.py migrate
./venv/bin/python manage.py seed_data
```

### 4. Ingest University Excel Workbooks
```bash
./venv/bin/python manage.py import_legacy_excel --dir /path/to/workbooks
```
Automatically classifies and stitches multi-line author rows across all 4 files:
- `Conference Publication Data 2026 (From Jan 2026 to December 2026).xlsx`
- `Faculty Participation Data- session 2025-26 ODD& EVEN Semester.xlsx`
- `Journal Publication Data 2026 (From Jan 2026 to December 2026).xlsx`
- `Patent Publication Data 2026 (From Jan 2026 to Dec 2026).xlsx`

### 5. Run Automated Tests
```bash
./venv/bin/python manage.py test
```
Runs the full 21-test suite covering models, proof invariant guardrails, approval/rejection state machines, RBAC department scoping, peer metrics privacy, NAAC exports, CrossRef integration, and bulk ingestion.

### 6. Run Development Server
```bash
./venv/bin/python manage.py runserver 0.0.0.0:8000
```
Open [http://localhost:8000/admin/](http://localhost:8000/admin/) in your browser.

### 7. Cloudflare D1 SQL & R2 Storage Management (Pure REST API, No Wrangler Needed)
All operations use direct Cloudflare REST API v4 with your `CLOUDFLARE_D1_API_TOKEN`:
```bash
# Check D1 database and R2 bucket status
./venv/bin/python manage.py d1_cli --status
./venv/bin/python manage.py d1_cli --test-r2
./venv/bin/python manage.py d1_cli --test-all

# List remote tables and row counts in Cloudflare D1
./venv/bin/python manage.py d1_cli --tables

# Execute read query (SELECT)
./venv/bin/python manage.py d1_cli --read "SELECT id, username, email FROM accounts_user LIMIT 5;"

# Execute write query (INSERT / UPDATE / DELETE)
./venv/bin/python manage.py d1_cli --write "UPDATE accounts_user SET is_active=1 WHERE id=1;"

# Apply schema directly to Cloudflare D1 via API (no Wrangler needed)
./venv/bin/python manage.py d1_cli --apply-schema

# Or export schema to file, then apply via API
./venv/bin/python manage.py d1_cli --export-schema cloudflare_d1_schema.sql
./venv/bin/python manage.py d1_cli --apply-schema=cloudflare_d1_schema.sql

# Execute any SQL script file directly on D1 via API
./venv/bin/python manage.py d1_cli --execute-file=custom_seed.sql
```

---

## 👥 Default Accounts

| Role | Username | Password | Notes |
| :--- | :--- | :--- | :--- |
| **DevOps Superuser** | `admin` | `admin123` | Full root access across all apps |
| **Dept Coordinator** | `coordinator.ac` | `coordinator123` | Advance Computing Coordinator |
| **Head of Dept (HOD)** | `hod.ac` | `hod123` | Advance Computing HOD |
| **Imported Faculty** | `<emp_id>` | `poornima123` | Faculty created during bulk import |

---

## 📡 REST API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/activities/` | `GET`, `POST` | List & create activities (department-scoped) |
| `/api/activities/<id>/` | `GET`, `PUT`, `DELETE` | Retrieve, update, or remove activity record |
| `/api/activities/<id>/submit/` | `POST` | Transition from `draft` to `submitted` |
| `/api/activities/<id>/approve/` | `POST` | Approve activity (requires $\ge 1$ proof document) |
| `/api/activities/<id>/reject/` | `POST` | Reject activity (requires non-empty `reason`) |
| `/api/activities/bulk-import/` | `POST` | Ingest `.xlsx` or `.zip` archive via API |
| `/api/activities/metrics/department-counts/` | `GET` | Faculty peer counts without leaking titles/proofs |
| `/api/activities/export/` | `GET` | 1-Click NAAC AQAR Criteria 3 Excel Export |
| `/api/activities/auto-enrich-doi/` | `POST` | On-demand bibliographic lookup by DOI |
| `/api/documents/` | `GET`, `POST` | Upload and manage proof attachments (`multipart/form-data`) |
| `/api/sessions/` | `GET`, `POST` | Manage academic years/sessions |
