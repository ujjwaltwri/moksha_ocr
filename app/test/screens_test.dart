import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:moksha_gate/models.dart';
import 'package:moksha_gate/screens/home_screen.dart';
import 'package:moksha_gate/screens/result_screen.dart';
import 'package:moksha_gate/screens/setup_screen.dart';
import 'package:moksha_gate/services/app_services.dart';
import 'package:moksha_gate/theme.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const _pass = PassRecord(
    id: 'p1', name: 'Aarav Sharma', college: 'Test College', rollNo: 'R100');
const _token = PassToken(
    version: 1, passId: 'p1', eventId: 'moksha26', days: [1], issuedAt: 0);

/// A configured phone with a fresh database on disk.
Future<AppServices> _app(WidgetTester t, {bool withPasses = true}) async {
  SharedPreferences.setMockInitialValues({
    'server_url': 'https://gate.test',
    'gate': 'Gate 2',
    'day': 1,
    'device_id': 'dev-1',
    'debug_public_key': 'A' * 43, // 32 zero bytes; only the length matters here
  });
  FlutterSecureStorage.setMockInitialValues({'device_token': 'tok'});
  return (await t.runAsync(() async {
    final dir = Directory.systemTemp.createTempSync('gate_test');
    final app = await AppServices.init(dbPath: '${dir.path}/gate.db');
    if (withPasses) await app.db.upsertPasses([_pass]);
    await app.sync.refreshCounts();
    return app;
  }))!;
}

Future<void> _show(WidgetTester t, AppServices app, Widget screen) async {
  t.view.physicalSize = const Size(1179, 2556);
  t.view.devicePixelRatio = 3;
  addTearDown(t.view.reset);
  await t.pumpWidget(Services(
    services: app,
    child: MaterialApp(theme: buildTheme(), home: screen),
  ));
  await t.pumpAndSettle();
}

FilledButton _button(WidgetTester t, String label) => t.widget<FilledButton>(
    find.ancestor(of: find.text(label), matching: find.byType(FilledButton)));

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  testWidgets('home allows scanning once the pass list is on the phone',
      (t) async {
    await _show(t, await _app(t), const HomeScreen());
    expect(find.text('Gate 2'), findsOneWidget);
    expect(_button(t, 'Scan passes').onPressed, isNotNull);
  });

  testWidgets('home blocks scanning without a pass list', (t) async {
    await _show(t, await _app(t, withPasses: false), const HomeScreen());
    expect(_button(t, 'Not ready to scan').onPressed, isNull);
    expect(find.text('Download'), findsOneWidget);
  });

  testWidgets('setup screen renders', (t) async {
    await _show(t, await _app(t), const SetupScreen(firstRun: true));
    expect(find.text('Scan setup code'), findsOneWidget);
    // Camera only: there is nothing to type.
    expect(find.byType(TextField), findsNothing);
  });

  test('setup code checks', () {
    String code(Map<String, Object?> m) =>
        jsonEncode({'t': 'moksha-gate-setup', ...m});
    const ok = {'url': 'https://gate.test', 'token': 'tok', 'gate': 'Gate 2'};

    final c = parseSetupCode(code({...ok, 'day': 2}), allowHttp: false)!;
    expect((c.url, c.token, c.gate, c.day),
        ('https://gate.test', 'tok', 'Gate 2', 2));
    expect(
        parseSetupCode(code({...ok, 'day': 9}), allowHttp: false)!.day, isNull);
    expect(parseSetupCode('hello', allowHttp: false), isNull);
    expect(parseSetupCode(jsonEncode({...ok, 't': 'other'}), allowHttp: false),
        isNull);
    expect(
        parseSetupCode(code({...ok, 'token': ''}), allowHttp: false), isNull);
    expect(
        parseSetupCode(code({...ok, 'gate': null}), allowHttp: false), isNull);
    final http = code({...ok, 'url': 'http://10.0.0.5:8787'});
    expect(parseSetupCode(http, allowHttp: false), isNull);
    expect(parseSetupCode(http, allowHttp: true), isNotNull);
  });

  testWidgets('a valid pass shows the student and ADMIT', (t) async {
    await _show(
        t,
        await _app(t),
        const ResultScreen(
            outcome:
                ScanOutcome(ScanStatus.valid, token: _token, pass: _pass)));
    expect(find.text('Aarav Sharma'), findsOneWidget);
    expect(find.text('ADMIT'), findsOneWidget);
  });

  testWidgets('a red screen has no ADMIT button', (t) async {
    await _show(
        t,
        await _app(t),
        const ResultScreen(
            outcome:
                ScanOutcome(ScanStatus.revoked, token: _token, pass: _pass)));
    expect(find.text('PASS CANCELLED'), findsOneWidget);
    expect(find.text('ADMIT'), findsNothing);
  });
}
