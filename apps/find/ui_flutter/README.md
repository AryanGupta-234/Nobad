# NOBAD Find UI (Flutter)

The Flutter window for NOBAD Find (ROADMAP Phase 3). It owns nothing but the screen: everything comes from the
engine over the private pipe `\\.\pipe\NOBADFind-<user SID>` (JSON-RPC 2.0, the contract in `../contract/`).
Layout follows `docs/STRUCTURE.md`.

```
# the engine (from apps/find)
python -m nobadfind --engine
# the UI (from apps/find/ui_flutter)
flutter test && flutter analyze
flutter build windows --release
build\windows\x64\runner\Release\nobad_find.exe          # main window
build\windows\x64\runner\Release\nobad_find.exe --bar    # quick find bar (Esc hides, the engine's bar hotkey shows it)
```

On the maintainer's PC: `E:\dev\flutter\bin\flutter`, `PUB_CACHE=E:\dev\pub-cache`, VS 2022 Build Tools in `E:\dev\VSBuildTools`.

## Layout

| Folder | What |
|---|---|
| `lib/app/theme/` | The design system: `colors.dart` (one NOBAD orange, dark and light), `typography.dart` (system fonts only), `tokens.dart` (spacing, radius, motion), `theme.dart`, `glass.dart` (Mica and the title bar via `DwmSetWindowAttribute`) |
| `lib/widgets/` | Shared widgets: pressable base with a focus ring, buttons, switch, select, chips, fields, panels, stat tiles, meter, dialogs, icons and the level glyph, the resources chart, motion (appear, skeleton) |
| `lib/engine/` | The only code that knows the engine: `engine_api.dart` (the typed interface), `rpc.dart` (`EngineClient`, a typed call per contract method), `pipe_client.dart`, `events.dart`, `models/`, `fake_engine.dart`, and `wiring.dart`, **the one place that routes each call** to the pipe or the fake |
| `lib/state/` | Controllers (search, status, settings, toasts), fed by engine events: no polling timers |
| `lib/features/` | Screens: shell (rail), search (box, filters, results, Home, status line), bar, indexing, settings (six pages), consent, welcome, splash |
| `test/` | Models, controllers, widget tests per screen, dark + light goldens (drawn with the real Windows fonts), and a replay of `../contract/transcripts` |

`WiredEngine` sends a method over the pipe when the engine lists it in `hello.methods`, and answers it from
`FakeEngine` otherwise (an older engine), so the same build works against both.

## Dependencies

Flutter SDK, `material_ui` (Flutter's Material widgets, split out of the SDK in 3.50: text field, menus, dialogs) and
`ffi` (native memory for the pipe and window calls). Win32 calls are bound directly with `dart:ffi`, so `win32` and a
window plugin aren't needed. Fonts are the ones Windows has (Arial Black is registered from the Windows fonts folder
at start), so nothing is bundled.

## Switches (off unless set)

| Variable | What |
|---|---|
| `NOBAD_FIND_FAKE_ENGINE=1` | Run against the in-memory `FakeEngine` (design work, screenshots); `NOBAD_FIND_FAKE_WELCOME=0` skips the welcome, `NOBAD_FIND_FAKE_GLASS=0` turns glass off |
| `NOBAD_FIND_UI_DEMO=1` / `a\|b\|c` | Types fixed searches into its own box and records timings (`../docs/measurements.md`) |
| `NOBAD_FIND_UI_DEMO=tour` | Visits every main screen in dark and light and saves a picture of each to `NOBAD_FIND_UI_SHOT_DIR` |
| `NOBAD_FIND_UI_TIMING=<file>`, `NOBAD_FIND_UI_SHOT_DIR=<folder>` | Where timings and pictures go |
| `NOBAD_FIND_SKIA_CACHE_MB` | Skia's GPU cache while shown (default 12; emptied while hidden) |
| `NOBAD_FIND_RENDERER=impeller` | Impeller instead of Skia (for measuring) |

Screenshots of the release build are in `docs/screenshots/`.
