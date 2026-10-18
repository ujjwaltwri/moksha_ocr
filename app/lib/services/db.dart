import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import '../models.dart';

/// On-device store: the pass list and every check-in this phone knows about.
class GateDb {
  late final Database _db;

  Future<void> open() async {
    final dir = await getDatabasesPath();
    _db = await openDatabase(
      p.join(dir, 'gate.db'),
      version: 1,
      onCreate: (db, _) async {
        await db.execute('''
          CREATE TABLE passes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            college TEXT NOT NULL,
            roll_no TEXT,
            thumb BLOB,
            revoked INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
          )''');
        await db.execute('''
          CREATE TABLE checkins (
            id TEXT PRIMARY KEY,
            pass_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            gate TEXT NOT NULL,
            scanned_at TEXT NOT NULL,
            result TEXT NOT NULL,
            reason TEXT,
            day INTEGER NOT NULL,
            synced INTEGER NOT NULL DEFAULT 0,
            remote INTEGER NOT NULL DEFAULT 0,
            conflict INTEGER NOT NULL DEFAULT 0
          )''');
        await db.execute(
            'CREATE INDEX checkins_pass_day ON checkins (pass_id, day, result)');
        await db.execute('CREATE INDEX checkins_unsynced ON checkins (synced)');
        await db.execute(
            'CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
      },
    );
  }

  // ---- Pass list ----

  Future<PassRecord?> getPass(String id) async {
    final rows = await _db.query('passes', where: 'id = ?', whereArgs: [id]);
    return rows.isEmpty ? null : _passFromRow(rows.first);
  }

  Future<void> upsertPasses(List<PassRecord> passes) async {
    final batch = _db.batch();
    for (final pass in passes) {
      batch.insert(
        'passes',
        {
          'id': pass.id,
          'name': pass.name,
          'college': pass.college,
          'roll_no': pass.rollNo,
          'thumb': pass.thumb,
          'revoked': pass.revoked ? 1 : 0,
          'updated_at': pass.updatedAt,
        },
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }
    await batch.commit(noResult: true);
  }

  Future<int> passCount() async =>
      Sqflite.firstIntValue(await _db.rawQuery('SELECT COUNT(*) FROM passes')) ??
      0;

  // ---- Check-ins ----

  /// The first admission of this pass on [day], from any gate.
  Future<Checkin?> firstAdmission(String passId, int day) async {
    final rows = await _db.query(
      'checkins',
      where: 'pass_id = ? AND day = ? AND result = ?',
      whereArgs: [passId, day, CheckinResult.admitted.name],
      orderBy: 'scanned_at ASC',
      limit: 1,
    );
    return rows.isEmpty ? null : _checkinFromRow(rows.first);
  }

  Future<void> insertCheckin(Checkin c) => _db.insert(
        'checkins',
        _checkinToRow(c),
        // A synced row from another gate may arrive more than once.
        conflictAlgorithm: ConflictAlgorithm.ignore,
      );

  Future<void> insertCheckins(List<Checkin> list) async {
    if (list.isEmpty) return;
    final batch = _db.batch();
    for (final c in list) {
      batch.insert('checkins', _checkinToRow(c),
          conflictAlgorithm: ConflictAlgorithm.ignore);
    }
    await batch.commit(noResult: true);
  }

  Future<List<Checkin>> unsynced({int limit = 200}) async {
    final rows = await _db.query('checkins',
        where: 'synced = 0 AND remote = 0',
        orderBy: 'scanned_at ASC',
        limit: limit);
    return rows.map(_checkinFromRow).toList();
  }

  Future<void> markSynced(Iterable<String> ids) async {
    if (ids.isEmpty) return;
    final batch = _db.batch();
    for (final id in ids) {
      batch.update('checkins', {'synced': 1},
          where: 'id = ?', whereArgs: [id]);
    }
    await batch.commit(noResult: true);
  }

  Future<void> markConflicts(Iterable<String> checkinIds) async {
    if (checkinIds.isEmpty) return;
    final batch = _db.batch();
    for (final id in checkinIds) {
      batch.update('checkins', {'conflict': 1},
          where: 'id = ?', whereArgs: [id]);
    }
    await batch.commit(noResult: true);
  }

  Future<int> pendingCount() async =>
      Sqflite.firstIntValue(await _db.rawQuery(
          'SELECT COUNT(*) FROM checkins WHERE synced = 0 AND remote = 0')) ??
      0;

  Future<int> conflictCount(int day) async =>
      Sqflite.firstIntValue(await _db.rawQuery(
          'SELECT COUNT(*) FROM checkins WHERE conflict = 1 AND day = ?',
          [day])) ??
      0;

  /// Students this phone admitted on [day].
  Future<int> admittedHere(String deviceId, int day) async =>
      Sqflite.firstIntValue(await _db.rawQuery(
          'SELECT COUNT(*) FROM checkins '
          'WHERE device_id = ? AND day = ? AND result = ? AND remote = 0',
          [deviceId, day, CheckinResult.admitted.name])) ??
      0;

  /// This phone's recent decisions, newest first, with the pass details.
  Future<List<(Checkin, PassRecord?)>> recentLocal({int limit = 200}) async {
    final rows = await _db.rawQuery('''
      SELECT c.*, p.name AS p_name, p.college AS p_college,
             p.roll_no AS p_roll, p.thumb AS p_thumb
      FROM checkins c LEFT JOIN passes p ON p.id = c.pass_id
      WHERE c.remote = 0
      ORDER BY c.scanned_at DESC
      LIMIT ?''', [limit]);
    return rows.map((r) {
      final pass = r['p_name'] == null
          ? null
          : PassRecord(
              id: r['pass_id'] as String,
              name: r['p_name'] as String,
              college: r['p_college'] as String,
              rollNo: r['p_roll'] as String?,
              thumb: r['p_thumb'] as dynamic,
            );
      return (_checkinFromRow(r), pass);
    }).toList();
  }

  // ---- Settings that sync needs ----

  Future<String?> getMeta(String key) async {
    final rows =
        await _db.query('meta', where: 'key = ?', whereArgs: [key], limit: 1);
    return rows.isEmpty ? null : rows.first['value'] as String;
  }

  Future<void> setMeta(String key, String? value) async {
    if (value == null) {
      await _db.delete('meta', where: 'key = ?', whereArgs: [key]);
    } else {
      await _db.insert('meta', {'key': key, 'value': value},
          conflictAlgorithm: ConflictAlgorithm.replace);
    }
  }

  /// End of the fest day: remove the pass list and synced check-ins.
  /// Unsynced check-ins are kept so nothing is lost.
  Future<void> wipeForNewDay() async {
    await _db.transaction((txn) async {
      await txn.delete('passes');
      await txn.delete('checkins', where: 'synced = 1 OR remote = 1');
      await txn.delete('meta');
    });
  }

  // ---- Row mapping ----

  PassRecord _passFromRow(Map<String, Object?> r) => PassRecord(
        id: r['id'] as String,
        name: r['name'] as String,
        college: r['college'] as String,
        rollNo: r['roll_no'] as String?,
        thumb: r['thumb'] as dynamic,
        revoked: (r['revoked'] as int) == 1,
        updatedAt: r['updated_at'] as String?,
      );

  Map<String, Object?> _checkinToRow(Checkin c) => {
        'id': c.id,
        'pass_id': c.passId,
        'device_id': c.deviceId,
        'gate': c.gate,
        'scanned_at': c.scannedAt.toUtc().toIso8601String(),
        'result': c.result.name,
        'reason': c.reason,
        'day': c.day,
        'synced': c.synced ? 1 : 0,
        'remote': c.remote ? 1 : 0,
        'conflict': c.conflict ? 1 : 0,
      };

  Checkin _checkinFromRow(Map<String, Object?> r) => Checkin(
        id: r['id'] as String,
        passId: r['pass_id'] as String,
        deviceId: r['device_id'] as String,
        gate: r['gate'] as String,
        scannedAt: DateTime.parse(r['scanned_at'] as String).toLocal(),
        result: CheckinResult.values.byName(r['result'] as String),
        reason: r['reason'] as String?,
        day: r['day'] as int,
        synced: (r['synced'] as int) == 1,
        remote: (r['remote'] as int) == 1,
        conflict: (r['conflict'] as int) == 1,
      );
}
