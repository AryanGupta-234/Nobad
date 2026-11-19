/// Reading a WireGuard QR code from a picture (a screenshot of a provider's page, a phone photo), in this window's
/// process at the user's rights: only the decoded text goes to the engine (`import`, which refuses script hooks).
/// The same tries as the WebView's jsQR path (app_ext.js decodeQR): the full picture, then smaller copies.
library;

import 'dart:typed_data';

import 'package:image/image.dart' as img;
import 'package:zxing2/qrcode.dart';

const imageExtensions = {'png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'};

bool isImageName(String name) => imageExtensions.contains(name.split('.').last.toLowerCase());

/// The QR code's text, or null when the picture has none (or isn't a picture).
String? decodeQr(Uint8List bytes) {
  img.Image? picture;
  try {
    picture = img.decodeImage(bytes);
  } on Object {
    return null;
  }
  if (picture == null) return null;
  for (final max in const [1600, 900, 500]) {
    final longest = picture.width > picture.height ? picture.width : picture.height;
    final scaled = longest > max
        ? img.copyResize(picture, width: picture.width * max ~/ longest, height: picture.height * max ~/ longest)
        : picture;
    final pixels = scaled.convert(numChannels: 4).getBytes(order: img.ChannelOrder.abgr).buffer.asInt32List();
    final source = RGBLuminanceSource(scaled.width, scaled.height, pixels);
    for (final bitmap in [BinaryBitmap(HybridBinarizer(source)), BinaryBitmap(GlobalHistogramBinarizer(source))]) {
      try {
        final text = QRCodeReader().decode(bitmap).text;
        if (text.isNotEmpty) return text;
      } on Object {
        // not found at this size or with this binarizer: try the next
      }
    }
    if (longest <= max) break;
  }
  return null;
}
