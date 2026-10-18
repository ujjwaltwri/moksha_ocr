import 'package:uuid/uuid.dart';

import '../config.dart';
import '../models.dart';
import 'db.dart';
import 'pass_verifier.dart';
import 'settings.dart';
import 'sync.dart';

/// Turns a scanned QR into a green or red screen, and records decisions.
/// Everything here runs on the phone, with no network.
class GateService {
  GateService(this._db, this._settings, this._sync);

  final GateDb _db;
  final Settings _settings;
  final SyncService _sync;

  /// Null when no valid public key is available: scanning is blocked.
  PassVerifier? verifier;

  static const _uuid = Uuid();

  Future<ScanOutcome> evaluate(String raw) async {
    final v = verifier;
    if (v == null) {
      throw StateError('No pass public key configured in this build');
    }

    final result = await v.verify(raw);
    if (result.error == VerifyError.malformed) {
      return const ScanOutcome(ScanStatus.notAPass);
    }
    if (result.error == VerifyError.badSignature) {
      return const ScanOutcome(ScanStatus.invalidSignature);
    }
    final token = result.token!;

    if (token.eventId != AppConfig.eventId) {
      return ScanOutcome(ScanStatus.wrongEvent, token: token);
    }

    final pass = await _db.getPass(token.passId);
    final day = _settings.day;

    if (!token.days.contains(day)) {
      return ScanOutcome(ScanStatus.wrongDay, token: token, pass: pass);
    }
    if (pass == null) {
      return ScanOutcome(ScanStatus.notFound, token: token);
    }
    if (pass.revoked) {
      return ScanOutcome(ScanStatus.revoked, token: token, pass: pass);
    }
    final first = await _db.firstAdmission(pass.id, day);
    if (first != null) {
      return ScanOutcome(ScanStatus.alreadyUsed,
          token: token, pass: pass, firstEntry: first);
    }
    return ScanOutcome(ScanStatus.valid, token: token, pass: pass);
  }

  /// The volunteer tapped Admit.
  Future<void> admit(ScanOutcome o) =>
      _record(o, CheckinResult.admitted, null);

  /// The volunteer tapped Deny on a green screen, with a reason.
  Future<void> deny(ScanOutcome o, String reason) =>
      _record(o, CheckinResult.denied, reason);

  /// A red screen for a real pass is logged too, so the help desk can see
  /// repeat attempts. Forged or unreadable codes have no pass ID to log.
  Future<void> logRejected(ScanOutcome o) async {
    if (o.token == null || o.canAdmit) return;
    await _record(
      o,
      o.status == ScanStatus.alreadyUsed
          ? CheckinResult.duplicate
          : CheckinResult.denied,
      o.reasonCode,
    );
  }

  Future<void> _record(
      ScanOutcome o, CheckinResult result, String? reason) async {
    await _db.insertCheckin(Checkin(
      id: _uuid.v4(),
      passId: o.token!.passId,
      deviceId: _settings.deviceId,
      gate: _settings.gate,
      scannedAt: DateTime.now(),
      result: result,
      reason: reason,
      day: _settings.day,
    ));
    // Push it now so the other gates hear about it within seconds.
    _sync.syncNow();
  }
}
