# Moksha Gate

Flutter app that volunteers use at the Moksha entry gates. It scans the QR pass a student got by email and checks the pass signature on the phone. The volunteer then compares the student's face with the photo from their ID card and taps **Admit** or **Deny**.

The gate keeps working with no internet. Each phone holds the day's pass list and syncs check-ins with the server every 5 seconds whenever it has a connection.

## How a scan works

1. The camera reads the QR.
2. The Ed25519 signature is checked against the public key built into the app. A forged or edited QR shows **INVALID PASS**.
3. The event ID and the fest day are checked.
4. The pass is looked up in the on-phone pass list. It can come back **not found**, **cancelled** or **already used**, and an already-used pass shows the gate and time of first entry.
5. A **green** screen shows the face cropped from the ID card, with the name, college and roll number. The volunteer taps **Admit**, or **Deny** with a reason.
6. The decision is saved on the phone and uploaded in the background. Other gates hear about it within seconds.

A red screen has no Admit button. When the pass is real, the red screen also shows whose pass it is, which helps spot shared screenshots.

## Project layout

```
lib/
  main.dart                 app start, sync on/off with app lifecycle
  config.dart               build-time settings: public key, event ID, PIN, fest days
  models.dart               pass, check-in, scan outcomes
  theme.dart                colours and button styles
  services/
    pass_verifier.dart      Ed25519 check of the QR token
    db.dart                 SQLite: pass list, check-ins, sync cursors
    api.dart                GET /gate/manifest, POST /gate/checkins
    sync.dart               5 s check-in sync, 60 s pass-list refresh
    gate_service.dart       scan → green/red decision; records Admit/Deny
    settings.dart           server, gate name, day; token in Keychain/Keystore
  screens/
    setup_screen.dart       scan a setup QR or type the details
    home_screen.dart        "ready to scan?" status, download pass list
    scan_screen.dart        camera with viewfinder, torch, counters
    result_screen.dart      full-screen green / red verdict
    history_screen.dart     this phone's entry log
    settings_screen.dart    PIN-protected: day, connection, clear for a new day
tool/patch_platforms.dart   adds permissions, signing, iOS keys after `flutter create`
tools/                      test key, test passes and a mock server (Python)
test/                       unit tests for pass verification
```

## First build (on your laptop)

You need Flutter 3.27 or newer (`flutter --version`).

```bash
cd moksha_gate
flutter create --org com.moksha --project-name moksha_gate --platforms android,ios .
dart run tool/patch_platforms.dart
flutter pub get
flutter test
```

`flutter create .` adds the `android/` and `ios/` folders and leaves the existing `lib/` alone. The patch script then:

- adds camera and internet permissions;
- locks the app to portrait and names it "Moksha Gate";
- sets minimum Android to 6.0 (API 23);
- sets up release signing;
- adds the iOS camera prompt text and local network keys, and declares no export encryption so each upload skips the compliance questions.

Don't use an org starting with `in.`, because `in` is a reserved word in Kotlin and Java.

## Try it before the backend exists

```bash
pip install cryptography "qrcode[pil]" pillow
python tools/make_test_passes.py      # test key, 40 fake students, test QRs
python tools/mock_server.py           # prints http://<laptop-ip>:8787/
```

Then:

1. Connect a phone to the same Wi-Fi as the laptop.
2. Run `flutter run` (a debug build).
3. On the phone, tap **Scan setup code** and scan the QR at `http://<laptop-ip>:8787/`.
4. Tap **Download pass list**, then **Start scanning**.
5. Open `/passes` on the laptop and scan each test QR. Every gate outcome is covered: valid, already used, cancelled, wrong day, wrong event, forged, not on the list, and not a pass.

Also try the following:

- **Two gates:** set up a second phone and admit the same pass on both. The second phone shows ALREADY USED as soon as it syncs.
- **Offline gates:** turn Wi-Fi off on both phones, admit the same pass on each, then turn Wi-Fi back on. Both phones flag a conflict.
- **Cancel a pass:** open `/revoke?id=<pass id>`. Within a minute the pass shows CANCELLED.
- **Load test:** run `python tools/make_test_passes.py --count 25000` to time the full pass-list download on a real phone.

Debug builds accept `http://` and the test key from the setup QR. Release builds accept only `https://` and the key compiled into the app.

## Release builds

The fest public key comes from the backend's `scripts/gen_keys.py`. Every release build needs it:

```bash
--dart-define=PASS_PUBLIC_KEY=<base64url public key> \
--dart-define=EVENT_ID=moksha26 \
--dart-define=ADMIN_PIN=<4-digit PIN for gate leads>
```

Raise `version:` in `pubspec.yaml` for every upload (for example, `1.0.0+2`, then `1.0.0+3`).

### Android: install the APK directly (fastest for the gate phones)

```bash
flutter build apk --release --dart-define=...
# build/app/outputs/flutter-apk/app-release.apk
```

Copy the APK to each phone and install it. Android will ask you to allow installs from that source.

### Android: Play Console internal testing

1. **Create an upload key (once).** Keep the `.jks` file and its passwords safe; you need them for every update.
   ```bash
   keytool -genkey -v -keystore ~/moksha-upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload
   ```
2. **Create `android/key.properties`.** Never commit this file.
   ```
   storePassword=...
   keyPassword=...
   keyAlias=upload
   storeFile=/full/path/to/moksha-upload.jks
   ```
3. **Build the app bundle:**
   ```bash
   flutter build appbundle --release --dart-define=...
   # build/app/outputs/bundle/release/app-release.aab
   ```
4. **Upload it.** In Play Console, create the app, then go to **Test and release → Internal testing**. Upload the `.aab`, add the volunteers' Gmail addresses as testers, and share the opt-in link.

Internal testing has no review and takes up to 100 testers. A personal account made after November 2023 can't go to public production until 12 testers have been in a closed test for 14 days in a row, so the public store isn't possible before the fest.

### iOS: TestFlight

You need:

- the Apple Developer Program ($99/year; enrolment can take a day or two);
- a Mac with Xcode, or a cloud Mac build service such as Codemagic.

Steps:

1. **Create the app record.** In App Store Connect, create the app with the bundle ID from Xcode (`com.moksha.mokshaGate`).
2. **Set up signing.** Open `ios/Runner.xcworkspace` in Xcode. Under **Signing & Capabilities**, pick your team.
3. **Patch the Podfile.** Run `flutter build ios --config-only`, then run `dart run tool/patch_platforms.dart` again. This sets the iOS minimum to 15.5.
4. **Build:** `flutter build ipa --release --dart-define=...`
5. **Upload** the `.ipa` from `build/ios/ipa/` with the **Transporter** app.
6. **Add testers.** In TestFlight, add volunteers as **internal testers**. Each one must first be added to your App Store Connect team (**Users and Access**). Internal builds arrive within minutes, with no review.

External testers (anyone outside the team) need Apple's beta review first, which usually takes a day or two.

## Fest-day checklist for each phone

- [ ] Latest build installed; setup code scanned; correct gate name and **day**
- [ ] Pass list downloaded on Wi-Fi the night before; count matches the admin page
- [ ] Test scan of a known pass shows green; tap **Deny → Other** so it isn't counted as an entry
- [ ] Battery above 80%, power bank attached
- [ ] Phone set to stay awake; the scan screen keeps the screen on by itself
- [ ] After the last day: **Settings → Clear for a new day** once everything shows uploaded

## Server contract

The app expects these two endpoints, with `Authorization: Bearer <device token>`:

```
GET /gate/manifest?since=<cursor>&limit=1000
→ { "passes": [ { "id", "name", "college", "roll_no",
                  "thumb_b64",        // WebP/JPEG face crop, base64
                  "revoked", "updated_at" } ],
    "next_cursor": "...", "has_more": true, "total": 24812 }

POST /gate/checkins
← { "device_id", "gate", "since": "<cursor or null>",
    "checkins": [ { "id", "pass_id", "scanned_at", "result", "reason", "day" } ] }
→ { "accepted": ["<id>", ...],          // stored (send repeats again safely)
    "conflicts": ["<id>", ...],         // admitted here after another gate
    "remote": [ { ...check-ins from other devices since the cursor... } ],
    "next_since": "<cursor>" }
```

`result` is one of `admitted`, `denied` or `duplicate`. `since` and `next_since` are opaque cursors; the mock server uses a sequence number. `tools/mock_server.py` is a working reference implementation.

Setup QR shown on the admin page:

```json
{"t":"moksha-gate-setup","url":"https://api…","token":"<device token>","gate":"Gate 2","day":1}
```

## Notes for the backend team

- **Thumbnail size:** the spec's 96×96 thumbnails look soft at the size the green screen shows them. 160×160 WebP at quality 70 is about 6–8 KB, so 25k passes come to roughly 175 MB. Alternatively, download only the day's passes.
- **Duplicate check-ins:** the app may send the same check-in more than once after a timeout. Keep the check-in `id` unique and treat repeats as accepted.
