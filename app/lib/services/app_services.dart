import 'package:flutter/widgets.dart';

import '../config.dart';
import 'db.dart';
import 'gate_service.dart';
import 'pass_verifier.dart';
import 'settings.dart';
import 'sync.dart';

/// Everything the screens need, created once at startup.
class AppServices {
  AppServices._(this.settings, this.db, this.sync, this.gate);

  final Settings settings;
  final GateDb db;
  final SyncService sync;
  final GateService gate;

  /// Why scanning is unavailable, or null when the key is fine.
  String? keyError;

  /// [dbPath] is for tests.
  static Future<AppServices> init({String? dbPath}) async {
    final settings = await Settings.load();
    final db = GateDb();
    await db.open(path: dbPath);
    final sync = SyncService(db, settings);
    final app =
        AppServices._(settings, db, sync, GateService(db, settings, sync));
    app.loadKey();
    return app;
  }

  /// (Re)loads the pass public key: the built-in one, or in debug builds a
  /// key from a mock-server setup code.
  void loadKey() {
    final key = settings.debugPublicKey ?? AppConfig.passPublicKey;
    gate.verifier = null;
    if (key.isEmpty) {
      keyError = 'This build has no pass public key. Rebuild it with '
          '--dart-define=PASS_PUBLIC_KEY=<key>.';
      return;
    }
    try {
      gate.verifier = PassVerifier.fromBase64Url(key);
      keyError = null;
    } on FormatException catch (e) {
      keyError = 'The pass public key in this build is invalid: ${e.message}';
    }
  }
}

class Services extends InheritedWidget {
  const Services({super.key, required this.services, required super.child});

  final AppServices services;

  static AppServices of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<Services>()!.services;

  @override
  bool updateShouldNotify(Services oldWidget) => services != oldWidget.services;
}
