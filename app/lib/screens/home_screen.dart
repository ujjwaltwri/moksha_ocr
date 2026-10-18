import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../config.dart';
import '../services/api.dart';
import '../services/app_services.dart';
import '../theme.dart';
import '../widgets/sync_badge.dart';
import 'history_screen.dart';
import 'scan_screen.dart';
import 'settings_screen.dart';

/// Before-the-gates-open screen: is this phone ready to scan?
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final app = Services.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Moksha Gate'),
        actions: [
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => openSettings(context),
          ),
        ],
      ),
      body: SafeArea(
        child: ListenableBuilder(
          listenable: Listenable.merge([app.sync, app.settings]),
          builder: (context, _) {
            final sync = app.sync;
            final day = AppConfig.dayInfo(app.settings.day);
            final ready = app.keyError == null && sync.passCount > 0;
            return Column(
              children: [
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: sync.syncNow,
                    child: ListView(
                      padding: const EdgeInsets.fromLTRB(20, 4, 20, 20),
                      children: [
                        _GateHeader(gate: app.settings.gate, day: day),
                        const SizedBox(height: 16),
                        if (app.keyError != null) ...[
                          _Banner(
                              color: GateColors.stop,
                              icon: Icons.error_outline,
                              text: app.keyError!),
                          const SizedBox(height: 16),
                        ],
                        if (sync.conflicts > 0) ...[
                          _Banner(
                            color: GateColors.warn,
                            icon: Icons.warning_amber_rounded,
                            text:
                                '${sync.conflicts} pass(es) were also used at another gate while offline. The help desk sees these on the admin page.',
                          ),
                          const SizedBox(height: 16),
                        ],
                        Row(children: [
                          Expanded(
                              child: _Stat(
                                  label: 'Admitted here today',
                                  value: '${sync.admittedHere}')),
                          const SizedBox(width: 12),
                          Expanded(
                              child: _Stat(
                                  label: 'Passes on phone',
                                  value: NumberFormat.decimalPattern()
                                      .format(sync.passCount))),
                        ]),
                        const SizedBox(height: 16),
                        _PassListCard(app: app),
                        const SizedBox(height: 16),
                        _SyncCard(app: app),
                      ],
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
                  child: Column(children: [
                    if (!ready && app.keyError == null)
                      const Padding(
                        padding: EdgeInsets.only(bottom: 10),
                        child: Text(
                          'Download the pass list before scanning.',
                          style: TextStyle(color: GateColors.muted),
                        ),
                      ),
                    FilledButton.icon(
                      onPressed: ready
                          ? () => Navigator.of(context).push(MaterialPageRoute(
                              builder: (_) => const ScanScreen()))
                          : null,
                      style: FilledButton.styleFrom(
                        backgroundColor: GateColors.accent,
                        minimumSize: const Size.fromHeight(64),
                        textStyle: const TextStyle(
                            fontSize: 20, fontWeight: FontWeight.w800),
                      ),
                      icon: const Icon(Icons.qr_code_scanner, size: 28),
                      label: const Text('Start scanning'),
                    ),
                    const SizedBox(height: 10),
                    OutlinedButton.icon(
                      onPressed: () => Navigator.of(context).push(
                          MaterialPageRoute(
                              builder: (_) => const HistoryScreen())),
                      icon: const Icon(Icons.history),
                      label: const Text('Entry log'),
                    ),
                  ]),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _GateHeader extends StatelessWidget {
  const _GateHeader({required this.gate, required this.day});
  final String gate;
  final FestDay day;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(gate,
                  style: const TextStyle(
                      fontSize: 30,
                      fontWeight: FontWeight.w800,
                      height: 1.1,
                      color: GateColors.ink)),
              const SizedBox(height: 4),
              Text(day.label,
                  style: const TextStyle(
                      fontSize: 16, color: GateColors.muted)),
            ],
          ),
        ),
        WristbandChip(label: '${day.wristband} band', color: day.color),
      ],
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(value,
                style: const TextStyle(
                    fontSize: 32,
                    fontWeight: FontWeight.w800,
                    fontFeatures: [FontFeature.tabularFigures()])),
            const SizedBox(height: 2),
            Text(label, style: const TextStyle(color: GateColors.muted)),
          ],
        ),
      ),
    );
  }
}

class _PassListCard extends StatelessWidget {
  const _PassListCard({required this.app});
  final AppServices app;

  Future<void> _download(BuildContext context, {required bool full}) async {
    try {
      await app.sync.downloadPassList(full: full);
    } on ApiException catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(e.unauthorized
              ? 'Device token rejected. Ask an admin for a new setup code.'
              : 'Download failed: ${e.message}')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sync = app.sync;
    final updated = sync.passListUpdatedAt;
    final empty = sync.passCount == 0;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Pass list',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
            const SizedBox(height: 4),
            Text(
              updated == null
                  ? 'Not downloaded yet. Download it on Wi-Fi before the gates open.'
                  : 'Updated ${_ago(updated)}. New passes and cancellations are picked up every minute while online.',
              style: const TextStyle(color: GateColors.muted),
            ),
            if (sync.downloading) ...[
              const SizedBox(height: 14),
              LinearProgressIndicator(
                value: (sync.downloadTotal ?? 0) > 0
                    ? sync.downloaded / sync.downloadTotal!
                    : null,
                minHeight: 6,
                borderRadius: BorderRadius.circular(3),
              ),
              const SizedBox(height: 6),
              Text(
                sync.downloadTotal == null
                    ? '${sync.downloaded} passes…'
                    : '${sync.downloaded} of ${sync.downloadTotal} passes',
                style: const TextStyle(color: GateColors.muted),
              ),
            ] else ...[
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: () => _download(context, full: empty),
                icon: const Icon(Icons.download),
                label: Text(empty ? 'Download pass list' : 'Check for updates'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SyncCard extends StatelessWidget {
  const _SyncCard({required this.app});
  final AppServices app;

  @override
  Widget build(BuildContext context) {
    final sync = app.sync;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Expanded(
                child: Text('Sync with other gates',
                    style:
                        TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
              ),
              SyncBadge(sync: sync),
            ]),
            const SizedBox(height: 6),
            Text(
              sync.lastSyncAt == null
                  ? 'Not synced yet. Scanning still works offline.'
                  : 'Last synced ${_ago(sync.lastSyncAt!)}. Scanning works offline; entries upload when the network is back.',
              style: const TextStyle(color: GateColors.muted),
            ),
            if (sync.lastError != null) ...[
              const SizedBox(height: 8),
              Text(sync.lastError!,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: GateColors.stop)),
            ],
          ],
        ),
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({required this.color, required this.icon, required this.text});
  final Color color;
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, color: color),
        const SizedBox(width: 10),
        Expanded(child: Text(text, style: TextStyle(color: color))),
      ]),
    );
  }
}

String _ago(DateTime t) {
  final d = DateTime.now().difference(t);
  if (d.inSeconds < 60) return 'just now';
  if (d.inMinutes < 60) return '${d.inMinutes} min ago';
  if (d.inHours < 24) return 'at ${DateFormat.jm().format(t)}';
  return DateFormat.MMMd().add_jm().format(t);
}
