# Moksha Entry System

ID-card verification and QR entry for Moksha, NSUT's intercollege fest. Students register online with an ID card photo, get approved by OCR plus rules or by a reviewer, receive a signed QR pass by email, and are admitted at the gate offline.

Full plan: the "Moksha Entry System — 6-Day Build Spec" doc.

## Status

| Day | Area | State |
| --- | --- | --- |
| 1 | Schema, presigned uploads, `/registrations`, `/status`, re-upload, colleges list | **Done** (this branch) |
| 1 | Registration form + status page (Next.js) | To do (owner C) |
| 2 | OCR pipeline in `worker/`, decision rules, review endpoints and dashboard | To do |
| 3 | Pass signing (`api/app/signing.py` is ready), QR email | To do |
| 4 | Gate PWA, manifest, check-in sync | To do |

## Layout

```
api/            FastAPI app
  app/          config, db, models, schemas, services, routers/, signing.py, migrate.py
  migrations/   plain SQL, applied in order by `python -m app.migrate`
  tests/        pytest against a real Postgres
worker/         Arq worker (OCR pipeline lands here on day 2)
  templates/    one YAML per college; see _example.yaml
infra/          docker-compose.yml (Postgres, Redis, MinIO, API), Caddyfile
scripts/        gen_keys.py, seed_colleges.py, enqueue_pending.py
```

## Run locally

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml --env-file .env up --build
# API on http://localhost:8000 (docs at /docs), MinIO console on http://localhost:9001
DATABASE_URL=postgresql://moksha:moksha@localhost:5432/moksha python scripts/seed_colleges.py
```

Tests (need a Postgres you can wipe):

```bash
cd api && pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/moksha_test pytest
```

## API for the registration form

All bodies are JSON. Errors come back as `{"detail": "<message to show the student>"}`, or as FastAPI's 422 list for field errors.

1. `GET /colleges` → `[{id, name}]` for the dropdown. Add an "Other" option yourself.
2. `POST /uploads/presign` `{content_type, size}` → `{url, fields, key, expires_in}`.
   Upload the file with a multipart **POST** to `url`, sending every entry of `fields` first and the file last as `file`. JPG, PNG or HEIC only, max 8 MB.
3. `POST /registrations`:
   ```json
   {
     "name": "...", "college_id": 1, "college_other": null,
     "roll_no": "...", "course": "...", "email": "...", "phone": "...",
     "id_image_key": "<key from step 2>",
     "consent_entry": true, "consent_dataset": false,
     "consent_version": "2026-10-18.v1",
     "captcha_token": "<Turnstile token>"
   }
   ```
   Send exactly one of `college_id` or `college_other`. → `201 {id, status, status_token, status_url}`.
   `409` = email already registered, or the form is out of date (consent version changed). `429` = rate limited.
4. `GET /status/{token}` → `{name, college, status, message, reasons[], can_reupload, qr_token}`. `reasons` are already in plain words.
5. When `can_reupload` is true: `POST /status/{token}/reupload/presign` (same as step 2), upload, then `POST /status/{token}/reupload {id_image_key}`.

## Notes for the next days

- **Worker:** the API queues `process_registration(registration_id)` for every registration. Don't run the worker until the pipeline exists; it would consume jobs and fail. After it ships, run `scripts/enqueue_pending.py` to queue everything still pending. Keep any reasons already on a registration (`duplicate_roll`, `other_college`): they're set at registration time.
- **Duplicates:** at most one live (pending, processing or approved) registration per college and roll number, enforced by a unique index. A second one goes to `review` with `duplicate_roll`, and the first is flagged too.
- **Roll numbers** are stored normalised: uppercase, spaces and dashes removed. Write template regexes against that form.
- **Consent:** `CONSENT_VERSION` in `.env` must match what the form sends. Bump both whenever the wording changes.
- **Keys:** run `scripts/gen_keys.py` once. The signing key goes in the server's `.env`, never in git.
- Schema additions beyond the spec: `colleges.slug`, `colleges.allowed`, `registrations.college_other`, `registrations.college_email`, `registrations.client_ip`, `registrations.updated_at`, `audit_log.detail`.
