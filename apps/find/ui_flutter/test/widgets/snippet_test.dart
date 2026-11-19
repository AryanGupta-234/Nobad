import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/app/theme/colors.dart';
import 'package:nobad_find/widgets/common.dart';

void main() {
  test('a snippet is one line of words, with the matches marked', () {
    final spans = snippetSpans(
      'tax checklist.md\n\n  your \x02tax\x03 refund\tis\r\nhere',
      const TextStyle(),
      NbColors.dark,
    );
    expect(spans.map((s) => s.text).join(), 'tax checklist.md your tax refund is here');
    expect(spans.where((s) => s.style?.backgroundColor != null).single.text, 'tax');
  });
}
