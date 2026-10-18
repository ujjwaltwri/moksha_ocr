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

/// Small coloured chip naming today's wristband.
class WristbandChip extends StatelessWidget {
  const WristbandChip(
      {super.key, required this.label, required this.color, this.large = false});

  final String label;
  final Color color;
  final bool large;

  @override
  Widget build(BuildContext context) {
    final dark = color.computeLuminance() < 0.5;
    return Container(
      padding: EdgeInsets.symmetric(
          horizontal: large ? 16 : 10, vertical: large ? 8 : 4),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: Colors.white, width: large ? 2 : 0),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: dark ? Colors.white : GateColors.ink,
          fontWeight: FontWeight.w800,
          fontSize: large ? 18 : 12,
          letterSpacing: 0.3,
        ),
      ),
    );
  }
}
