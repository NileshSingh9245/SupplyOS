import 'package:flutter/material.dart';

const volt = Color(0xFFD4FF00);
const charcoal = Color(0xFF0A0A0A);
const monoStyle = TextStyle(
  fontFamily: 'monospace',
  fontWeight: FontWeight.w600,
);

ThemeData adminTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final scheme = ColorScheme.fromSeed(
    seedColor: volt,
    brightness: brightness,
    primary: dark ? volt : const Color(0xFF455900),
    onPrimary: dark ? Colors.black : Colors.white,
    surface: dark ? const Color(0xFF141414) : const Color(0xFFF5F5EF),
  );
  return ThemeData(
    colorScheme: scheme,
    scaffoldBackgroundColor: dark ? charcoal : Colors.white,
    useMaterial3: true,
    visualDensity: VisualDensity.standard,
    textTheme: TextTheme(
      displayLarge: TextStyle(
        fontSize: 44,
        fontWeight: FontWeight.w900,
        letterSpacing: -1.5,
        color: scheme.onSurface,
      ),
      headlineLarge: TextStyle(
        fontSize: 32,
        fontWeight: FontWeight.w900,
        letterSpacing: -1,
        color: scheme.onSurface,
      ),
      titleLarge: TextStyle(
        fontSize: 23,
        fontWeight: FontWeight.w800,
        color: scheme.onSurface,
      ),
      bodyMedium: TextStyle(fontSize: 15, color: scheme.onSurface),
      labelSmall: TextStyle(
        fontFamily: 'monospace',
        fontSize: 12,
        letterSpacing: 1.2,
        color: scheme.onSurfaceVariant,
      ),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: dark ? charcoal : Colors.white,
      elevation: 0,
      centerTitle: false,
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: BorderSide(color: scheme.outlineVariant),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(48, 48),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(3)),
        textStyle: const TextStyle(fontWeight: FontWeight.w800),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(minimumSize: const Size(48, 48)),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(minimumSize: const Size(48, 48)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: scheme.surface,
      border: const OutlineInputBorder(),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 18),
    ),
  );
}
