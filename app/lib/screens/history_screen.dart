import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models.dart';
import '../services/app_services.dart';
import '../theme.dart';

/// This phone's recent decisions, newest first.
class HistoryScreen extends StatelessWidget {
  const HistoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final app = Services.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Entry log')),
      body: ListenableBuilder(
        listenable: app.sync,
        builder: (context, _) => FutureBuilder(
          future: app.db.recentLocal(limit: 300),
          builder: (context, snap) {
            final rows = snap.data;
            if (rows == null) {
              return const Center(child: CircularProgressIndicator());
            }
            if (rows.isEmpty) {
              return const Center(
                child: Text('No entries yet on this phone.',
                    style: TextStyle(color: GateColors.muted, fontSize: 16)),
              );
            }
            return ListView.separated(
              padding: const EdgeInsets.symmetric(vertical: 8),
              itemCount: rows.length,
              separatorBuilder: (_, __) =>
                  const Divider(height: 1, indent: 76, color: GateColors.line),
              itemBuilder: (context, i) {
                final (c, pass) = rows[i];
                return _Row(checkin: c, pass: pass);
              },
            );
          },
        ),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.checkin, required this.pass});
  final Checkin checkin;
  final PassRecord? pass;

  @override
  Widget build(BuildContext context) {
    final c = checkin;
    final (color, icon, label) = switch (c.result) {
      CheckinResult.admitted => (GateColors.go, Icons.check_circle, 'Admitted'),
      CheckinResult.denied => (GateColors.stop, Icons.cancel, 'Denied'),
      CheckinResult.duplicate =>
        (GateColors.warn, Icons.content_copy, 'Already used'),
    };
    final reason = c.reason == null || c.result == CheckinResult.duplicate
        ? ''
        : ' · ${_reasonText(c.reason!)}';
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      leading: CircleAvatar(
        radius: 26,
        backgroundColor: GateColors.line,
        backgroundImage: pass?.thumb == null ? null : MemoryImage(pass!.thumb!),
        child: pass?.thumb == null
            ? const Icon(Icons.person_outline, color: GateColors.muted)
            : null,
      ),
      title: Text(pass?.name ?? 'Unknown pass',
          style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text(
        '${DateFormat.jm().format(c.scannedAt)} · Day ${c.day}$reason',
        style: const TextStyle(color: GateColors.muted),
      ),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, color: color, size: 18),
            const SizedBox(width: 4),
            Text(label,
                style: TextStyle(color: color, fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 4),
          Icon(
            c.conflict
                ? Icons.warning_amber_rounded
                : c.synced
                    ? Icons.cloud_done_outlined
                    : Icons.cloud_upload_outlined,
            size: 16,
            color: c.conflict ? GateColors.warn : GateColors.muted,
          ),
        ],
      ),
    );
  }

  static String _reasonText(String code) => switch (code) {
        'face_mismatch' => 'face didn\'t match',
        'no_id_card' => 'no ID card',
        'not_a_pass' => 'not a pass',
        'bad_signature' => 'fake QR',
        'wrong_event' => 'wrong event',
        'wrong_day' => 'wrong day',
        'not_in_list' => 'not on list',
        'revoked' => 'cancelled',
        _ => code,
      };
}
