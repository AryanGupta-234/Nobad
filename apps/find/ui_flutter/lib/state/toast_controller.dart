/// Short notices at the bottom of the window (app.js toast): one at a time, gone after 3.2 s. The engine's
/// `notice` event shows one too.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../engine/engine_api.dart';
import '../engine/events.dart';

class ToastController extends ChangeNotifier {
  ToastController({EngineApi? engine, this.lasts = const Duration(milliseconds: 3200)}) {
    _sub = engine?.events.listen((e) {
      if (e is NoticeEvent) show(e.text);
    });
  }

  final Duration lasts;
  StreamSubscription<EngineEvent>? _sub;
  Timer? _timer;
  String? _message;

  /// Bumped for every new toast, so the same words twice still animate in again.
  int serial = 0;

  String? get message => _message;

  void show(String text) {
    if (text.isEmpty) return;
    _message = text;
    serial++;
    _timer?.cancel();
    _timer = Timer(lasts, dismiss);
    notifyListeners();
  }

  void dismiss() {
    _timer?.cancel();
    if (_message == null) return;
    _message = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _sub?.cancel();
    super.dispose();
  }
}
