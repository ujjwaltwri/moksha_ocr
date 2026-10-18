// Patches the android/ and ios/ folders that `flutter create` generates, so
// the app has camera and network access and builds for the store.
//
// Run from the project root, after `flutter create`:
//   dart run tool/patch_platforms.dart
//
// Safe to run more than once. On the Mac, run it again after
// `flutter build ios --config-only` so the Podfile gets patched too.

import 'dart:io';

int changes = 0;

void main() {
  _removeTemplateTest();
  _androidManifest();
  _androidDebugManifest();
  _androidGradle();
  _iosInfoPlist();
  _iosPodfile();
  stdout.writeln(changes == 0
      ? 'Nothing to change; platform files are already patched.'
      : 'Done: $changes change(s).');
}

// `flutter create` adds a counter-app test that doesn't compile against
// this app. Remove it.
void _removeTemplateTest() {
  final f = File('test/widget_test.dart');
  if (f.existsSync() && f.readAsStringSync().contains('MyApp')) {
    f.deleteSync();
    _did('Removed the template test/widget_test.dart');
  }
}

void _androidManifest() {
  final f = File('android/app/src/main/AndroidManifest.xml');
  if (!f.existsSync()) return _missing(f.path);
  var s = f.readAsStringSync();
  for (final perm in [
    'android.permission.INTERNET',
    'android.permission.CAMERA',
  ]) {
    if (!s.contains(perm)) {
      s = s.replaceFirstMapped(RegExp(r'<manifest[^>]*>'),
          (m) => '${m[0]}\n    <uses-permission android:name="$perm"/>');
      _did('AndroidManifest: added $perm');
    }
  }
  if (s.contains('android:label="moksha_gate"')) {
    s = s.replaceFirst(
        'android:label="moksha_gate"', 'android:label="Moksha Gate"');
    _did('AndroidManifest: app name "Moksha Gate"');
  }
  // Lock the scanner to portrait.
  if (!s.contains('android:screenOrientation')) {
    s = s.replaceFirst(
        'android:name=".MainActivity"',
        'android:name=".MainActivity"\n            android:screenOrientation="portrait"');
    _did('AndroidManifest: portrait only');
  }
  f.writeAsStringSync(s);
}

// Debug builds may talk to the mock server over plain http on the LAN.
// Release builds stay HTTPS-only.
void _androidDebugManifest() {
  final f = File('android/app/src/debug/AndroidManifest.xml');
  if (!f.existsSync()) return _missing(f.path);
  var s = f.readAsStringSync();
  if (s.contains('usesCleartextTraffic')) return;
  if (s.contains('<application')) {
    s = s.replaceFirst('<application', '<application android:usesCleartextTraffic="true"');
  } else {
    s = s.replaceFirst('</manifest>',
        '    <application android:usesCleartextTraffic="true"/>\n</manifest>');
  }
  f.writeAsStringSync(s);
  _did('Debug manifest: allow http for the mock server');
}

void _androidGradle() {
  for (final path in ['android/app/build.gradle.kts', 'android/app/build.gradle']) {
    final f = File(path);
    if (!f.existsSync()) continue;
    var s = f.readAsStringSync();
    final kts = path.endsWith('.kts');
    final re = RegExp(r'minSdk(Version)?\s*=?\s*flutter\.minSdkVersion');
    if (re.hasMatch(s)) {
      s = s.replaceFirst(re, kts ? 'minSdk = 23' : 'minSdkVersion 23');
      _did('$path: minSdk 23');
    }
    if (kts) {
      s = _releaseSigning(s);
    } else if (!s.contains('key.properties')) {
      stdout.writeln('  ! $path is Groovy: add release signing by hand '
          '(see README, "Android release key").');
    }
    f.writeAsStringSync(s);
    return;
  }
  _missing('android/app/build.gradle(.kts)');
}

/// Signs release builds with the upload key from android/key.properties
/// when that file exists; otherwise falls back to the debug key.
String _releaseSigning(String s) {
  if (s.contains('key.properties')) return s;
  // Imports go at the very top; Gradle needs plugins {} before other code.
  const imports = '''
import java.io.FileInputStream
import java.util.Properties

''';
  const props = '''
val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

''';
  const signing = '''
    signingConfigs {
        create("release") {
            if (keystorePropertiesFile.exists()) {
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
                storeFile = file(keystoreProperties["storeFile"] as String)
                storePassword = keystoreProperties["storePassword"] as String
            }
        }
    }

    buildTypes {''';
  final androidBlock = RegExp(r'^android \{', multiLine: true);
  if (!s.contains('    buildTypes {') || !androidBlock.hasMatch(s)) {
    stdout.writeln('  ! build.gradle.kts layout not recognised; add signing by hand.');
    return s;
  }
  s = imports +
      s
          .replaceFirst(androidBlock, '${props}android {')
          .replaceFirst('    buildTypes {', signing);
  s = s.replaceFirst(
      'signingConfig = signingConfigs.getByName("debug")',
      'signingConfig = if (keystorePropertiesFile.exists()) '
          'signingConfigs.getByName("release") else signingConfigs.getByName("debug")');
  _did('build.gradle.kts: release signing from android/key.properties');
  return s;
}

void _iosInfoPlist() {
  final f = File('ios/Runner/Info.plist');
  if (!f.existsSync()) return _missing(f.path);
  var s = f.readAsStringSync();
  final entries = <String, String>{
    'NSCameraUsageDescription':
        '<string>The camera scans entry passes at the gate.</string>',
    'NSLocalNetworkUsageDescription':
        '<string>Syncs entries with other gates on the venue network.</string>',
    // Only standard HTTPS and signature checks: no export paperwork per upload.
    'ITSAppUsesNonExemptEncryption': '<false/>',
    'NSAppTransportSecurity':
        '<dict>\n\t\t<key>NSAllowsLocalNetworking</key>\n\t\t<true/>\n\t</dict>',
  };
  entries.forEach((key, value) {
    if (s.contains('<key>$key</key>')) return;
    final i = s.lastIndexOf('</dict>');
    s = '${s.substring(0, i)}\t<key>$key</key>\n\t$value\n${s.substring(i)}';
    _did('Info.plist: added $key');
  });
  // Portrait only on iPhone.
  final orient = RegExp(
      r'<key>UISupportedInterfaceOrientations</key>\s*<array>[\s\S]*?</array>');
  const portrait =
      '<key>UISupportedInterfaceOrientations</key>\n\t<array>\n\t\t<string>UIInterfaceOrientationPortrait</string>\n\t</array>';
  final m = orient.firstMatch(s);
  if (m != null && m.group(0)!.contains('Landscape')) {
    s = s.replaceRange(m.start, m.end, portrait);
    _did('Info.plist: portrait only');
  }
  f.writeAsStringSync(s);
}

void _iosPodfile() {
  final f = File('ios/Podfile');
  if (!f.existsSync()) {
    stdout.writeln('ios/Podfile not generated yet. On the Mac, run '
        '`flutter build ios --config-only`, then run this script again.');
    return;
  }
  var s = f.readAsStringSync();
  final re = RegExp(r"^#?\s*platform :ios, '[\d.]+'", multiLine: true);
  const want = "platform :ios, '15.5'";
  if (s.contains(want)) return;
  s = re.hasMatch(s) ? s.replaceFirst(re, want) : '$want\n$s';
  f.writeAsStringSync(s);
  _did('Podfile: iOS 15.5 minimum');
}

void _did(String what) {
  changes++;
  stdout.writeln('  ✓ $what');
}

void _missing(String path) => stdout.writeln('  ! $path not found (skipped)');
