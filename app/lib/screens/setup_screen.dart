import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../config.dart';
import '../services/app_services.dart';
import '../theme.dart';
import '../widgets/brand.dart';
import '../widgets/qr_capture.dart';

/// Connects a phone to the server. An admin shows a setup QR from the admin
/// page; scanning it is the only way in, so nobody types a server or token.
///
/// Setup QR content (JSON):
///   {"t":"moksha-gate-setup","url":"https://…","token":"…","gate":"Gate 2","day":1}
class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key, this.firstRun = false});

  final bool firstRun;

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

/// A setup code that passed every check.
typedef SetupCode = ({
  String url,
  String token,
  String gate,
  int? day,
  String? key
});

/// Reads a scanned setup QR. Returns null when it is not a
/// usable gate setup code.
SetupCode? parseSetupCode(String raw, {required bool allowHttp}) {
  try {
    final j = jsonDecode(raw);
    if (j is! Map || j['t'] != 'moksha-gate-setup') return null;
    final url = (j['url'] as String?)?.trim() ?? '';
    final token = (j['token'] as String?)?.trim() ?? '';
    final gate = (j['gate'] as String?)?.trim() ?? '';
    final u = Uri.tryParse(url);
    if (u == null || u.host.isEmpty) return null;
    if (u.scheme != 'https' && !(allowHttp && u.scheme == 'http')) return null;
    if (token.isEmpty || gate.isEmpty) return null;
    final d = j['day'];
    final day =
        d is int && AppConfig.festDays.any((f) => f.number == d) ? d : null;
    return (
      url: url,
      token: token,
      gate: gate,
      day: day,
      key: j['key'] as String?
    );
  } catch (_) {
    return null;
  }
}

class _SetupScreenState extends State<SetupScreen> {
  bool _saving = false;

  Future<void> _scanSetupCode() async {
    final raw = await Navigator.of(context).push<String>(MaterialPageRoute(
        builder: (_) => const QrCaptureScreen(title: 'Scan setup code')));
    if (raw == null || !mounted) return;
    final code = parseSetupCode(raw, allowHttp: kDebugMode);
    if (code == null) {
      _snack('That is not a gate setup code. Ask the gate lead for the one '
          'on the admin page.');
      return;
    }
    setState(() => _saving = true);
    final app = Services.of(context);
    await app.settings.save(
      serverUrl: code.url,
      deviceToken: code.token,
      gate: code.gate,
      day: code.day ?? app.settings.day,
      debugPublicKey: code.key,
    );
    app.loadKey();
    app.sync.start();
    if (!mounted) return;
    setState(() => _saving = false);
    if (!widget.firstRun) {
      _snack('Connected as ${code.gate}.');
      Navigator.of(context).pop();
    }
  }

  void _snack(String msg) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: widget.firstRun ? null : AppBar(title: const Text('Connection')),
      body: SafeArea(
        child: ListView(
          padding: EdgeInsets.fromLTRB(20, widget.firstRun ? 28 : 8, 20, 32),
          children: [
            if (widget.firstRun) ...[
              const Row(children: [
                NsutLogo(size: 64),
                SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      BrandEyebrow(),
                      SizedBox(height: 2),
                      Text('Gate scanner',
                          style:
                              TextStyle(fontSize: 15, color: GateColors.muted)),
                    ],
                  ),
                ),
              ]),
              const SizedBox(height: 28),
            ],
            Text(
                widget.firstRun ? 'Set up this phone' : 'Scan a new setup code',
                style: Theme.of(context).textTheme.headlineMedium),
            const SizedBox(height: 8),
            const Text(
              'Ask the gate lead to show the setup code from the admin page, then scan it.',
              style: TextStyle(fontSize: 16, color: GateColors.muted),
            ),
            const SizedBox(height: 24),
            const _Step(
                n: 1, text: 'Open the admin page on the gate lead\'s laptop.'),
            const _Step(n: 2, text: 'Tap Scan setup code below.'),
            const _Step(
                n: 3,
                text: 'Point the camera at the code. The phone connects by '
                    'itself.'),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: _saving ? null : _scanSetupCode,
              style: FilledButton.styleFrom(
                  backgroundColor: GateColors.accent,
                  minimumSize: const Size.fromHeight(68),
                  textStyle: const TextStyle(
                      fontSize: 20, fontWeight: FontWeight.w800)),
              icon: const Icon(Icons.qr_code_scanner, size: 28),
              label: Text(_saving ? 'Connecting…' : 'Scan setup code'),
            ),
          ],
        ),
      ),
    );
  }
}

class _Step extends StatelessWidget {
  const _Step({required this.n, required this.text});
  final int n;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(children: [
          CircleAvatar(
            radius: 14,
            backgroundColor: GateColors.accentSoft,
            child: Text('$n',
                style: const TextStyle(
                    color: GateColors.accent, fontWeight: FontWeight.w800)),
          ),
          const SizedBox(width: 12),
          Expanded(child: Text(text, style: const TextStyle(fontSize: 15))),
        ]),
      );
}
