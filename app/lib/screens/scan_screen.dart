import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../config.dart';
import '../services/app_services.dart';
import '../theme.dart';
import '../widgets/sync_badge.dart';
import 'result_screen.dart';

/// The camera screen volunteers keep open at the gate.
class ScanScreen extends StatefulWidget {
  const ScanScreen({super.key});

  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> with WidgetsBindingObserver {
  final _controller = MobileScannerController(
    formats: const [BarcodeFormat.qrCode],
    detectionSpeed: DetectionSpeed.normal,
  );

  bool _busy = false;
  String? _lastRaw;
  DateTime _lastDoneAt = DateTime.fromMillisecondsSinceEpoch(0);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WakelockPlus.enable();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    WakelockPlus.disable();
    _controller.dispose();
    super.dispose();
  }

  // Release the camera when the app goes to the background, and take it
  // back when the volunteer returns.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!_controller.value.hasCameraPermission) return;
    switch (state) {
      case AppLifecycleState.resumed:
        _controller.start().catchError((_) {});
        WakelockPlus.enable();
      case AppLifecycleState.inactive:
      case AppLifecycleState.paused:
        _controller.stop().catchError((_) {});
      default:
        break;
    }
  }

  Future<void> _onDetect(BarcodeCapture capture) async {
    if (_busy) return;
    String? raw;
    for (final b in capture.barcodes) {
      if (b.rawValue != null && b.rawValue!.isNotEmpty) {
        raw = b.rawValue;
        break;
      }
    }
    if (raw == null) return;

    // The student is often still holding the same QR up after a decision.
    if (raw == _lastRaw &&
        DateTime.now().difference(_lastDoneAt) < AppConfig.rescanCooldown) {
      return;
    }

    _busy = true;
    final app = Services.of(context);
    try {
      final outcome = await app.gate.evaluate(raw);
      if (outcome.canAdmit) {
        HapticFeedback.mediumImpact();
      } else {
        HapticFeedback.heavyImpact();
        app.gate.logRejected(outcome);
      }
      if (!mounted) return;
      await Navigator.of(context).push(PageRouteBuilder(
        opaque: true,
        transitionDuration: const Duration(milliseconds: 120),
        reverseTransitionDuration: const Duration(milliseconds: 80),
        pageBuilder: (_, __, ___) => ResultScreen(outcome: outcome),
        transitionsBuilder: (_, anim, __, child) =>
            FadeTransition(opacity: anim, child: child),
      ));
    } finally {
      _lastRaw = raw;
      _lastDoneAt = DateTime.now();
      _busy = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = Services.of(context);
    final day = AppConfig.dayInfo(app.settings.day);
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          MobileScanner(controller: _controller, onDetect: _onDetect),
          const _Viewfinder(),
          // Camera problems (permission denied, camera in use).
          ValueListenableBuilder<MobileScannerState>(
            valueListenable: _controller,
            builder: (context, state, _) => state.error == null
                ? const SizedBox.shrink()
                : _CameraError(message: _cameraErrorText(state.error!)),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                children: [
                  Row(children: [
                    _RoundButton(
                      icon: Icons.arrow_back,
                      tooltip: 'Stop scanning',
                      onTap: () => Navigator.of(context).pop(),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        app.settings.gate,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            color: Colors.white,
                            fontSize: 18,
                            fontWeight: FontWeight.w700),
                      ),
                    ),
                    SyncBadge(sync: app.sync, onDark: true),
                  ]),
                  const Spacer(),
                  const Text(
                    'Point at the QR pass',
                    style: TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                        fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 24),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Expanded(
                        child: ListenableBuilder(
                          listenable: app.sync,
                          builder: (context, _) => Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text('${app.sync.admittedHere}',
                                  style: const TextStyle(
                                      color: Colors.white,
                                      fontSize: 34,
                                      fontWeight: FontWeight.w800,
                                      height: 1)),
                              const SizedBox(height: 4),
                              Text('admitted here · ${day.label}',
                                  style: const TextStyle(
                                      color: Colors.white70, fontSize: 13)),
                            ],
                          ),
                        ),
                      ),
                      ValueListenableBuilder<MobileScannerState>(
                        valueListenable: _controller,
                        builder: (context, state, _) {
                          if (state.torchState == TorchState.unavailable) {
                            return const SizedBox.shrink();
                          }
                          final on = state.torchState == TorchState.on;
                          return _RoundButton(
                            icon: on ? Icons.flash_on : Icons.flash_off,
                            tooltip: 'Torch',
                            highlighted: on,
                            onTap: _controller.toggleTorch,
                          );
                        },
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _cameraErrorText(MobileScannerException e) =>
      e.errorCode == MobileScannerErrorCode.permissionDenied
          ? 'Camera access is off. Allow camera access for Moksha Gate in the phone\'s Settings, then come back.'
          : 'The camera could not start (${e.errorCode.name}). Close other camera apps and try again.';
}

/// Dark scrim with a clear square in the middle.
class _Viewfinder extends StatelessWidget {
  const _Viewfinder();

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: LayoutBuilder(builder: (context, c) {
        final side = c.maxWidth * 0.72;
        final rect = Rect.fromCenter(
            center: Offset(c.maxWidth / 2, c.maxHeight * 0.45),
            width: side,
            height: side);
        return CustomPaint(painter: _ViewfinderPainter(rect));
      }),
    );
  }
}

class _ViewfinderPainter extends CustomPainter {
  _ViewfinderPainter(this.window);
  final Rect window;

  @override
  void paint(Canvas canvas, Size size) {
    final rrect = RRect.fromRectAndRadius(window, const Radius.circular(24));
    final scrim = Path()
      ..addRect(Offset.zero & size)
      ..addRRect(rrect)
      ..fillType = PathFillType.evenOdd;
    canvas.drawPath(scrim, Paint()..color = Colors.black.withValues(alpha: 0.55));

    // Corner brackets.
    final p = Paint()
      ..color = GateColors.accent
      ..style = PaintingStyle.stroke
      ..strokeWidth = 6
      ..strokeCap = StrokeCap.round;
    const len = 36.0;
    final r = window;
    for (final (corner, dx, dy) in [
      (r.topLeft, 1.0, 1.0),
      (r.topRight, -1.0, 1.0),
      (r.bottomLeft, 1.0, -1.0),
      (r.bottomRight, -1.0, -1.0),
    ]) {
      canvas.drawLine(corner, corner + Offset(len * dx, 0), p);
      canvas.drawLine(corner, corner + Offset(0, len * dy), p);
    }
  }

  @override
  bool shouldRepaint(_ViewfinderPainter old) => old.window != window;
}

class _RoundButton extends StatelessWidget {
  const _RoundButton({
    required this.icon,
    required this.onTap,
    required this.tooltip,
    this.highlighted = false,
  });

  final IconData icon;
  final VoidCallback onTap;
  final String tooltip;
  final bool highlighted;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Material(
        color: highlighted ? GateColors.accent : Colors.black54,
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: onTap,
          child: SizedBox(
              width: 52,
              height: 52,
              child: Icon(icon, color: Colors.white, size: 26)),
        ),
      ),
    );
  }
}

class _CameraError extends StatelessWidget {
  const _CameraError({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.black,
      alignment: Alignment.center,
      padding: const EdgeInsets.all(32),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const Icon(Icons.no_photography_outlined,
            color: Colors.white70, size: 56),
        const SizedBox(height: 16),
        Text(message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white, fontSize: 17)),
      ]),
    );
  }
}
