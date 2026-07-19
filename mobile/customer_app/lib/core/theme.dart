import 'package:flutter/material.dart';

ThemeData buildLightTheme() {
  const scaffold = Color(0xFFF7F5F0); // Paper / bone
  const surface = Color(0xFFFFFFFF);
  const ink = Color(0xFF0F1112);
  const muted = Color(0xFF6B7280);
  const volt = Color(0xFFD4FF00);
  const accent = Color(0xFF0F1112);

  return ThemeData(
    colorScheme: const ColorScheme(
      brightness: Brightness.light,
      primary: accent,
      onPrimary: Colors.white,
      secondary: volt,
      onSecondary: Colors.black,
      surface: surface,
      onSurface: ink,
      error: Color(0xFFDC2626),
      onError: Colors.white,
    ),
    scaffoldBackgroundColor: scaffold,
    fontFamily: 'Inter',
    appBarTheme: const AppBarTheme(
      backgroundColor: scaffold,
      foregroundColor: ink,
      elevation: 0,
      centerTitle: false,
    ),
    textTheme: const TextTheme(
      displayLarge: TextStyle(fontSize: 40, fontWeight: FontWeight.w900, color: ink, letterSpacing: -1.2),
      titleLarge: TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: ink),
      bodyMedium: TextStyle(fontSize: 14, color: ink),
      labelSmall: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: muted, letterSpacing: 2),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: accent,
        foregroundColor: Colors.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(2)),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(2),
        borderSide: const BorderSide(color: Color(0xFFE4E4E7)),
      ),
    ),
  );
}
