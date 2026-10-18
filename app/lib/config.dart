/// Build-time settings. Pass them with --dart-define, for example:
///
///   flutter build apk --release \
///     --dart-define=PASS_PUBLIC_KEY=<base64url Ed25519 public key> \
///     --dart-define=EVENT_ID=moksha26 \
///     --dart-define=ADMIN_PIN=4826
class AppConfig {
  /// Ed25519 public key that verifies passes (32 bytes, base64url).
  /// Comes from scripts/gen_keys.py on the server side. Without it the app
  /// refuses to scan.
  static const passPublicKey = String.fromEnvironment('PASS_PUBLIC_KEY');

  /// Must match the "e" field inside every pass.
  static const eventId =
      String.fromEnvironment('EVENT_ID', defaultValue: 'moksha26');

  /// PIN that guards settings on the gate phones. Change it for the fest build.
  static const adminPin =
      String.fromEnvironment('ADMIN_PIN', defaultValue: '2026');

  /// Push and pull check-ins this often while the app is open.
  static const syncInterval = Duration(seconds: 5);

  /// Pick up late passes and revocations this often.
  static const manifestRefreshInterval = Duration(seconds: 60);

  static const manifestPageSize = 1000;

  /// The same QR scanned again within this window is ignored, so a student
  /// still holding up their phone after "Admit" doesn't show "already used".
  static const rescanCooldown = Duration(seconds: 4);

  /// Fest days. Each pass lists the days it is valid for, and the gate
  /// checks today against it. Edit to match the plan.
  static const festDays = <FestDay>[FestDay(1), FestDay(2), FestDay(3)];

  static FestDay dayInfo(int day) =>
      festDays.firstWhere((d) => d.number == day, orElse: () => FestDay(day));
}

class FestDay {
  const FestDay(this.number);
  final int number;

  String get label => 'Day $number';
}
