import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models.dart';
import '../services/app_services.dart';
import '../theme.dart';
import '../widgets/sync_badge.dart';

/// Full-screen green or red verdict. Only a green screen has an Admit button.
class ResultScreen extends StatefulWidget {
  const ResultScreen({super.key, required this.outcome});

  final ScanOutcome outcome;

  @override
  State<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends State<ResultScreen> {
  bool _deciding = false;

  Future<void> _admit() async {
    if (_deciding) return;
    setState(() => _deciding = true);
    await Services.of(context).gate.admit(widget.outcome);
    if (mounted) Navigator.of(context).pop();
  }

  Future<void> _deny() async {
    if (_deciding) return;
    final reason = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(20, 0, 20, 8),
            child: Text('Why are you denying entry?',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
          ),
          for (final (code, label, icon) in const [
            ('face_mismatch', 'Face doesn\'t match', Icons.face_retouching_off),
            ('no_id_card', 'No physical ID card', Icons.badge_outlined),
            ('other', 'Other', Icons.more_horiz),
          ])
            ListTile(
              leading: Icon(icon),
              title: Text(label, style: const TextStyle(fontSize: 17)),
              onTap: () => Navigator.of(context).pop(code),
            ),
          const SizedBox(height: 8),
        ]),
      ),
    );
    if (reason == null || !mounted) return;
    setState(() => _deciding = true);
    await Services.of(context).gate.deny(widget.outcome, reason);
    if (!mounted) return;
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final o = widget.outcome;
    final app = Services.of(context);
    final green = o.canAdmit;
    final bg = green ? GateColors.go : GateColors.stop;

    return Scaffold(
      backgroundColor: bg,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(children: [
                Icon(green ? Icons.check_circle : Icons.cancel,
                    color: Colors.white, size: 36),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(o.title,
                      style: const TextStyle(
                          color: Colors.white,
                          fontSize: 26,
                          fontWeight: FontWeight.w900,
                          letterSpacing: 0.5)),
                ),
                SyncBadge(sync: app.sync, onDark: true),
              ]),
              const SizedBox(height: 16),
              Expanded(
                child: green
                    ? _GreenBody(pass: o.pass!)
                    : _RedBody(outcome: o, myDeviceId: app.settings.deviceId),
              ),
              const SizedBox(height: 12),
              if (green)
                Row(children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _deciding ? null : _deny,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: Colors.white,
                        backgroundColor: Colors.transparent,
                        side: const BorderSide(color: Colors.white, width: 2),
                        minimumSize: const Size.fromHeight(72),
                        textStyle: const TextStyle(
                            fontSize: 20, fontWeight: FontWeight.w700),
                      ),
                      child: const Text('Deny'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    flex: 2,
                    child: FilledButton(
                      onPressed: _deciding ? null : _admit,
                      style: FilledButton.styleFrom(
                        backgroundColor: Colors.white,
                        foregroundColor: GateColors.go,
                        minimumSize: const Size.fromHeight(72),
                        textStyle: const TextStyle(
                            fontSize: 24, fontWeight: FontWeight.w900),
                      ),
                      child: const Text('ADMIT'),
                    ),
                  ),
                ])
              else
                FilledButton(
                  onPressed: () => Navigator.of(context).pop(),
                  style: FilledButton.styleFrom(
                    backgroundColor: Colors.white,
                    foregroundColor: GateColors.stop,
                    minimumSize: const Size.fromHeight(72),
                    textStyle: const TextStyle(
                        fontSize: 22, fontWeight: FontWeight.w800),
                  ),
                  child: const Text('Scan next'),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _GreenBody extends StatelessWidget {
  const _GreenBody({required this.pass});
  final PassRecord pass;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Flexible(child: _Photo(pass: pass)),
        const SizedBox(height: 16),
        Text(pass.name,
            textAlign: TextAlign.center,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
                color: Colors.white,
                fontSize: 30,
                fontWeight: FontWeight.w800,
                height: 1.1)),
        const SizedBox(height: 6),
        Text(pass.college,
            textAlign: TextAlign.center,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: Colors.white, fontSize: 18)),
        if (pass.rollNo != null) ...[
          const SizedBox(height: 4),
          Text(pass.rollNo!,
              style: const TextStyle(
                  color: Colors.white70,
                  fontSize: 16,
                  fontFeatures: [FontFeature.tabularFigures()])),
        ],
        const SizedBox(height: 14),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: Colors.black.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(12),
          ),
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.badge_outlined, color: Colors.white),
            SizedBox(width: 8),
            Flexible(
              child: Text('Compare the face and check the physical ID card.',
                  style: TextStyle(color: Colors.white, fontSize: 15)),
            ),
          ]),
        ),
      ],
    );
  }
}

class _RedBody extends StatelessWidget {
  const _RedBody({required this.outcome, required this.myDeviceId});
  final ScanOutcome outcome;
  final String myDeviceId;

  String get _detail {
    final o = outcome;
    switch (o.status) {
      case ScanStatus.alreadyUsed:
        final f = o.firstEntry!;
        final where = f.deviceId == myDeviceId ? 'this phone' : f.gate;
        return 'Already entered at $where at ${DateFormat.jm().format(f.scannedAt)}.';
      case ScanStatus.wrongDay:
        final days = o.token!.days.map((d) => 'Day $d').join(', ');
        return 'This pass is for $days only.';
      case ScanStatus.notFound:
        return 'The pass is genuine but not on this phone\'s list. It may have been issued late.';
      case ScanStatus.revoked:
        return 'This pass has been cancelled by the organisers.';
      case ScanStatus.wrongEvent:
        return 'This pass is for a different event.';
      case ScanStatus.invalidSignature:
        return 'This QR was not issued by Moksha. It may be edited or fake.';
      case ScanStatus.notAPass:
        return 'This QR code is not a Moksha pass.';
      case ScanStatus.valid:
        return '';
    }
  }

  @override
  Widget build(BuildContext context) {
    final pass = outcome.pass;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(_detail,
            style: const TextStyle(
                color: Colors.white,
                fontSize: 22,
                fontWeight: FontWeight.w600,
                height: 1.25)),
        const SizedBox(height: 18),
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: Colors.black.withValues(alpha: 0.18),
            borderRadius: BorderRadius.circular(14),
          ),
          child: const Row(children: [
            Icon(Icons.do_not_disturb_on, color: Colors.white),
            SizedBox(width: 10),
            Expanded(
              child: Text('Do not admit. Send them to the help desk.',
                  style: TextStyle(
                      color: Colors.white,
                      fontSize: 17,
                      fontWeight: FontWeight.w700)),
            ),
          ]),
        ),
        const SizedBox(height: 18),
        // For a real pass, show who it belongs to: helps spot a shared
        // screenshot, and helps the help desk.
        if (pass != null)
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox.square(
                    dimension: 120, child: _Photo(pass: pass, small: true)),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Pass belongs to',
                          style:
                              TextStyle(color: Colors.white70, fontSize: 13)),
                      const SizedBox(height: 2),
                      Text(pass.name,
                          style: const TextStyle(
                              color: Colors.white,
                              fontSize: 20,
                              fontWeight: FontWeight.w700)),
                      Text(pass.college,
                          style: const TextStyle(
                              color: Colors.white, fontSize: 15)),
                      if (pass.rollNo != null)
                        Text(pass.rollNo!,
                            style: const TextStyle(
                                color: Colors.white70, fontSize: 14)),
                    ],
                  ),
                ),
              ],
            ),
          )
        else
          const Spacer(),
      ],
    );
  }
}

class _Photo extends StatelessWidget {
  const _Photo({required this.pass, this.small = false});
  final PassRecord pass;
  final bool small;

  @override
  Widget build(BuildContext context) {
    final radius = BorderRadius.circular(small ? 12 : 20);
    final thumb = pass.thumb;
    return Center(
      // Hug the photo instead of filling the height, so the name sits right
      // under it.
      heightFactor: 1,
      child: AspectRatio(
        aspectRatio: 1,
        child: Container(
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.15),
            borderRadius: radius,
            border: Border.all(color: Colors.white, width: small ? 2 : 4),
          ),
          child: ClipRRect(
            borderRadius: radius,
            child: thumb == null
                ? Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.person_outline,
                          color: Colors.white70, size: small ? 40 : 96),
                      if (!small)
                        const Padding(
                          padding: EdgeInsets.all(12),
                          child: Text('No photo on file — check the ID card',
                              textAlign: TextAlign.center,
                              style: TextStyle(color: Colors.white)),
                        ),
                    ],
                  )
                : Image.memory(
                    thumb,
                    fit: BoxFit.cover,
                    gaplessPlayback: true,
                    filterQuality: FilterQuality.medium,
                  ),
          ),
        ),
      ),
    );
  }
}
