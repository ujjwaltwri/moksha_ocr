import 'package:flutter/material.dart';

/// Colours picked for readability in bright daylight at a gate.
class GateColors {
  static const ink = Color(0xFF14161A);
  static const paper = Color(0xFFF6F4EF);
  static const accent = Color(0xFFE8740C); // saffron
  static const muted = Color(0xFF6B6E76);
  static const line = Color(0xFFE2DED5);

  static const go = Color(0xFF0E8A3E); // green screen
  static const stop = Color(0xFFC62828); // red screen
  static const warn = Color(0xFFB26A00);
}

ThemeData buildTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: GateColors.accent,
    primary: GateColors.ink,
    secondary: GateColors.accent,
    surface: GateColors.paper,
    error: GateColors.stop,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: GateColors.paper,
    appBarTheme: const AppBarTheme(
      backgroundColor: GateColors.paper,
      foregroundColor: GateColors.ink,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
          color: GateColors.ink, fontSize: 20, fontWeight: FontWeight.w700),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: GateColors.ink,
        foregroundColor: Colors.white,
        minimumSize: const Size.fromHeight(56),
        textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: GateColors.ink,
        minimumSize: const Size.fromHeight(52),
        side: const BorderSide(color: GateColors.line, width: 1.5),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: GateColors.line),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: GateColors.line),
      ),
    ),
    cardTheme: CardThemeData(
      color: Colors.white,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: const BorderSide(color: GateColors.line),
      ),
    ),
  );
}
