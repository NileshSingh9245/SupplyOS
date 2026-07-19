import 'package:flutter/material.dart';

ThemeData buildDarkTheme() {
  const bg = Color(0xFF0A0A0A);
  const surface = Color(0xFF141414);
  const border = Color(0xFF2E2E2E);
  const text = Color(0xFFFFFFFF);
  const muted = Color(0xFFA3A3A3);
  const volt = Color(0xFFD4FF00);

  return ThemeData(
    brightness: Brightness.dark,
    colorScheme: const ColorScheme(
      brightness: Brightness.dark,
      primary: volt,
      onPrimary: Colors.black,
      secondary: volt,
      onSecondary: Colors.black,
      surface: surface,
      onSurface: text,
      error: Color(0xFFFF3B30),
      onError: Colors.white,
    ),
    scaffoldBackgroundColor: bg,
    appBarTheme: const AppBarTheme(
      backgroundColor: bg, foregroundColor: text, elevation: 0, centerTitle: false,
    ),
    textTheme: const TextTheme(
      displayLarge: TextStyle(fontSize: 40, fontWeight: FontWeight.w900, color: text, letterSpacing: -1.5),
      titleLarge: TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: text),
      bodyMedium: TextStyle(fontSize: 15, color: text),
      labelSmall: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: muted, letterSpacing: 2.4),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: volt, foregroundColor: Colors.black,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(2)),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
        textStyle: const TextStyle(fontWeight: FontWeight.w700),
      ),
    ),
    inputDecorationTheme: const InputDecorationTheme(
      filled: true,
      fillColor: Color(0xFF0F0F0F),
      border: OutlineInputBorder(
        borderSide: BorderSide(color: border),
      ),
    ),
  );
}
