import 'dart:typed_data';

/// What is inside a signed QR pass. No personal data: the name and photo
/// come from the pass list downloaded to the phone.
class PassToken {
  const PassToken({
    required this.version,
    required this.passId,
    required this.eventId,
    required this.days,
    required this.issuedAt,
  });

  final int version;
  final String passId;
  final String eventId;
  final List<int> days;
  final int issuedAt;
}

/// One row of the pass list ("manifest") from GET /gate/manifest.
class PassRecord {
  const PassRecord({
    required this.id,
    required this.name,
    required this.college,
    this.rollNo,
    this.thumb,
    this.revoked = false,
    this.updatedAt,
  });

  final String id;
  final String name;
  final String college;
  final String? rollNo;
  final Uint8List? thumb;
  final bool revoked;
  final String? updatedAt;
}

enum CheckinResult { admitted, denied, duplicate }

/// One entry decision, made on this phone or synced from another gate.
class Checkin {
  const Checkin({
    required this.id,
    required this.passId,
    required this.deviceId,
    required this.gate,
    required this.scannedAt,
    required this.result,
    required this.day,
    this.reason,
    this.synced = false,
    this.remote = false,
    this.conflict = false,
  });

  final String id;
  final String passId;
  final String deviceId;
  final String gate;
  final DateTime scannedAt;
  final CheckinResult result;
  final int day;
  final String? reason;
  final bool synced;

  /// Came from another gate through sync.
  final bool remote;

  /// The server says another gate admitted this pass first.
  final bool conflict;

  Map<String, Object?> toJson() => {
        'id': id,
        'pass_id': passId,
        'scanned_at': scannedAt.toUtc().toIso8601String(),
        'result': result.name,
        'reason': reason,
        'day': day,
      };
}

/// Why a scan is green or red. Only [valid] lets the volunteer admit.
enum ScanStatus {
  valid,
  notAPass,
  invalidSignature,
  wrongEvent,
  wrongDay,
  notFound,
  revoked,
  alreadyUsed,
}

class ScanOutcome {
  const ScanOutcome(this.status, {this.token, this.pass, this.firstEntry});

  final ScanStatus status;
  final PassToken? token;
  final PassRecord? pass;

  /// For [ScanStatus.alreadyUsed]: where and when the pass was first used.
  final Checkin? firstEntry;

  bool get canAdmit => status == ScanStatus.valid;

  String get title => switch (status) {
        ScanStatus.valid => 'VALID PASS',
        ScanStatus.notAPass => 'NOT A PASS',
        ScanStatus.invalidSignature => 'INVALID PASS',
        ScanStatus.wrongEvent => 'WRONG EVENT',
        ScanStatus.wrongDay => 'NOT FOR TODAY',
        ScanStatus.notFound => 'PASS NOT FOUND',
        ScanStatus.revoked => 'PASS CANCELLED',
        ScanStatus.alreadyUsed => 'ALREADY USED',
      };

  /// Short code saved with the check-in, for the help desk and reports.
  String get reasonCode => switch (status) {
        ScanStatus.valid => 'ok',
        ScanStatus.notAPass => 'not_a_pass',
        ScanStatus.invalidSignature => 'bad_signature',
        ScanStatus.wrongEvent => 'wrong_event',
        ScanStatus.wrongDay => 'wrong_day',
        ScanStatus.notFound => 'not_in_list',
        ScanStatus.revoked => 'revoked',
        ScanStatus.alreadyUsed => 'already_used',
      };
}
