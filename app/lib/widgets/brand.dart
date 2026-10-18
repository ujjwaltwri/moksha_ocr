import 'package:flutter/material.dart';

import '../theme.dart';

/// The NSUT seal on a white disc, so it stays legible on dark backgrounds.
class NsutLogo extends StatelessWidget {
  const NsutLogo({super.key, this.size = 48});

  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      padding: EdgeInsets.all(size * 0.06),
      decoration: const BoxDecoration(
        color: Colors.white,
        shape: BoxShape.circle,
        boxShadow: [
          BoxShadow(
              color: Color(0x22000000), blurRadius: 8, offset: Offset(0, 2))
        ],
      ),
      child: Image.asset('assets/branding/nsut_logo.png',
          filterQuality: FilterQuality.medium, semanticLabel: 'NSUT logo'),
    );
  }
}

/// "MOKSHA 2026 · NSUT" line above screen titles.
class BrandEyebrow extends StatelessWidget {
  const BrandEyebrow({super.key});

  @override
  Widget build(BuildContext context) {
    return const Text(
      'MOKSHA 2026 · NSUT',
      style: TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.w800,
        letterSpacing: 1.6,
        color: GateColors.accent,
      ),
    );
  }
}
