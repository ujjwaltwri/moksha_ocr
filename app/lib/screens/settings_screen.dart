import 'package:flutter/material.dart';

import '../config.dart';
import '../services/api.dart';
import '../services/app_services.dart';
import '../theme.dart';
import 'history_screen.dart';
import 'setup_screen.dart';

/// Opens settings after the gate lead enters the admin PIN, so volunteers
/// can't change the day or wipe the pass list by accident.
Future<void> openSettings(BuildContext context) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (_) => const _PinDialog(),
  );
  if (ok == true && context.mounted) {
    await Navigator.of(context)
        .push(MaterialPageRoute(builder: (_) => const SettingsScreen()));
  }
}

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final app = Services.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Gate lead settings')),
      body: ListenableBuilder(
        listenable: Listenable.merge([app.settings, app.sync]),
        builder: (context, _) => ListView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
          children: [
            const _Heading('Fest day'),
            SegmentedButton<int>(
              segments: [
                for (final d in AppConfig.festDays)
                  ButtonSegment(value: d.number, label: Text(d.label)),
              ],
              selected: {app.settings.day},
              onSelectionChanged: (s) async {
                await app.settings.setDay(s.first);
                await app.sync.refreshCounts();
              },
            ),
            const SizedBox(height: 6),
            const Text(
              'Passes that don\'t include this day show red.',
              style: TextStyle(color: GateColors.muted),
            ),
            const _Heading('Connection'),
            _InfoRow('Gate', app.settings.gate),
            _InfoRow('Server', app.settings.serverUrl),
            _InfoRow('Device ID', app.settings.deviceId),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              icon: const Icon(Icons.edit_outlined),
              label: const Text('Change connection or gate name'),
              onPressed: () => Navigator.of(context)
                  .push(MaterialPageRoute(builder: (_) => const SetupScreen())),
            ),
            const _Heading('Entries'),
            OutlinedButton.icon(
              icon: const Icon(Icons.history),
              label: const Text('Entry log for this phone'),
              onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const HistoryScreen())),
            ),
            const _Heading('Pass list'),
            OutlinedButton.icon(
              icon: const Icon(Icons.refresh),
              label: const Text('Download the whole list again'),
              onPressed: app.sync.downloading
                  ? null
                  : () async {
                      try {
                        await app.sync.downloadPassList(full: true);
                      } on ApiException catch (e) {
                        if (!context.mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text('Failed: ${e.message}')));
                      }
                    },
            ),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              icon: const Icon(Icons.delete_outline, color: GateColors.stop),
              style: OutlinedButton.styleFrom(foregroundColor: GateColors.stop),
              label: const Text('Clear for a new day'),
              onPressed: () => _confirmWipe(context, app),
            ),
            const SizedBox(height: 6),
            const Text(
              'Removes the pass list and uploaded entries from this phone. '
              'Entries not yet uploaded are kept.',
              style: TextStyle(color: GateColors.muted),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmWipe(BuildContext context, AppServices app) async {
    final pending = app.sync.pending;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Clear this phone?'),
        content: Text(pending > 0
            ? '$pending entries haven\'t uploaded yet. They will be kept, but connect to the network soon so they reach the server.'
            : 'The pass list will need downloading again before scanning.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Clear',
                  style: TextStyle(color: GateColors.stop))),
        ],
      ),
    );
    if (ok != true) return;
    await app.db.wipeForNewDay();
    await app.sync.refreshCounts();
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Cleared. Download the new pass list.')));
    }
  }
}

class _Heading extends StatelessWidget {
  const _Heading(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 24, bottom: 10),
        child: Text(text,
            style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w800,
                letterSpacing: 0.8,
                color: GateColors.muted)),
      );
}

class _InfoRow extends StatelessWidget {
  const _InfoRow(this.label, this.value);
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(
              width: 90,
              child:
                  Text(label, style: const TextStyle(color: GateColors.muted))),
          Expanded(
              child: SelectableText(value,
                  style: const TextStyle(fontWeight: FontWeight.w600))),
        ]),
      );
}

class _PinDialog extends StatefulWidget {
  const _PinDialog();

  @override
  State<_PinDialog> createState() => _PinDialogState();
}

class _PinDialogState extends State<_PinDialog> {
  final _pin = TextEditingController();
  bool _wrong = false;

  @override
  void dispose() {
    _pin.dispose();
    super.dispose();
  }

  void _submit() {
    if (_pin.text == AppConfig.adminPin) {
      Navigator.pop(context, true);
    } else {
      setState(() => _wrong = true);
      _pin.clear();
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Gate lead PIN'),
      content: TextField(
        controller: _pin,
        autofocus: true,
        obscureText: true,
        keyboardType: TextInputType.number,
        onSubmitted: (_) => _submit(),
        decoration: InputDecoration(errorText: _wrong ? 'Wrong PIN' : null),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel')),
        TextButton(onPressed: _submit, child: const Text('Open')),
      ],
    );
  }
}
