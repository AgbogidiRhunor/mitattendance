# MIT Meeting Attendance Management System

Django 5.2 + PostgreSQL, server-rendered templates, vanilla JS, custom white/grey CSS. No frontend frameworks or CDNs.

## Roles
- **User** – registers (full name, student ID, password), sees own stats and history (finalized meetings only).
- **Usher** – member of the `Usher` group (permission `meetings.take_attendance`): records attendance for open sessions.
- **Admin** – Django superuser: sessions, finalization, users/roles, corrections, audit log, reports, CSV export.
Everyone (admins and ushers included) appears in the attendance list and has their own attendance recorded.

## 1. Setup
Prerequisites: Python 3.11+, PostgreSQL 14+.

```bash
# PostgreSQL (psql as a superuser)
CREATE USER mit_user WITH PASSWORD 'strong-password';
CREATE DATABASE mit_attendance OWNER mit_user;

python -m venv .venv
.venv\Scripts\activate          # Windows;  Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env  -> then edit it
python manage.py migrate
python manage.py createsuperuser   # prompts: student ID, full name, password
python manage.py runserver
```
For local development set `DJANGO_DEBUG=True` in `.env`. Environment variables are listed in `.env.example`
(`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_TIME_ZONE`, `DB_*` or `DATABASE_URL`, ...). Generate a secret with
`python -c "import secrets; print(secrets.token_urlsafe(60))"`.

## 2. Admin account and ushers
There is no admin registration page. The first admin is created with `createsuperuser` (above); it can sign in to the
app at `/` (admin pages under `/manage/`) and to Django Admin at `/django-admin/`.
To appoint ushers: the person registers normally, then an admin opens **Users** (`/manage/users/`), searches, and clicks
**Make usher** (or **Remove usher**). The same page can grant/remove admin; the last active admin cannot be removed.

## 3. Workflow
1. Admin creates a session (title, date, opens at, closes at). Times use `DJANGO_TIME_ZONE` (default `Africa/Lagos`).
2. Between opening and closing time, ushers open **Take attendance**, search/paginate, tick people, and **Save attendance**.
   Selections apply to the current page only (the browser warns about unsaved ticks). Saved rows are locked.
3. After closing, the admin may **Finalize** (explicit). Only finalized sessions count in statistics.
4. Mistakes: admin opens the session → **Correct** → mark present/absent with a mandatory reason. Allowed for closed and
   finalized sessions only; each change is written to the immutable audit log (**Audit**).

Statuses: Scheduled → Open → Closed → Finalized. Admin may also **Close now** (scheduled/open) and edit scheduled/open sessions.
Definitions: eligible = active accounts (plus any inactive account with a record for that session); absences = eligible − attendees;
percentage = attendees ÷ eligible × 100; personal missed = held − attended. Every finalized session applies to every account
(no per-user eligibility rules yet – a late registrant shows earlier meetings as missed).

## 4. Automatic closing
Enforced on the server at every submission: the clock (`closes_at`) is checked inside the transaction that locks the session
row, so nothing is ever recorded at/after the closing time, even if no job runs. Stored statuses are refreshed lazily when
pages load. Optionally persist them on a schedule:
`python manage.py close_due_sessions` (cron every minute, e.g. `* * * * * cd /app && .venv/bin/python manage.py close_due_sessions`;
on Render use a Cron Job). Finalization is never automatic.

## 5. Production
- `DJANGO_DEBUG=False`, real `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain`.
- TLS must terminate at a proxy that sets `X-Forwarded-Proto` (Render does). HTTPS redirect, secure cookies and HSTS are on automatically.
- `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
- Run: `gunicorn config.wsgi:application`. Static files are served by WhiteNoise.
- Render: set `DATABASE_URL` (or `DB_*`), build command above, start command `gunicorn config.wsgi:application`.
- Logging goes to stdout; errors show a generic 500 page (no stack traces) when `DEBUG=False`.
- Not included: login rate limiting – put one at the proxy or add `django-axes` if brute force is a concern.

## 6. Backup and restore
```bash
pg_dump -Fc -U mit_user -h localhost mit_attendance > backup_$(date +%F).dump
createdb -U mit_user mit_attendance_restored
pg_restore -U mit_user -h localhost -d mit_attendance_restored --clean --if-exists backup_2026-01-01.dump
```
Schedule the dump daily and store copies off the server; test a restore occasionally. Dumps contain personal data: keep them private.

## 7. Data retention
Attendance records and audit entries are kept indefinitely (they are the official record; foreign keys are `PROTECT`).
Accounts are deactivated (Django Admin → `is_active`) rather than deleted, which preserves history. Remove personal data only
by a documented, admin-approved process (e.g. at graduation) and after exporting the CSV reports you need.

## 8. Tests
```bash
python manage.py test      # needs PostgreSQL (the concurrency test uses row locks); 51 tests
```
