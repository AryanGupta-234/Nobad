# NOBAD Find UI (Flutter prototype)

The Flutter window for NOBAD Find (ROADMAP Phase 3 step 1). It owns nothing but the screen: everything comes from the
engine over the private pipe `\\.\pipe\NOBADFind-<user SID>` (JSON-RPC 2.0, see `../nobadfind/rpc/`). Layout follows
`docs/STRUCTURE.md` (branch `find-structure`).

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

Dependencies: Flutter SDK, `material_ui` (Flutter's Material widgets, split out of the SDK in 3.50: text field,
theme) and `ffi` (native memory for the pipe and window calls). Win32 calls are bound directly with `dart:ffi`
(about 25 functions), so `win32` and a window plugin aren't needed.

Measurement switches (off unless set; see `../docs/measurements.md`): `NOBAD_FIND_RENDERER=impeller`,
`NOBAD_FIND_UI_TIMING=<file>`, `NOBAD_FIND_UI_DEMO=1`, `NOBAD_FIND_UI_SHOT_DIR=<folder>`.
