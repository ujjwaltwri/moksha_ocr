import 'dart:async';

import 'package:flutter/foundation.dart';

import '../config.dart';
import 'api.dart';
import 'db.dart';
import 'settings.dart';

/// Keeps this phone in step with the server: downloads the pass list,
/// uploads this phone's check-ins and pulls other gates' check-ins.
/// Scanning never waits on any of this, so the gate keeps working offline.
class SyncService extends ChangeNotifier {
  SyncService(this._db, this._settings);

  final GateDb _db;
  final Settings _settings;

  Timer? _timer;
  bool _busy = false;
  bool _manifestBusy = false;
  DateTime _lastManifestRefresh = DateTime.fromMillisecondsSinceEpoch(0);

  // Status shown on the home and scan screens.
  bool online = false;
  bool tokenRejected = false;
  DateTime? lastSyncAt;
  String? lastError;
  int pending = 0;
  int conflicts = 0;
  int passCount = 0;
  int admittedHere = 0;
  DateTime? passListUpdatedAt;

  // Pass list download progress.
  bool downloading = false;
  int downloaded = 0;
  int? downloadTotal;

  static const _manifestCursorKey = 'manifest_cursor';
  static const _manifestAtKey = 'manifest_updated_at';
  static const _checkinCursorKey = 'checkin_cursor';

  GateApi get _api => GateApi(
      baseUrl: _settings.serverUrl, deviceToken: _settings.deviceToken);

  void start() {
    _timer?.cancel();
    _timer = Timer.periodic(AppConfig.syncInterval, (_) => _tick());
    refreshCounts();
    _tick();
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  @override
  void dispose() {
    stop();
    super.dispose();
  }

  Future<void> refreshCounts() async {
    final day = _settings.day;
    passCount = await _db.passCount();
    pending = await _db.pendingCount();
    conflicts = await _db.conflictCount(day);
    admittedHere = await _db.admittedHere(_settings.deviceId, day);
    final at = await _db.getMeta(_manifestAtKey);
    passListUpdatedAt = at == null ? null : DateTime.parse(at).toLocal();
    notifyListeners();
  }

  /// Runs one sync round now, e.g. after a check-in.
  Future<void> syncNow() => _tick();

  Future<void> _tick() async {
    if (_busy || !_settings.isConfigured) return;
    _busy = true;
    try {
      await _syncCheckins();
      final due = DateTime.now().difference(_lastManifestRefresh) >
          AppConfig.manifestRefreshInterval;
      if (due && passCount > 0 && !_manifestBusy) {
        _lastManifestRefresh = DateTime.now();
        await _pullManifest(full: false);
      }
      _ok();
    } on ApiException catch (e) {
      _fail(e);
    } finally {
      _busy = false;
      await refreshCounts();
    }
  }

  Future<void> _syncCheckins() async {
    // Upload in batches until nothing is left, so a backlog from an
    // offline stretch clears quickly once the network is back.
    var since = await _db.getMeta(_checkinCursorKey);
    for (var round = 0; round < 10; round++) {
      final batch = await _db.unsynced(limit: 200);
      final result = await _api.syncCheckins(
        deviceId: _settings.deviceId,
        gate: _settings.gate,
        checkins: batch,
        since: since,
      );
      await _db.markSynced(result.accepted);
      await _db.markConflicts(result.conflictIds);
      await _db.insertCheckins(result.remote);
      if (result.nextSince != null) {
        since = result.nextSince;
        await _db.setMeta(_checkinCursorKey, since);
      }
      // Stop when everything is uploaded and nothing more is coming.
      if (batch.length < 200 && result.remote.length < 500) break;
    }
  }

  /// Downloads the pass list. [full] starts again from the beginning;
  /// otherwise only passes changed since the last download are fetched.
  Future<void> downloadPassList({bool full = true}) async {
    if (_manifestBusy) return;
    try {
      await _pullManifest(full: full);
      _ok();
    } on ApiException catch (e) {
      _fail(e);
      rethrow;
    } finally {
      await refreshCounts();
    }
  }

  Future<void> _pullManifest({required bool full}) async {
    if (_manifestBusy) return;
    _manifestBusy = true;
    downloading = full;
    downloaded = 0;
    downloadTotal = null;
    notifyListeners();
    try {
      var cursor = full ? null : await _db.getMeta(_manifestCursorKey);
      while (true) {
        final page = await _api.fetchManifest(
            since: cursor, limit: AppConfig.manifestPageSize);
        await _db.upsertPasses(page.passes);
        downloaded += page.passes.length;
        downloadTotal ??= page.total;
        if (page.nextCursor != null) {
          cursor = page.nextCursor;
          await _db.setMeta(_manifestCursorKey, cursor);
        }
        if (full) notifyListeners();
        if (!page.hasMore || page.passes.isEmpty) break;
      }
      await _db.setMeta(
          _manifestAtKey, DateTime.now().toUtc().toIso8601String());
    } finally {
      _manifestBusy = false;
      downloading = false;
      notifyListeners();
    }
  }

  void _ok() {
    online = true;
    tokenRejected = false;
    lastError = null;
    lastSyncAt = DateTime.now();
  }

  void _fail(ApiException e) {
    online = false;
    tokenRejected = e.unauthorized;
    lastError = e.unauthorized
        ? 'This phone\'s device token was rejected. Ask an admin for a new one.'
        : e.message;
    debugPrint('Sync failed: $e');
  }
}
