import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../config.dart';

/// Per-phone settings. The device token lives in the Keychain / Keystore.
class Settings extends ChangeNotifier {
  Settings._(this._prefs, this._secure);

  final SharedPreferences _prefs;
  final FlutterSecureStorage _secure;

  String _token = '';

  static Future<Settings> load() async {
    final s = Settings._(
      await SharedPreferences.getInstance(),
      const FlutterSecureStorage(
        aOptions: AndroidOptions(encryptedSharedPreferences: true),
      ),
    );
    try {
      s._token = await s._secure.read(key: 'device_token') ?? '';
    } catch (_) {
      // The Keystore key behind the encrypted store can be lost (backup
      // restore, some OEM phones). Start clean; the phone just needs the
      // setup code scanned again.
      await s._secure.deleteAll().catchError((_) {});
    }
    if (s._prefs.getString('device_id') == null) {
      await s._prefs.setString('device_id', const Uuid().v4());
    }
    return s;
  }

  String get serverUrl => _prefs.getString('server_url') ?? '';
  String get deviceToken => _token;
  String get gate => _prefs.getString('gate') ?? '';
  String get deviceId => _prefs.getString('device_id')!;

  int get day =>
      _prefs.getInt('day') ?? AppConfig.festDays.first.number;

  /// Public key override from a setup code. Debug builds only, for testing
  /// against the mock server; release builds always use the built-in key.
  String? get debugPublicKey =>
      kDebugMode ? _prefs.getString('debug_public_key') : null;

  bool get isConfigured =>
      serverUrl.isNotEmpty && _token.isNotEmpty && gate.isNotEmpty;

  Future<void> save({
    required String serverUrl,
    required String deviceToken,
    required String gate,
    required int day,
    String? debugPublicKey,
  }) async {
    await _prefs.setString('server_url', serverUrl.trim());
    await _prefs.setString('gate', gate.trim());
    await _prefs.setInt('day', day);
    if (kDebugMode && debugPublicKey != null && debugPublicKey.isNotEmpty) {
      await _prefs.setString('debug_public_key', debugPublicKey.trim());
    }
    _token = deviceToken.trim();
    await _secure.write(key: 'device_token', value: _token);
    notifyListeners();
  }

  Future<void> setDay(int day) async {
    await _prefs.setInt('day', day);
    notifyListeners();
  }
}
