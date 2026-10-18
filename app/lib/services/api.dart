import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../models.dart';

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);
  final int? statusCode;
  final String message;

  /// The device token was revoked or is wrong.
  bool get unauthorized => statusCode == 401 || statusCode == 403;

  @override
  String toString() =>
      statusCode == null ? message : 'HTTP $statusCode: $message';
}

class ManifestPage {
  const ManifestPage(this.passes, this.nextCursor, this.hasMore, this.total);
  final List<PassRecord> passes;
  final String? nextCursor;
  final bool hasMore;
  final int? total;
}

class CheckinSyncResult {
  const CheckinSyncResult({
    required this.accepted,
    required this.conflictIds,
    required this.remote,
    required this.nextSince,
  });

  /// Our check-in IDs the server stored.
  final List<String> accepted;

  /// Our admitted check-ins for passes another gate had already admitted.
  final List<String> conflictIds;

  /// Check-ins from other gates since our last pull.
  final List<Checkin> remote;
  final String? nextSince;
}

/// Client for the two gate endpoints in the build spec. Every call carries
/// the per-device token as a Bearer token.
///
/// GET  /gate/manifest?since=<cursor>&limit=<n>
///   -> { "passes": [ { "id", "name", "college", "roll_no",
///                      "thumb_b64", "revoked", "updated_at" } ],
///        "next_cursor": "...", "has_more": true, "total": 24812 }
///
/// POST /gate/checkins
///   <- { "device_id", "gate", "since": "<cursor>",
///        "checkins": [ { "id", "pass_id", "scanned_at", "result",
///                        "reason", "day" } ] }
///   -> { "accepted": ["<id>"], "conflicts": ["<id>"],
///        "remote": [ { "id", "pass_id", "device_id", "gate",
///                      "scanned_at", "result", "reason", "day" } ],
///        "next_since": "<cursor>" }
class GateApi {
  GateApi({required String baseUrl, required this.deviceToken, http.Client? client})
      : baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), ''),
        _client = client ?? http.Client();

  final String baseUrl;
  final String deviceToken;
  final http.Client _client;

  Map<String, String> get _headers => {
        'Authorization': 'Bearer $deviceToken',
        'Accept': 'application/json',
      };

  Future<ManifestPage> fetchManifest({String? since, int limit = 1000}) async {
    final uri = Uri.parse('$baseUrl/gate/manifest').replace(queryParameters: {
      if (since != null) 'since': since,
      'limit': '$limit',
    });
    final res = await _send(() => _client
        .get(uri, headers: _headers)
        .timeout(const Duration(seconds: 45)));
    final body = res as Map<String, dynamic>;
    final passes = (body['passes'] as List? ?? const [])
        .cast<Map<String, dynamic>>()
        .map(_passFromJson)
        .toList();
    return ManifestPage(
      passes,
      body['next_cursor'] as String?,
      body['has_more'] == true,
      (body['total'] as num?)?.toInt(),
    );
  }

  Future<CheckinSyncResult> syncCheckins({
    required String deviceId,
    required String gate,
    required List<Checkin> checkins,
    String? since,
  }) async {
    final res = await _send(() => _client
        .post(
          Uri.parse('$baseUrl/gate/checkins'),
          headers: {..._headers, 'Content-Type': 'application/json'},
          body: jsonEncode({
            'device_id': deviceId,
            'gate': gate,
            'since': since,
            'checkins': checkins.map((c) => c.toJson()).toList(),
          }),
        )
        .timeout(const Duration(seconds: 10)));
    final body = res as Map<String, dynamic>;
    return CheckinSyncResult(
      accepted: (body['accepted'] as List? ?? const []).cast<String>(),
      conflictIds: (body['conflicts'] as List? ?? const []).cast<String>(),
      remote: (body['remote'] as List? ?? const [])
          .cast<Map<String, dynamic>>()
          .map(_remoteCheckinFromJson)
          .whereType<Checkin>()
          .toList(),
      nextSince: body['next_since'] as String?,
    );
  }

  Future<Object?> _send(Future<http.Response> Function() call) async {
    final http.Response res;
    try {
      res = await call();
    } catch (e) {
      throw ApiException(null, 'Network error: $e');
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw ApiException(res.statusCode, _shorten(res.body));
    }
    try {
      return jsonDecode(utf8.decode(res.bodyBytes));
    } on FormatException {
      throw ApiException(res.statusCode, 'Server sent something that is not JSON');
    }
  }

  static PassRecord _passFromJson(Map<String, dynamic> j) {
    Uint8List? thumb;
    final b64 = j['thumb_b64'];
    if (b64 is String && b64.isNotEmpty) {
      try {
        thumb = base64.decode(base64.normalize(b64));
      } on FormatException {
        thumb = null;
      }
    }
    return PassRecord(
      id: j['id'] as String,
      name: (j['name'] as String?) ?? '',
      college: (j['college'] as String?) ?? '',
      rollNo: j['roll_no'] as String?,
      thumb: thumb,
      revoked: j['revoked'] == true,
      updatedAt: j['updated_at'] as String?,
    );
  }

  static Checkin? _remoteCheckinFromJson(Map<String, dynamic> j) {
    try {
      return Checkin(
        id: j['id'] as String,
        passId: j['pass_id'] as String,
        deviceId: (j['device_id'] as String?) ?? '?',
        gate: (j['gate'] as String?) ?? '?',
        scannedAt: DateTime.parse(j['scanned_at'] as String),
        result: CheckinResult.values.byName(j['result'] as String),
        reason: j['reason'] as String?,
        day: (j['day'] as num).toInt(),
        synced: true,
        remote: true,
      );
    } catch (_) {
      return null; // Skip a malformed row rather than failing the whole sync.
    }
  }

  static String _shorten(String s) =>
      s.length > 200 ? '${s.substring(0, 200)}…' : s;
}
