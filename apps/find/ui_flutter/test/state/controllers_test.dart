import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/fake_engine.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/state/search_controller.dart';
import 'package:nobad_find/state/settings_controller.dart';
import 'package:nobad_find/state/status_controller.dart';
import 'package:nobad_find/state/toast_controller.dart';

void main() {
  group('FindController', () {
    test('filters go with the words; filters alone list files, the order alone does not', () async {
      final e = FakeEngine();
      final f = FindController(e, debounce: Duration.zero);
      f.setFilters(const SearchFilters(kind: 'pdf')); // a filter searches at once, no debounce
      await pumpEventQueue();
      expect(e.searches.single, '');
      expect(e.searchFilters.single.kind, 'pdf');
      expect(f.showingResults, isTrue);
      expect(f.results.map((r) => r.id), [1]); // listing leaves out the weak ones

      f.setFilters(const SearchFilters(sort: 'newest'));
      expect(f.showingResults, isFalse);
      expect(f.results, isEmpty);

      f.setText('tax');
      await f.run();
      expect(e.searchFilters.last.sort, 'newest');
      f.dispose();
    });

    test('Ctrl+C copies the path, Shift+Delete forgets after asking', () async {
      final e = FakeEngine();
      final copied = <String>[];
      final toasts = ToastController();
      final f = FindController(e, debounce: Duration.zero, toasts: toasts, copy: (s) async => copied.add(s));
      f.setText('tax return');
      await f.run();
      await f.copySelected();
      expect(copied, [r'C:\Users\me\Documents\Taxes\tax return 2025.pdf']);
      expect(toasts.message, 'Path copied.');

      String? asked;
      expect(
        await f.forgetSelected((q) async {
          asked = q;
          return false;
        }),
        isFalse,
      );
      expect(asked, 'Forget "tax return 2025.pdf" and keep it out of the index from now on?');
      expect(e.forgotten, isEmpty);

      expect(await f.forgetSelected((q) async => true), isTrue);
      expect(e.forgotten, [1]);
      expect(toasts.message, 'Forgotten. Undo it in Settings → Never search.');
      expect(f.results, isEmpty); // searched again
      f.dispose();
      toasts.dispose();
    });

    test('an open that fails says why', () async {
      final e = FakeEngine()..openOk = false;
      final toasts = ToastController();
      final f = FindController(e, debounce: Duration.zero, toasts: toasts);
      f.setText('notes');
      await f.run();
      expect(await f.openSelected(), isFalse);
      expect(toasts.message, "That file isn't there any more.");
      f.dispose();
      toasts.dispose();
    });

    test('here: the folder the hotkey was pressed in', () async {
      final e = FakeEngine()..here = r'C:\Users\me\Documents\Taxes';
      final f = FindController(e, debounce: Duration.zero);
      await f.loadHere();
      expect(f.here, r'C:\Users\me\Documents\Taxes');
      f.useHere();
      expect(f.filters.folder, r'C:\Users\me\Documents\Taxes');
      f.dispose();
    });
  });

  group('StatusController', () {
    test('status from events; details only while watched; new decisions on top; downloads from events', () async {
      final e = FakeEngine();
      final s = StatusController(e);
      expect(s.details, isNull);
      await s.watch(true);
      expect(e.watching, isTrue);
      expect(s.details?.phases, isNotEmpty);
      final before = s.activity.length;
      e.emit(const ActivityEvent(ActivityEntry(t: 1, text: 'Paused: on battery.')));
      expect(s.activity.first.text, 'Paused: on battery.');
      expect(s.activity.length, before + 1);
      e.emit(const DownloadEvent(id: 'meaning', state: 'downloading', gotMb: 5, sizeMb: 10));
      expect(s.model('meaning').percent, 50);
      e.emit(const StatusEvent(EngineStatus(level: 'full', files: 3)));
      expect(s.status?.level, 'full');
      expect(s.line, '3 files indexed · Working at full speed');
      e.emit(const LevelEvent('paused', 'Paused: on battery', paused: 'on battery'));
      expect(s.status?.phaseLabel, 'Paused · on battery');
      await s.watch(false);
      expect(e.watching, isFalse);
      s.dispose();
    });
  });

  group('SettingsController', () {
    test('a change goes to the engine; a refused one says so and snaps back', () async {
      final e = FakeEngine();
      final toasts = ToastController();
      final c = SettingsController(e, toasts: toasts);
      await c.load();
      expect(c.settings.dark, isTrue);
      await c.set('theme', 'light');
      expect(c.settings.dark, isFalse);
      expect(e.settingsSet.last, {'theme': 'light'});
      await c.set('workers', -3);
      expect(toasts.message, "That value wasn't accepted.");
      expect(c.settings.number('workers'), 0);
      c.dispose();
      toasts.dispose();
    });

    test('a model download asks first, then allows and starts it', () async {
      final e = FakeEngine();
      final toasts = ToastController();
      final c = SettingsController(e, toasts: toasts);
      await c.load();
      expect(await c.download('meaning', consent: () async => false), isFalse);
      expect(e.calls, isNot(contains('download_meaning')));
      expect(await c.download('meaning', consent: () async => true), isTrue);
      expect(c.settings.flag('allow_model_download'), isTrue);
      expect(e.calls, contains('download_meaning'));
      expect(toasts.message, 'Downloading the model…');
      c.dispose();
      toasts.dispose();
    });

    test('the whole index is deleted only with DELETE typed', () async {
      final e = FakeEngine();
      final toasts = ToastController();
      final c = SettingsController(e, toasts: toasts);
      expect(await c.wipe(() async => 'delete'), isFalse);
      expect(e.calls, isNot(contains('wipe')));
      expect(await c.wipe(() async => 'DELETE'), isTrue);
      expect(toasts.message, 'Index deleted. Rebuilding.');
      c.dispose();
      toasts.dispose();
    });
  });

  test('a toast hides itself after 3.2 s, and an engine notice shows one', () {
    fakeAsync((async) {
      final e = FakeEngine();
      final t = ToastController(engine: e);
      t.show('Rescan started.');
      expect(t.message, 'Rescan started.');
      async.elapse(const Duration(milliseconds: 3300));
      expect(t.message, isNull);
      e.emit(const NoticeEvent('The model is ready.'));
      expect(t.message, 'The model is ready.');
      t.dispose();
    });
  });
}
