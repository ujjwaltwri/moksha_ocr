# Moksha Entry System: project context for Claude Code

This file hands over context from the claude.ai chats where the system was designed and built:
- **"OCR solution for college fest":** design, the backend API, the OCR worker and the website-team contract.
- **The gate-app chat:** the Flutter scanner app.

Read this first. When it disagrees with older notes, this file wins. Last updated Oct 18, 2026 (day 0/1 of the 6-day plan).

## What we're building

This is an entry system for **Moksha**, NSUT's intercollege fest: about 20k–30k students from DU and engineering colleges, with the **fest on day 6, around Oct 24, 2026**. The professor wants it generic and multi-tenant so it can later become a verification API or a startup. Moksha is tenant #1. For this week, build only what Moksha needs.

**The core idea:** do all the heavy verification *before* the fest, so the gate check takes about 5 seconds.

1. **Register.** The student registers online with name, college, roll number, email and an **ID card photo**, plus consent checkboxes. The website team builds the form against our API.
2. **Verify.** A worker runs OCR on the card, checks name, roll number, college, validity and duplicates, and decides **approve / review / reject**. It approves only clean cases and rarely rejects; everything else goes to human review.
3. **Issue the pass.** An approved student gets an **Ed25519-signed QR pass** by email. The same QR is shown on their status page.
4. **Enter.** At the gate, a volunteer's phone (the Flutter app) verifies the signature **offline** and shows the **face cropped from the ID card**. The volunteer compares faces and the physical card, then taps Admit or Deny. Re-entry uses wristbands, one colour per day.

**Out of scope until after the fest:** live selfie and liveness check, email OTP, face matching, the VLM extractor, the public `/v1` multi-tenant API, rotating QR codes and Kubernetes.

**Design docs (Claude Docs, owned by Zenoharsh):**
- **6-Day Build Spec**, the plan for this week: https://claude.ai/code/artifact/e2dae566-379f-44c7-88c9-e0b6b1af51b5
- **End-to-End Design**, the full product after the fest: https://claude.ai/code/artifact/fc957092-237d-46f6-ad04-91525201a2bf
- **Registration API guide for the website team:** https://claude.ai/artifact/EDkjBko82c48uRHNP9qV1P

## People

- **Zenoharsh:** leads the project; drives the backend and OCR work.
- **Ujjwal:** gate app; owns GitHub repo `ujjwaltwri/moksha_ocr`.
- **Website team (college):** builds the registration form and status page against our API.
- **Professor:** assigned the project. Code and data ownership (NSUT, professor or team) still has to be agreed in writing.

## Repository: github.com/ujjwaltwri/moksha_ocr

| Branch | Contents | State |
|---|---|---|
| `day1-registration` (default) | FastAPI app, schema, registration/status/upload endpoints, `/form-config`, pass signing, scripts, Docker Compose, reference HTML pages, OpenAPI spec | Pushed (55a744a); 15 tests pass |
| `day2-ocr` | OCR worker: imaging, RapidOCR, matching, decision rules, duplicate-card check | Pushed (b562c45); 26 tests pass |
| `main` | `day2-ocr` + the Flutter gate app in `app/` | Pushed (88ccda9) |
| `day4-deploy` | To merge into `main`, which is what gets deployed. From `day3-passes-gate`: production compose (Caddy HTTPS, 2 workers), sslmode handling, pinned versions (OpenCV 4.x), bucket setup + smoke-test scripts | Tested on Python 3.12 |
| `day3-passes-gate` | From `main`: review endpoints + `/review` page, pass issuance + QR email, gate endpoints, device/staff tokens, `/admin` page | 32 API + 31 worker tests pass; full chain and 25k load tested |

**Repository layout:**
```
api/            FastAPI app
  app/          config, db, models, schemas, services, auth, routers/ (registrations, review, gate, admin), static/ (review + admin pages)
  migrations/   plain SQL, applied in order by `python -m app.migrate`
  tests/        pytest against a real Postgres
worker/         Arq worker: OCR pipeline, decision rules, pass issuance and email
  templates/    one YAML per college (see _example.yaml)
infra/          docker-compose.yml (Postgres, Redis, MinIO, API), Caddyfile
scripts/        gen_keys.py, seed_colleges.py, enqueue_pending.py
examples/       register.html, status.html: reference pages for the website team
docs/           openapi.json
app/            Flutter gate scanner (see app/README.md)
```

**Gate app location:** it lives in `app/` on `main` (built on top of `day2-ocr`). Leave it there; the build scripts and README refer to that path.

## Backend (api/ + worker/)

**Stack:** FastAPI (Python 3.11), SQLAlchemy async, Postgres, Arq on Redis, S3-compatible storage (MinIO locally), RapidOCR (PaddleOCR models as ONNX, bundled, no downloads), OpenCV. Deployed as one VM with Docker Compose behind Caddy (HTTPS) and managed Postgres in Mumbai. **Not deployed yet.**

**Run locally:**
```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml --env-file .env up --build   # API :8000 (/docs), MinIO :9001
DATABASE_URL=postgresql://moksha:moksha@localhost:5432/moksha python scripts/seed_colleges.py
cd api && pip install -r requirements-dev.txt && TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/moksha_test pytest
cd worker && pip install -r requirements-dev.txt && TEST_DATABASE_URL=postgresql://... pytest
```

**Public API, used by the website form:**
- `GET /colleges` returns `[{id, name}]`.
- `GET /form-config` returns the consent wording and version, the Turnstile site key and the upload limits.
- `POST /uploads/presign` takes `{content_type, size}` and returns `{url, fields, key, expires_in}`. The browser uploads straight to the bucket with a multipart POST. JPG, PNG or HEIC, up to 8 MB.
- `POST /registrations` takes name, `college_id` *or* `college_other`, `roll_no`, course, email, phone, `id_image_key`, `consent_entry`, `consent_dataset`, `consent_version` and `captcha_token`.
  - Success: `201 {id, status, status_token, status_url}`.
  - `409`: the email is already registered, or the consent version is stale.
  - `429`: rate limited.
- `GET /status/{token}` returns `{name, college, status, message, reasons[], can_reupload, qr_token}`.
- Photo re-upload goes through the status token when `can_reupload` is true.

**Behaviours to keep:**
- Errors are `{"detail": "<message for the student>"}`.
- A duplicate roll number sends **both** registrations to review.
- **Consent:**
  - The wording lives in `api/app/consent.py` and is versioned; bump `CONSENT_VERSION` when it changes.
  - The dataset opt-in is a separate, unticked checkbox, and entry never depends on it.
  - Images of students who didn't opt in are deleted 30 days after the fest.
- **Settings:** `CORS_ORIGINS` must list the website's origin, and the bucket needs a matching CORS rule. `STATUS_URL_TEMPLATE` is the website's status page URL containing `{token}`.

**OCR worker (day2-ocr):**
- **Pipeline:**
  1. Decode the image, fixing EXIF rotation and converting HEIC.
  2. Quality check. A bad photo gets the reason `poor_image`, and the student can re-upload.
  3. Flatten the card only when the detected outline has ID-card proportions.
  4. Crop the face (Haar + CLAHE).
  5. OCR with RapidOCR.
  6. Match college, name and roll number.
  7. Check the roll-number format and the validity date.
- **Matching rules:**
  - The college name is matched ignoring spaces.
  - Name matching tolerates initials, middle names and merged words, and never accepts the father's name.
  - The roll number must match exactly, or with one OCR slip on long numbers.
- **Duplicate cards** are detected by hashing the **portrait**, not the whole card, because whole-card hashes collide across a college's shared layout.
- **Decision:** approve only clean cards. Reject only a clearly expired card or an uninvited college. Everything else goes to review with plain-language reasons.
- **Speed:** about 1.6 s per card, roughly 1,500–2,000 cards an hour per worker process.
- **Thresholds were tuned on synthetic cards only.** Re-tune them on real sample cards from opted-in students.
- **Before starting the worker on the server:** run `scripts/seed_colleges.py`, then `scripts/enqueue_pending.py`.

**Pass token (api/app/signing.py, already written):**
```
token   = base64url(body) + "." + base64url(Ed25519 signature over body bytes)   # no padding
body    = compact JSON with sort_keys, e.g. {"d":[1,2,3],"e":"moksha26","iat":1761300000,"p":"<pass uuid>","v":1}
```
The gate app verifies over the exact body bytes, so key order doesn't matter. The payload carries **no personal data**. `scripts/gen_keys.py` makes the key pair once. The private key lives only in the server's secrets, never in git. The public key is compiled into the gate app. **Check** that `gen_keys.py` prints the public key as raw 32 bytes in base64url, which is what the app expects; convert it if it doesn't.

## Gate app (gate_app/, Flutter)

- **Platforms:** one codebase for iOS (TestFlight) and Android (Play internal testing, or a directly installed APK). The public Play release is impossible before the fest: a new personal account needs 12 testers × 14 days.
- **Status: the code is complete but has never been compiled.** The original environment couldn't download the Flutter SDK. The Python test tools were run and work. Gate-app details are in `gate_app/README.md`.
- **First build:**
  ```bash
  cd gate_app
  flutter create --org com.moksha --project-name moksha_gate --platforms android,ios .
  dart run tool/patch_platforms.dart       # permissions, release signing, iOS keys, removes template test
  flutter pub get && flutter analyze && flutter test
  ```
  Don't use an org starting with `in.`, because `in` is a Kotlin/Java keyword.
- **Test without the backend:** run `python tools/make_test_passes.py && python tools/mock_server.py`. On the phone, scan the setup QR at `http://<laptop-ip>:8787/` (debug build), then scan the test passes at `/passes`.
- **Release build:** add `--dart-define=PASS_PUBLIC_KEY=<key> --dart-define=EVENT_ID=moksha26 --dart-define=ADMIN_PIN=<pin>`. Release builds accept only `https://`.
- **Key files:**
  - `lib/services/pass_verifier.dart`: the signature check.
  - `gate_service.dart`: the scan decision order. Malformed → bad signature → wrong event → wrong day → not on list → revoked → already admitted today → valid.
  - `sync.dart`: check-ins every 5 s, manifest refresh every 60 s.
  - `db.dart`: sqflite.
- **Packages:** `mobile_scanner` ^7, `cryptography`, `sqflite`, `http`, `shared_preferences`, `flutter_secure_storage` ^9, `wakelock_plus`. minSdk 23, iOS 15.5.
- **iOS:** run `flutter build ios --config-only` on the Mac, then run the patch script again so the Podfile minimum becomes 15.5. Then `flutter build ipa` and upload with Transporter. The Apple Developer account is needed and enrolment can take a day or two.

**Gate endpoints: the backend still has to build these.** The app implements this contract, and `gate_app/tools/mock_server.py` is a working reference.
```
GET  /gate/manifest?since=<cursor>&limit=1000     (Authorization: Bearer <device token>)
  → {"passes":[{"id","name","college","roll_no","thumb_b64","revoked","updated_at"}],
     "next_cursor":"…","has_more":bool,"total":int|null}
POST /gate/checkins
  ← {"device_id","gate","since":cursor|null,
     "checkins":[{"id","pass_id","scanned_at","result":"admitted|denied|duplicate","reason","day"}]}
  → {"accepted":[ids],"conflicts":[ids admitted after another gate],
     "remote":[check-ins from other devices since cursor],"next_since":"…"}
```
- `thumb_b64` is the face crop the worker already saves (`photo_crop_key`), sized **160×160 WebP**. 96×96 looks too soft at the gate.
- Treat a repeated check-in `id` as accepted, because phones retry.
- Admins create per-device tokens and can revoke them.
- The admin page shows a **setup QR** containing `{"t":"moksha-gate-setup","url":"https://…","token":"…","gate":"Gate 2","day":1}`.

## What's left (6-day plan)

| Day | Work | State |
|---|---|---|
| 0 | Deploy VM + managed Postgres + bucket + Caddy HTTPS; email service with SPF/DKIM/DMARC; generate the Ed25519 keys | **Not done. This blocks registration going live.** Needs the team's cloud account |
| 1 | Registration API | Done |
| 1 | Registration form + status page | Website team (they need our domain/CORS, status URL pattern and Turnstile keys) |
| 2 | OCR worker | Done |
| 2 | Review endpoints + `/review` page (keys A/R/U/J). Staff sign in with per-person token links from `/admin`, not Google sign-in | Done (`day3-passes-gate`) |
| 3 | Pass creation on approval, QR email over SMTP with retries, `email_sent_at`; admin stats + help-desk search/resend/approve/revoke | Done. No provider bounce webhooks: refused addresses and failures show on `/admin` |
| 3–4 | `/gate/manifest`, `/gate/checkins`, device tokens, setup QR on `/admin`; load tested at 25k passes and 8 lanes | Done |
| 3–4 | Gate app: first compile, phone tests, TestFlight/APK | Code written; needs build + testing |
| 5 | Dry run at the real gate with phones and test passes, including an offline test; registration closes; final manifest download | To do |
| 6 | Fest | |

## Decisions still open (settle with the organisers and professor)

- **Unreviewed cards at close:** help desk on the day, auto-approve on college + name match, or reject with an apology.
- **Fest dates, and per-day or all-days passes:** this sets the token's `d` field and the gate app's `AppConfig.festDays` and wristband colours.
- **College allowlist,** and whether "Other" colleges may register.
- **Sending domain:** DNS access for email.
- **Consent wording:** who approves it.
- **Reviewers:** 8–10, with their Google accounts. Expect 20–30% of cards in review, 5k–7.5k cards in total.
- **Ownership of code and data,** in writing.

## Working rules for Claude

- **Scope:** freeze it. Anything not in the 6-day plan waits until after the fest.
- **No real student data** in the repo or tests; use synthetic cards.
- **Secrets:** never commit them (`.env`, signing key, `android/key.properties`, `*.jks`).
- **Tests:** keep `api/` and `worker/` tests passing, and add tests with new endpoints.
- **Branches:** one branch per piece of work, from the latest branch.