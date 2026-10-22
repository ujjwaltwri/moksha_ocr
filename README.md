# Moksha Entry System

ID-card verification and QR entry for Moksha, NSUT's intercollege fest. Students register online with an ID card photo, get approved by OCR plus rules or by a reviewer, receive a signed QR pass by email, and are admitted at the gate offline.

Full plan: the "Moksha Entry System — 6-Day Build Spec" doc.

## Status

| Day | Area | State |
| --- | --- | --- |
| 1 | Schema, presigned uploads, `/registrations`, `/status`, re-upload, colleges list | **Done** (this branch) |
| 1 | Registration form + status page | Website team, using this API. Reference pages in `examples/` |
| 2 | OCR pipeline in `worker/` and decision rules | **Done** (`day2-ocr`) |
| 2 | Review endpoints and review page (`/review`) | **Done** (`day3-passes-gate`) |
| 3 | Pass issuance (signed QR + gate thumbnail) and QR email | **Done** (`day3-passes-gate`) |
| 3–4 | Gate endpoints for the Flutter app, device tokens, admin page (`/admin`) | **Done** (`day3-passes-gate`) |
| 3–4 | Gate app (`app/`): build, phone tests | Built by Ujjwal; test against the real API |
| 0 | **Deployment** | **Not done**: see the checklist below |

## Staff pages

- **`/admin`**: sign in with `ADMIN_TOKEN`. Overview (registrations, passes, emails, gates), help desk (search by name, roll, email, phone or pass ID; approve after an in-person check; resend; revoke), gate phones (create a setup QR per phone; revoke), reviewers and admins (create a private login link each).
- **`/review`**: reviewers open their link. One case at a time with the card, the face crop and what OCR read next to what the student typed. Keys: **A** approve, **R** then **1–5** reject with a reason, **U** ask for a new photo, **J** skip. Name and roll number can be corrected before approving. Two reviewers never get the same case; a claimed case returns to the queue after 10 minutes.

## Passes and email

- Approval (by the worker or a reviewer) queues `issue_pass`: the worker signs the QR token with `PASS_SIGNING_KEY`, makes a 160×160 WebP face thumbnail for the gate, then queues `send_pass_email`.
- Email goes out over SMTP with the QR inline, retried with backoff for about an hour; failures show on the admin page. **Send volume:** 20k+ emails needs a real provider (Amazon SES, Brevo paid, Mailgun, Postmark). Gmail and free tiers cap at a few hundred a day. Set up SPF, DKIM and DMARC for the sending domain.
- `GET /status/{token}` returns `qr_token` once the pass exists; the website draws it as a QR (see `examples/status.html`).

## Gate (for the Flutter app in `app/`)

`GET /gate/manifest` and `POST /gate/checkins` implement the contract in `app/lib/services/api.dart` (and `app/tools/mock_server.py`). Each phone uses its own device token from its setup QR. Check-ins are idempotent by the phone's id; a second admission of the same pass on the same day from another phone is returned in `conflicts`. Revoking a pass, or rejecting its registration, reaches phones on their next refresh (every 60 s).

**Measured here:** 25,000 passes download in about 3 s of server time per phone (expect 100–150 MB with real face thumbnails, gzip on; do the first download over Wi-Fi the night before); 8 lanes posting 2,000 admissions at once got every sync answered in under 150 ms.

## Deploy (DigitalOcean + AWS S3/SES)

Production runs on one DigitalOcean Droplet (Caddy for HTTPS, API, 2 OCR workers, Redis) with DigitalOcean managed Postgres, an AWS S3 bucket in Mumbai for photos, and Amazon SES for email. The step-by-step guide is the "Deployment Guide" doc; the short version:

```bash
git clone https://github.com/ujjwaltwri/moksha_ocr && cd moksha_ocr   # main is the deploy branch
cp .env.example .env && nano .env            # fill in every value (see comments)
T="docker compose -f infra/docker-compose.prod.yml"
$T run --rm tools python /scripts/gen_keys.py      # once; put both keys in .env
$T run --rm tools python /scripts/setup_bucket.py  # S3 bucket: private, encrypted, CORS
$T up -d --build                                    # migrations run on API start
$T run --rm tools python /scripts/seed_colleges.py
python scripts/smoke_test.py https://$API_DOMAIN you@example.com --admin-token <ADMIN_TOKEN>
```

Package versions are locked in `api/constraints.txt` and `worker/constraints.txt` (tested on Python 3.12, the image's base). Don't unpin OpenCV: version 5 removed the face detector the worker uses.

## Layout

```
api/            FastAPI app
  app/          config, db, models, schemas, services, routers/, signing.py, migrate.py
  migrations/   plain SQL, applied in order by `python -m app.migrate`
  tests/        pytest against a real Postgres
worker/         Arq worker: reads each ID card, decides approve / review / reject, issues and emails passes
  pipeline/     imaging (card, face, quality), ocr (RapidOCR), extract (fields + matching), decide (rules)
  templates/    one YAML per college; see _example.yaml
  tests/        unit, real-OCR pipeline tests on synthetic cards, and worker-job tests
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

The fest website hosts the form. Full spec: `docs/openapi.json` (also live at `/docs` on the API). Working plain-HTML reference pages: `examples/register.html` and `examples/status.html` (open with `?api=http://localhost:8000`).

All bodies are JSON. Errors come back as `{"detail": "<message to show the student>"}`, or as FastAPI's 422 list for field errors.

0. `GET /form-config` → consent wording and version, Turnstile site key, upload limits. Show the consent text from here; never hardcode it.
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

- **Worker:** the API queues `process_registration(registration_id)` for every registration. When the worker first starts, run `scripts/enqueue_pending.py` to queue anything registered before it existed. It keeps reasons set at registration time (`duplicate_roll`, `other_college`).
- **OCR engine:** RapidOCR, which runs PaddleOCR's PP-OCR models as ONNX on CPU. The models ship inside the pip package, so nothing downloads at runtime. About 1.5–2.5 s per card including face detection; one worker process handles roughly 1,500–2,000 cards an hour. Scale with more worker processes.
- **What the worker checks:** photo quality, college name on the card, the student's name (tolerates initials, middle names and OCR dropping spaces), roll number (exact, or one OCR slip on numbers of 8+ characters), roll format from the college template, validity date (only from a "Valid upto"-style label or a course session like 2022-26, never a birth date), a face on the card, and whether the same portrait already appears on another registration.
- **Verdicts:** approved only when every check passes with no reasons; rejected only for a clearly expired card or an uninvited college; everything else goes to review with reasons. A bad photo that explains failed reads becomes one reason, `poor_image`, so the student can re-upload. Results go in `registrations.ocr` for reviewers.
- **Duplicate cards** are detected by hashing the **portrait** on the card, not the whole card. Every card from one college shares a layout, so whole-card hashes collide.
- **Tests:** `cd worker && pip install -r requirements-dev.txt && TEST_DATABASE_URL=... pytest`. Synthetic cards use scikit-image's public-domain astronaut photo; no real student data is in the repo.
- **Duplicates:** at most one live (pending, processing or approved) registration per college and roll number, enforced by a unique index. A second one goes to `review` with `duplicate_roll`, and the first is flagged too.
- **Roll numbers** are stored normalised: uppercase, spaces and dashes removed. Write template regexes against that form.
- **Consent:** the wording lives in `api/app/consent.py` and reaches the form via `/form-config`. Bump `CONSENT_VERSION` in `.env` whenever the wording changes.
- **Website settings:** `CORS_ORIGINS` must list the website's origin, and the storage bucket needs a CORS rule for the same origin (POST). `STATUS_URL_TEMPLATE` is the website's status page URL with `{token}`.
- **Keys:** run `scripts/gen_keys.py` once. The signing key goes in the server's `.env`, never in git.
- Schema additions beyond the spec: `colleges.slug`, `colleges.allowed`, `registrations.college_other`, `registrations.college_email`, `registrations.client_ip`, `registrations.updated_at`, `audit_log.detail`.
