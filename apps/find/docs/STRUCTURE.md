# NOBAD Find: target code structure (engine + Flutter UI)

Companion to [`../ROADMAP.md`](../ROADMAP.md). This is **where every file goes** after the move to a Python
engine service with a Flutter UI, and the rules that keep the parts apart. Build new code into this layout; move
old modules into it in Phase 2 (one mechanical commit per package, with the old import path re-exported for one
release so nothing breaks mid-way).

Drafted 2026-11-18. If you change the layout, change this file in the same PR.

---

## 1. The three parts and how they talk

```
┌─────────────────────────────┐   JSON-RPC 2.0, one object per line     ┌──────────────────────────────┐
│ NOBAD Find UI (Flutter)      │ ◄──────────────────────────────────────►│ NOBAD Find engine (Python)    │
│ ui_flutter/ → NobadFind.exe  │   \\.\pipe\NOBADFind-<user SID>         │ nobadfind/ → nobadfind-engine │
│ draws, asks, shows events    │   requests ↔ responses, engine → events │ indexes, searches, decides    │
└─────────────────────────────┘                                         └──────────────────────────────┘
                 ▲                                                                     ▲
                 └──────────────────── contract/ (schemas + recorded transcripts) ─────┘
```

- The **engine** owns the data, the index, the models, the governor, the hotkeys and the idle state. It runs
  with the window closed. When a hotkey is pressed and no UI runs, it starts the UI.
- The **UI** owns nothing but the screen. Closing the window ends the UI process.
- The **contract** is the only thing both sides know about each other. Neither side imports the other's code.

## 2. Repository layout (apps/find)

```
apps/find/
├── ROADMAP.md                 plan, decisions, status table (read first)
├── AGENTS.md                  rules for AI assistants
├── CHANGELOG.md  README.md
├── docs/
│   ├── STRUCTURE.md           this file
│   └── measurements.md        RAM/CPU/GPU/latency numbers per commit (tools/measure.py)
├── contract/                  the UI ⇄ engine contract, shared by Python and Dart tests
│   ├── methods.schema.json    every RPC method: params + result JSON Schema, protocol version
│   ├── events.schema.json     every engine → UI event (status, level, activity, download, notice)
│   └── transcripts/           recorded request/response/event sessions (*.jsonl) replayed by both test suites
├── nobadfind/                 the engine (Python package; name kept for history and imports)
├── tests/                     engine tests (pytest), mirroring nobadfind/ subpackages
├── ui_flutter/                the UI (Flutter, Windows only)
├── tools/
│   └── measure.py             dev-only resource measurement harness (not shipped)
└── packaging/
    ├── engine.spec            PyInstaller: nobadfind-engine (no UI dependencies)
    ├── build.ps1              builds engine + UI, tests both, signs, makes the installer
    ├── installer.iss          Inno Setup: installs both, Start menu → UI, Run key → engine --background
    └── launch.py              engine entry point for the frozen build
```

## 3. The engine (nobadfind/)

```
nobadfind/
├── __main__.py         CLI: (default) --engine | --background | --wsearch | --uninstall | --version
├── engine.py           composition root: builds settings, store, indexer, governor, watchdog, hotkeys, rpc;
│                       start-up and shutdown order (the only place that wires parts together)
├── log.py
│
├── core/               pure Python: no Windows calls, no threads, no I/O beyond what is passed in
│   ├── const.py        names, paths, defaults (DEFAULTS), model pins
│   ├── settings.py     load/validate/save settings
│   ├── kinds.py        file kinds by extension
│   ├── query.py        plain-language question → Query
│   └── search.py       ranking and result shaping (given a store)
│
├── index/              the indexing pipeline and the encrypted store
│   ├── store.py        SQLCipher database, DPAPI-protected key
│   ├── indexer.py      phases, pools, level checks (obeys resources.governor)
│   ├── walker.py       folder walk          ├── watcher.py   folder-change notifications
│   ├── extract.py      text readers (worker) ├── ocr.py       Windows OCR (inside text workers)
│   ├── embed.py        meaning model + vector index (+ meaning worker)
│   ├── photo.py        photo model (photo worker)
│   └── thumbs.py       Windows thumbnail cache
│
├── resources/          staying out of the way, and proving it
│   ├── governor.py     levels + reasons (Brain is pure; Governor is the 2 s / event-driven loop)
│   ├── appmemory.py    learned apps            ├── activity.py   recent decisions
│   ├── watchdog.py     ends Find's own runaway workers; UI liveness over the pipe
│   ├── jobs.py         Windows job objects (outer kill-on-close, nested capped worker job)
│   ├── lifecycle.py    idle/active/background decisions
│   └── hardware.py     "Your PC" scan
│
├── platform/           every Win32 call lives here, behind small functions with safe defaults
│   ├── win.py          ctypes setup shared by the modules below (WIN flag, dll handles)
│   ├── sensors.py      CPU/GPU/memory samplers, foreground app, hung window, presentation/game state
│   ├── power.py        battery, power notifications, EcoQoS / memory / I/O priority
│   ├── shell.py        open outside the job, reveal in Explorer, known folders, drives
│   ├── security.py     DPAPI, admin check, current user SID, pipe security descriptor
│   ├── hotkey.py       global hotkeys (engine-owned)
│   └── wsearch.py      Windows Search switch (the only elevated helper)
│
└── rpc/                the engine's only door to the UI
    ├── server.py       named pipe: user-only DACL, reject remote clients, size cap, framing, one thread
    │                   per client, pipe liveness → watchdog
    ├── protocol.py     method registry, schema checks against contract/methods.schema.json, errors, version
    ├── events.py       pushes status / level / activity / download / notice to subscribed clients
    └── handlers/       thin: validate → call core/index/resources → shape the result
        ├── search.py   search, here_folder, thumbnail, open, reveal, path_of, forget
        ├── status.py   status, pause_for, resume, learned_apps, reset_learned, hardware
        ├── settings.py get_settings, set_settings, pick_folder, rescan, wipe
        ├── models.py   download_model, download_photo_model (consent, progress events)
        └── system.py   hello, wsearch_*, quit, ui_hidden (the old hide/page_visible/heartbeat)
```

Today's flat modules map one to one into these folders. `api.py` becomes `rpc/handlers/*`; `app.py` becomes
`engine.py`; `bar.py`'s window code and the whole `ui/` folder go away with the Flutter UI; `winapi.py` is split
into `platform/*` by topic.

### Engine dependency rules (enforced by a test that parses imports)
- `core` imports nothing from the other packages.
- `index` may import `core` and `platform`.
- `resources` may import `core` and `platform`, and `index` only through the indexer's public methods.
- `platform` imports nothing from Find except `log`.
- `rpc` may import everything; **nothing imports `rpc`** except `engine.py`.
- Worker processes (text readers, meaning worker, photo worker) import only what their job needs: never numpy or
  onnxruntime in a text reader (Phase 1 memory rule).

## 4. The UI (ui_flutter/)

```
ui_flutter/
├── pubspec.yaml        few, justified dependencies (see §6)
├── lib/
│   ├── main.dart       args: (none) = main window, --bar = quick find bar; connects to the engine
│   ├── app/
│   │   ├── app.dart            MaterialApp/WidgetsApp, routes, keyboard shortcuts
│   │   └── theme/              colors.dart (NOBAD tokens: one orange, dark/light), typography.dart, glass.dart
│   ├── engine/                 the only code that knows about the pipe
│   │   ├── pipe_client.dart    Win32 named pipe (win32/ffi), framing, reconnect with backoff
│   │   ├── rpc.dart            request ids, timeouts, typed calls generated from contract/methods.schema.json
│   │   ├── events.dart         typed event stream
│   │   └── models/             result.dart, status.dart, settings.dart, model_card.dart, learned_app.dart
│   ├── state/                  ValueNotifier/ChangeNotifier controllers (no heavy state library)
│   │   ├── search_controller.dart   query, debouncing, results, selection
│   │   ├── status_controller.dart   level, reason, phases, resources (from events, never polled)
│   │   └── settings_controller.dart
│   ├── features/
│   │   ├── search/      search_screen.dart, home_view.dart, filter_bar.dart, result_tile.dart
│   │   ├── bar/         bar_window.dart (frameless, on top, monitor with the mouse)
│   │   ├── indexing/    indexing_screen.dart, now_panel.dart, pipeline.dart, resources_chart.dart,
│   │   │                model_cards.dart, activity_list.dart
│   │   ├── settings/    settings_screen.dart + pages/ general, indexing, models, performance, privacy, about
│   │   ├── consent/     download_consent_dialog.dart (0.8.0 model tiers)
│   │   └── splash/      splash.dart
│   ├── widgets/         shared: nobad_button, toggle, card, meter, sparkline, notice, kbd
│   └── platform/        window.dart (frameless, acrylic/Mica, always-on-top, DPI-aware placement)
├── test/
│   ├── widgets/         one test file per feature screen, with a fake engine
│   ├── golden/          dark + light screenshots of every screen
│   └── contract/        replays ../contract/transcripts/*.jsonl against the Dart models
└── windows/runner/      C++ runner: single instance, DPI awareness, window class, icon
```

### UI rules
- Only `engine/` touches the pipe; screens talk to controllers; controllers talk to `engine/`.
- No string-built markup, no polling timers: screens rebuild from controller state; the engine pushes events.
- Every text from the engine (file names, folders, app names) is shown as plain text, never parsed as markup.
- The UI never opens files, URLs or shells itself: it asks the engine (`open`, `reveal`), which checks the id.
- Copy (user-facing text) is a contract: keep the wording of 0.7.0 unless a setting's meaning changes.

## 5. The contract (contract/)

- **Methods:** the 0.7.0 API surface (ROADMAP §4) plus `hello {protocol, version}` and `subscribe {events}`.
  Requests carry `id`; errors use JSON-RPC codes plus a plain-language `message`.
- **Events:** `status` (phases, counts, resources), `level` (level, reason), `activity` (entry),
  `download` (model id, got/size, speed), `notice` (text for a toast).
- **Versioning:** `protocol` is an integer. The engine accepts the current and the previous version for one release;
  the UI refuses to start against an unknown newer engine and says why.
- **Tests on both sides** replay `transcripts/*.jsonl`: the Python side checks the engine produces them, the Dart side
  checks it parses them. A contract change is a PR that updates the schema, a transcript, and both sides.

## 6. Dependencies policy

- **Engine:** today's pins (requirements-lock.txt) minus `pywebview`, `bottle`, `pythonnet`/`clr_loader` (UI only)
  after the move. No new runtime dependency without a measurement and a line in this file.
- **UI:** Flutter SDK (stable, pinned in `pubspec.yaml` `environment:`) plus only:
  `win32` + `ffi` (named pipe, window calls) and one window package if the runner can't do it natively
  (`window_manager` or `flutter_acrylic`). Each added package: why, licence, size, in this list.
- Development tools live outside C: on the maintainer's PC: Flutter `E:\dev\flutter`, pub cache `E:\dev\pub-cache`,
  VS 2022 Build Tools (C++) `E:\dev\VSBuildTools`.

## 7. Build and release

- `packaging/build.ps1`: engine venv → tests → PyInstaller (`engine.spec`) → `flutter test` + `flutter build windows
  --release` → copy UI next to the engine → Inno Setup → SHA-256. Fails on the first error.
- CI (`.github/workflows/find-release.yml`): the same steps on a Windows runner with Flutter installed, attests both
  executables and the installer; releases only from a `find-v*` tag.
- The installer puts `NobadFind.exe` (UI) and `nobadfind-engine.exe` side by side; Start menu starts the UI, which
  starts the engine if needed; "Start with Windows" runs `nobadfind-engine --background` only.
