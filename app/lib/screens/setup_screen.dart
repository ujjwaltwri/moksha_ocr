import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../config.dart';
import '../services/app_services.dart';
import '../theme.dart';
import '../widgets/brand.dart';
import '../widgets/qr_capture.dart';

/// Connects a phone to the server. An admin shows a setup QR from the admin
/// page; scanning it fills every field. Manual entry is the fallback.
///
/// Setup QR content (JSON):
///   {"t":"moksha-gate-setup","url":"https://…","token":"…","gate":"Gate 2","day":1}
class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key, this.firstRun = false});

  final bool firstRun;

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  final _form = GlobalKey<FormState>();
  final _url = TextEditingController();
  final _token = TextEditingController();
  final _gate = TextEditingController();
  late int _day;
  String? _debugKey;
  bool _saving = false;
  bool _loaded = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_loaded) return;
    _loaded = true;
    final s = Services.of(context).settings;
    _url.text = s.serverUrl;
    _token.text = s.deviceToken;
    _gate.text = s.gate;
    _day = s.day;
  }

  @override
  void dispose() {
    _url.dispose();
    _token.dispose();
    _gate.dispose();
    super.dispose();
  }

  Future<void> _scanSetupCode() async {
    final raw = await Navigator.of(context).push<String>(MaterialPageRoute(
        builder: (_) => const QrCaptureScreen(title: 'Scan setup code')));
    if (raw == null || !mounted) return;
    try {
      final j = jsonDecode(raw);
      if (j is! Map || j['t'] != 'moksha-gate-setup') {
        throw const FormatException();
      }
      setState(() {
        _url.text = (j['url'] as String?) ?? _url.text;
        _token.text = (j['token'] as String?) ?? _token.text;
        _gate.text = (j['gate'] as String?) ?? _gate.text;
        final d = j['day'];
        if (d is int && AppConfig.festDays.any((f) => f.number == d)) _day = d;
        _debugKey = j['key'] as String?;
      });
      _snack('Setup code read. Check the details and tap Save.');
    } catch (_) {
      _snack('That is not a gate setup code.');
    }
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _saving = true);
    final app = Services.of(context);
    await app.settings.save(
      serverUrl: _url.text,
      deviceToken: _token.text,
      gate: _gate.text,
      day: _day,
      debugPublicKey: _debugKey,
    );
    app.loadKey();
    app.sync.start();
    if (!mounted) return;
    setState(() => _saving = false);
    if (!widget.firstRun) Navigator.of(context).pop();
  }

  void _snack(String msg) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: widget.firstRun ? null : AppBar(title: const Text('Connection')),
      body: SafeArea(
        child: Form(
          key: _form,
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
                            style: TextStyle(
                                fontSize: 15, color: GateColors.muted)),
                      ],
                    ),
                  ),
                ]),
                const SizedBox(height: 28),
                Text('Set up this phone',
                    style: Theme.of(context).textTheme.headlineMedium),
                const SizedBox(height: 8),
                const Text(
                  'Ask the gate lead to show the setup code from the admin page, then scan it.',
                  style: TextStyle(fontSize: 16, color: GateColors.muted),
                ),
                const SizedBox(height: 24),
              ],
              FilledButton.icon(
                onPressed: _scanSetupCode,
                style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(64)),
                icon: const Icon(Icons.qr_code_scanner, size: 26),
                label: const Text('Scan setup code'),
              ),
              const SizedBox(height: 28),
              const Row(children: [
                Expanded(child: Divider(color: GateColors.line)),
                Padding(
                  padding: EdgeInsets.symmetric(horizontal: 12),
                  child: Text('or enter the details',
                      style: TextStyle(
                          fontWeight: FontWeight.w600,
                          color: GateColors.muted)),
                ),
                Expanded(child: Divider(color: GateColors.line)),
              ]),
              const SizedBox(height: 16),
              TextFormField(
                controller: _url,
                keyboardType: TextInputType.url,
                autocorrect: false,
                decoration: const InputDecoration(
                    labelText: 'Server address',
                    hintText: 'https://api.example.in'),
                validator: (v) {
                  final u = Uri.tryParse(v?.trim() ?? '');
                  if (u == null || !u.hasScheme || u.host.isEmpty) {
                    return 'Enter the full address, starting with https://';
                  }
                  if (u.scheme != 'https' && !kDebugMode) {
                    return 'The server address must start with https://';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _token,
                obscureText: true,
                autocorrect: false,
                decoration: const InputDecoration(labelText: 'Device token'),
                validator: (v) =>
                    (v?.trim().isEmpty ?? true) ? 'Required' : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _gate,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(
                    labelText: 'Gate name', hintText: 'Gate 2, lane 3'),
                validator: (v) =>
                    (v?.trim().isEmpty ?? true) ? 'Required' : null,
              ),
              const SizedBox(height: 14),
              DropdownButtonFormField<int>(
                // initialValue is read once; the key rebuilds the field when
                // a scanned setup code changes the day.
                key: ValueKey(_day),
                initialValue: _day,
                decoration: const InputDecoration(labelText: 'Fest day'),
                items: [
                  for (final d in AppConfig.festDays)
                    DropdownMenuItem(value: d.number, child: Text(d.label)),
                ],
                onChanged: (v) => setState(() => _day = v ?? _day),
              ),
              if (_debugKey != null) ...[
                const SizedBox(height: 12),
                const Text(
                  'Debug build: using the test public key from the setup code.',
                  style: TextStyle(color: GateColors.warn),
                ),
              ],
              const SizedBox(height: 28),
              FilledButton(
                onPressed: _saving ? null : _save,
                style:
                    FilledButton.styleFrom(backgroundColor: GateColors.accent),
                child: Text(_saving ? 'Saving…' : 'Save'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
