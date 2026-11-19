/// Type: three of Windows' own faces, each with one job.
/// - Arial Black, upper case, for the one display line per screen (PROTECTED, SERVERS, SETTINGS): a slab you read
///   from across the room.
/// - Segoe UI Variable Text: SemiBold (600) for titles, labels and values, Regular for secondary text.
/// - Cascadia Mono SemiBold for values: addresses, milliseconds, megabits.
/// System fonts only: nothing bundled, nothing downloaded. Arial Black is registered from the Windows fonts folder
/// at start ([loadDisplayFont]), so tests and goldens draw the real face too.
///
/// The scale: 12 / 13 / 14 / 16 / 20 / 24; weights 400 and 600 (and Arial Black for the display line).
library;

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

abstract final class NbFont {
  static const body = 'Segoe UI Variable Text';
  static const bodyFallback = ['Segoe UI', 'Segoe UI Emoji', 'Segoe UI Symbol'];
  static const mono = 'Cascadia Mono';
  static const monoFallback = ['Consolas', 'Segoe UI'];
  static const display = 'NOBAD Display';
  static const displayFallback = ['Arial Black', 'Arial', 'Segoe UI'];
}

/// Registers C:\Windows\Fonts\ariblk.ttf as [NbFont.display] (and, for tests, the reading and data faces under
/// their own names). Missing files: the fallbacks draw it.
Future<void> loadDisplayFont({bool all = false}) async {
  final dir = '${Platform.environment['WINDIR'] ?? r'C:\Windows'}${Platform.pathSeparator}Fonts';
  Future<void> load(String family, List<String> files) async {
    final loader = FontLoader(family);
    var any = false;
    for (final name in files) {
      final f = File('$dir${Platform.pathSeparator}$name');
      if (!f.existsSync()) continue;
      loader.addFont(f.readAsBytes().then(ByteData.sublistView));
      any = true;
    }
    if (any) await loader.load();
  }

  try {
    await load(NbFont.display, ['ariblk.ttf']);
    if (all) {
      await load(NbFont.body, ['SegUIVar.ttf', 'segoeui.ttf']);
      await load('Segoe UI', ['segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf']);
      await load(NbFont.mono, ['CascadiaMono.ttf', 'consola.ttf']);
      await load('Segoe UI Symbol', ['seguisym.ttf']);
    }
  } on Object {
    // the fallbacks draw it
  }
}

/// Compact, like a desktop tool: reading text 13, the display line 22-26 at most.
abstract final class NbSize {
  static const caption = 12.0;
  static const small = 12.0;
  static const body = 13.0;
  static const title = 14.0;
  static const lead = 16.0;
  static const field = 20.0;
  static const page = 24.0;
}

abstract final class NbType {
  /// Reading text: Segoe UI Variable Text, Regular for secondary text, never lighter than 400.
  static TextStyle text(double size, Color color, {FontWeight weight = FontWeight.w400, double? height}) => TextStyle(
    fontFamily: NbFont.body,
    fontFamilyFallback: NbFont.bodyFallback,
    fontSize: size,
    fontWeight: weight.value < 400 ? FontWeight.w400 : weight,
    fontVariations: [FontVariation('wght', (weight.value < 400 ? 400 : weight.value).toDouble())],
    color: color,
    height: height,
    letterSpacing: size >= NbSize.lead ? -0.01 * size : 0,
  );

  /// Values: Cascadia Mono SemiBold (its weight axis at 600), tabular figures.
  static TextStyle data(double size, Color color, {FontWeight weight = FontWeight.w600, double? height}) => TextStyle(
    fontFamily: NbFont.mono,
    fontFamilyFallback: NbFont.monoFallback,
    fontSize: size,
    fontWeight: weight,
    fontVariations: [FontVariation('wght', weight.value.toDouble())],
    color: color,
    height: height,
    fontFeatures: const [FontFeature.tabularFigures()],
  );

  /// Titles, labels and values in reading text: Segoe UI Variable Text SemiBold.
  static TextStyle label(double size, Color color, {double? height}) => text(size, color, weight: FontWeight.w600, height: height);

  /// The display line: Arial Black, tight. Callers pass the text upper case (it's the brief's only upper case).
  static TextStyle display(double size, Color color) => TextStyle(
    fontFamily: NbFont.display,
    fontFamilyFallback: NbFont.displayFallback,
    fontSize: size,
    fontWeight: FontWeight.w900,
    color: color,
    height: .92,
    letterSpacing: -0.035 * size,
  );
}
