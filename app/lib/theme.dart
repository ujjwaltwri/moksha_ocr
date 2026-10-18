import 'package:flutter/material.dart';

/// Colours picked for readability in bright daylight at a gate.
class GateColors {
  static const ink = Color(0xFF14161A);
  static const inkSoft = Color(0xFF262A33);
  static const paper = Color(0xFFF6F4EF);
  static const accent = Color(0xFFE8740C); // saffron
  static const accentSoft = Color(0xFFFCEBDB);
  static const muted = Color(0xFF6B6E76);
  static const line = Color(0xFFE2DED5);
  static const nsutRed = Color(0xFFE10600); // the college seal

  static const go = Color(0xFF0E8A3E); // green screen
  static const goSoft = Color(0xFFE3F3E8);
  static const stop = Color(0xFFC62828); // red screen
  static const warn = Color(0xFFB26A00);
  static const warnSoft = Color(0xFFFBF0DC);
}

ThemeData buildTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: GateColors.accent,
    primary: GateColors.ink,
    secondary: GateColors.accent,
    surface: GateColors.paper,
    error: GateColors.stop,
  );
  final rounded14 =
      RoundedRectangleBorder(borderRadius: BorderRadius.circular(14));
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: GateColors.paper,
    textTheme: const TextTheme(
      headlineMedium: TextStyle(
          fontSize: 28,
          fontWeight: FontWeight.w800,
          height: 1.15,
          color: GateColors.ink),
      titleMedium: TextStyle(
          fontSize: 16, fontWeight: FontWeight.w700, color: GateColors.ink),
      bodyMedium: TextStyle(fontSize: 15, height: 1.35, color: GateColors.ink),
    ),
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
        disabledBackgroundColor: GateColors.line,
        disabledForegroundColor: GateColors.muted,
        minimumSize: const Size.fromHeight(56),
        textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
        shape: rounded14,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: GateColors.ink,
        backgroundColor: Colors.white,
        minimumSize: const Size.fromHeight(52),
        side: const BorderSide(color: GateColors.line, width: 1.5),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        shape: rounded14,
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: GateColors.line),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: GateColors.line),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: GateColors.accent, width: 2),
      ),
    ),
    cardTheme: CardThemeData(
      color: Colors.white,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: GateColors.line),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: GateColors.ink,
      shape: rounded14,
    ),
  );
}
