import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'screens/home_screen.dart';
import 'screens/setup_screen.dart';
import 'services/app_services.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
  final AppServices services;
  try {
    services = await AppServices.init();
  } catch (e) {
    // Without this the phone sits on the launch screen and looks frozen.
    runApp(_StartupError(e));
    return;
  }
  runApp(Services(services: services, child: const GateApp()));
}

class _StartupError extends StatelessWidget {
  const _StartupError(this.error);
  final Object error;

  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        home: Scaffold(
          body: SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('The app could not start',
                      style: Theme.of(context).textTheme.headlineMedium),
                  const SizedBox(height: 12),
                  const Text('Close it and open it again. If this keeps '
                      'happening, clear the app\'s storage in phone settings '
                      'and scan the setup code again.'),
                  const SizedBox(height: 16),
                  SelectableText('$error',
                      style: const TextStyle(fontSize: 13)),
                ],
              ),
            ),
          ),
        ),
      );
}

class GateApp extends StatefulWidget {
  const GateApp({super.key});

  @override
  State<GateApp> createState() => _GateAppState();
}

class _GateAppState extends State<GateApp> with WidgetsBindingObserver {
  late final AppServices _services = Services.of(context);
  bool _started = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_started) {
      _started = true;
      WidgetsBinding.instance.addObserver(this);
      _services.sync.start();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _services.sync.stop();
    super.dispose();
  }

  // Sync only while the app is in front; catch up straight away on return.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _services.sync.start();
    } else if (state == AppLifecycleState.paused) {
      _services.sync.stop();
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Moksha Gate',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: ListenableBuilder(
        listenable: _services.settings,
        builder: (context, _) => _services.settings.isConfigured
            ? const HomeScreen()
            : const SetupScreen(firstRun: true),
      ),
    );
  }
}
