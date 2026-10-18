import 'package:flutter/material.dart';

import '../services/sync.dart';
import '../theme.dart';

/// "Online" / "Offline · 12 waiting" pill, used on the home and scan screens.
class SyncBadge extends StatelessWidget {
  const SyncBadge({super.key, required this.sync, this.onDark = false});

  final SyncService sync;
  final bool onDark;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: sync,
      builder: (context, _) {
        final Color dot;
        final String label;
        if (sync.tokenRejected) {
          dot = GateColors.stop;
          label = 'Token rejected';
        } else if (sync.online) {
          dot = const Color(0xFF2ECC71);
          label = sync.pending == 0 ? 'Online' : 'Syncing · ${sync.pending}';
        } else {
          dot = GateColors.warn;
          label = sync.pending == 0
              ? 'Offline'
              : 'Offline · ${sync.pending} waiting';
        }
        final fg = onDark ? Colors.white : GateColors.ink;
        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: onDark ? Colors.black54 : Colors.white,
            borderRadius: BorderRadius.circular(999),
            border: onDark ? null : Border.all(color: GateColors.line),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Container(
              width: 9,
              height: 9,
              decoration: BoxDecoration(color: dot, shape: BoxShape.circle),
            ),
            const SizedBox(width: 8),
            Text(label,
                style: TextStyle(
                    color: fg, fontSize: 13, fontWeight: FontWeight.w600)),
          ]),
        );
      },
    );
  }
}
