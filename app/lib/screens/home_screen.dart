import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../config.dart';
import '../services/api.dart';
import '../services/app_services.dart';
import '../theme.dart';
import '../widgets/brand.dart';
import '../widgets/sync_badge.dart';
import 'scan_screen.dart';
import 'settings_screen.dart';

/// Before-the-gates-open screen: is this phone ready to scan?
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final app = Services.of(context);
    return Scaffold(
      body: SafeArea(
        child: ListenableBuilder(
          listenable: Listenable.merge([app.sync, app.settings]),
          builder: (context, _) {
            final sync = app.sync;
            final ready = app.keyError == null && sync.passCount > 0;
            return Column(
              children: [
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: sync.syncNow,
                    child: ListView(
                      padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
                      children: [
                        _GateHeader(app: app),
                        const SizedBox(height: 16),
                        if (sync.conflicts > 0) ...[
                          _Banner(
                            color: GateColors.warn,
                            icon: Icons.warning_amber_rounded,
                            text:
                                '${sync.conflicts} pass(es) were also used at another gate while offline. The help desk sees these on the admin page.',
                          ),
                          const SizedBox(height: 16),
                        ],
                        _ReadyCard(app: app),
                        const SizedBox(height: 16),
                        Row(children: [
                          Expanded(
                              child: _Stat(
                                  label: 'Admitted at this gate',
                                  value: sync.admittedHere)),
                          const SizedBox(width: 12),
                          Expanded(
                              child: _Stat(
                                  label: 'Admitted at all gates',
                                  value: sync.admittedAll)),
                        ]),
                      ],
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
                  child: FilledButton.icon(
                    onPressed: ready
                        ? () => Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) => const ScanScreen()))
                        : null,
                    style: FilledButton.styleFrom(
                      backgroundColor: GateColors.accent,
                      minimumSize: const Size.fromHeight(68),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(18)),
                      textStyle: const TextStyle(
                          fontSize: 20, fontWeight: FontWeight.w800),
                    ),
                    icon: const Icon(Icons.qr_code_scanner, size: 28),
                    label: Text(ready ? 'Scan passes' : 'Not ready to scan'),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

/// Dark card naming this gate and today's fest day.
class _GateHeader extends StatelessWidget {
  const _GateHeader({required this.app});
  final AppServices app;

  @override
  Widget build(BuildContext context) {
    final day = AppConfig.dayInfo(app.settings.day);
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 16, 10, 20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(22),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [GateColors.inkSoft, GateColors.ink],
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const NsutLogo(size: 44),
            const SizedBox(width: 12),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  BrandEyebrow(),
                  SizedBox(height: 2),
                  Text('Gate scanner',
                      style: TextStyle(color: Colors.white70, fontSize: 14)),
                ],
              ),
            ),
            IconButton(
              tooltip: 'Gate lead settings',
              color: Colors.white70,
              icon: const Icon(Icons.settings_outlined),
              onPressed: () => openSettings(context),
            ),
          ]),
          const SizedBox(height: 22),
          Text(app.settings.gate,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                  color: Colors.white,
                  fontSize: 32,
                  fontWeight: FontWeight.w800,
                  height: 1.1)),
          const SizedBox(height: 10),
          Row(children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: GateColors.accent,
                borderRadius: BorderRadius.circular(999),
              ),
              child: Text(day.label,
                  style: const TextStyle(
                      color: Colors.white,
                      fontSize: 13,
                      fontWeight: FontWeight.w800)),
            ),
            const SizedBox(width: 8),
            SyncBadge(sync: app.sync, onDark: true),
          ]),
        ],
      ),
    );
  }
}

/// The three things a phone needs before the gates open.
class _ReadyCard extends StatelessWidget {
  const _ReadyCard({required this.app});
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
    final empty = sync.passCount == 0;
    final updated = sync.passListUpdatedAt;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Ready to scan?',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            _Check(
              ok: app.keyError == null,
              title: 'Pass key',
              detail: app.keyError ?? 'Built in. Fake or edited QRs show red.',
            ),
            _Check(
              ok: !empty,
              title: empty
                  ? 'Pass list'
                  : '${NumberFormat.decimalPattern().format(sync.passCount)} passes on this phone',
              detail: empty
                  ? 'Not downloaded. Download it on Wi-Fi before the gates open.'
                  : 'Updated ${_ago(updated)}. Changes arrive every minute while online.',
              trailing: sync.downloading
                  ? null
                  : TextButton(
                      onPressed: () => _download(context, full: empty),
                      child: Text(empty ? 'Download' : 'Update'),
                    ),
            ),
            if (sync.downloading)
              Padding(
                padding: const EdgeInsets.fromLTRB(36, 0, 0, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    LinearProgressIndicator(
                      value: (sync.downloadTotal ?? 0) > 0
                          ? sync.downloaded / sync.downloadTotal!
                          : null,
                      minHeight: 6,
                      color: GateColors.accent,
                      backgroundColor: GateColors.accentSoft,
                      borderRadius: BorderRadius.circular(3),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      sync.downloadTotal == null
                          ? '${sync.downloaded} passes…'
                          : '${sync.downloaded} of ${sync.downloadTotal} passes',
                      style: const TextStyle(color: GateColors.muted),
                    ),
                  ],
                ),
              ),
            _Check(
              ok: sync.online,
              optional: true,
              title: sync.online ? 'Synced with other gates' : 'Offline',
              detail: sync.lastError ??
                  (sync.lastSyncAt == null
                      ? 'Scanning works offline; entries upload when the network is back.'
                      : 'Last synced ${_ago(sync.lastSyncAt)}.'),
            ),
          ],
        ),
      ),
    );
  }
}

class _Check extends StatelessWidget {
  const _Check({
    required this.ok,
    required this.title,
    required this.detail,
    this.optional = false,
    this.trailing,
  });

  final bool ok;
  final String title;
  final String detail;

  /// Not needed to scan: shown amber instead of red when missing.
  final bool optional;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final (icon, color) = ok
        ? (Icons.check_circle, GateColors.go)
        : optional
            ? (Icons.cloud_off_outlined, GateColors.warn)
            : (Icons.error, GateColors.stop);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, color: color, size: 24),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title,
                  style: const TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 2),
              Text(detail,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      color:
                          ok || optional ? GateColors.muted : GateColors.stop,
                      fontSize: 13.5)),
            ],
          ),
        ),
        if (trailing != null) trailing!,
      ]),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value});
  final String label;
  final int value;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(NumberFormat.decimalPattern().format(value),
                style: const TextStyle(
                    fontSize: 32,
                    fontWeight: FontWeight.w800,
                    height: 1.1,
                    fontFeatures: [FontFeature.tabularFigures()])),
            const SizedBox(height: 4),
            Text(label,
                style: const TextStyle(color: GateColors.muted, fontSize: 13)),
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

String _ago(DateTime? t) {
  if (t == null) return 'never';
  final d = DateTime.now().difference(t);
  if (d.inSeconds < 60) return 'just now';
  if (d.inMinutes < 60) return '${d.inMinutes} min ago';
  if (d.inHours < 24) return 'at ${DateFormat.jm().format(t)}';
  return DateFormat.MMMd().add_jm().format(t);
}
