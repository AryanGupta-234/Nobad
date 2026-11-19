# NOBAD Find: architecture, optimization and redesign roadmap

**Read this first if you are picking NOBAD Find up, human or AI, even in the middle of a phase.**
It records where the app is, why it is about to change, the exact order of work, and how to resume.
Update the [status table](#status) at the end of every step you finish. Rules in [`AGENTS.md`](AGENTS.md) and the
root [`AGENTS.md`](../../AGENTS.md) still apply and win over anything here.

Written 2026-11-18, after NOBAD Find 0.7.0 shipped (CI tag `find-v0.7.0`, main `c47df03`).

---

## 1. The goal, in the maintainer's words

> "My main aim is to optimize the app: RAM, CPU and GPU. Then go for in-app features. It must not bug out."

So the order is fixed. **Resources first, stability second, the new UI third, features fourth.** Do not start a
later phase while an earlier one has open work unless the status table says it was deliberately parked.

## 2. Why things are changing (the causes, with evidence)

1. **The window costs as much as the search engine.** Measured on the maintainer's PC (16 threads, 15.7 GB RAM,
   Intel Iris Xe) on 2026-11-18, 20 s after start while indexing:

   | Part | Processes | Working set | Private (committed) |
   |---|---|---|---|
   | Window: WebView2 (Edge) | 7 | **425 MB** | 212 MB |
   | Engine: `NobadFind.exe` main + indexing workers | 7 | 549 MB | **3,979 MB** |

   A browser engine with seven processes is far too heavy for a launcher-style tool.
2. **The engine commits about 4 GB it doesn't use.** 549 MB in use against 3,979 MB committed points at
   per-process allocators (ONNX Runtime arenas, numpy, imports duplicated in every worker), not real work.
3. **Web-page UIs have a whole class of bugs a native UI can't have.** NOBAD VPN's tray mini window was found
   showing a raw `{"ok": false}` JSON page (screenshot from the maintainer, 2026-11-18): the window had ended up
   on one of its own local server's API addresses. Any UI built on URLs, a local server, cookies and pages can
   land somewhere wrong. A native UI talking to the engine over a private pipe has no addresses to land on.
4. **The hand-written HTML/JS UI is getting brittle.** `ui/app.js` is about 630 lines of string-built DOM with
   manual refresh timers. Every release found focus, refresh, NaN or escaping issues in review. It works, but it
   doesn't scale to the screens planned (model tiers, consent dialogs, previews).

## 3. Decisions taken

| Date | Decision | Why |
|---|---|---|
| 2026-11-18 | Optimize RAM/CPU/GPU before new features | Maintainer's main aim |
| 2026-11-18 | Replace the WebView UI with **Flutter** (Dart). Keep the **Python engine** | Best-looking custom UI of the options, GPU-drawn, ~60-100 MB in one process instead of ~425 MB in seven; the engine (indexer, governor, OCR, models, encryption, 284 tests) is tested and stays |
| 2026-11-18 | UI and engine talk over a **private named pipe**, never HTTP | Removes the local-server/URL bug class (cause 3) |
| 2026-11-18 | Prototype first, measure, then commit to the full move | A wrong platform choice is expensive; numbers decide |
| 2026-11-18 | Maintainer: start the Flutter prototype now, before Phases 0-1 finish. Flutter SDK 3.50 at `E:\devlutter` (PUB_CACHE `E:\dev\pub-cache`), VS 2022 Build Tools (C++ only) at `E:\dev\VSBuildTools` | Maintainer's call; the prototype also gives the first UI measurements |
| 2026-11-19 | Maintainer approved the full move from the WebView UI to Flutter | Prototype numbers (section 6 status, `docs/measurements.md`) |
| 2026-11-19 | Pipe contract v1 lives in `contract/` (schemas, transcripts, README); `status` stays the short status, `status_full` is the Indexing page's; `heartbeat`/`page_visible`/`hide` became `ui_shown`/`ui_hidden` plus pipe liveness; `quit` needs `confirm: "QUIT"` | The UI never polls and never sends a path; one file both test suites replay |
| 2026-11-18 | Flutter prototype renders with **Skia**, not Impeller (Flutter 3.50's Windows default) | On the reference PC Impeller took 0.9 s to the first frame and ~50 MB more; re-measure on every Flutter upgrade and on another GPU before the full move |

Options considered for the UI and why they lost:

| Option | Why not (for now) |
|---|---|
| Keep WebView, add Svelte/React | Fixes brittleness, not the 425 MB or the URL bug class |
| Tauri | Uses WebView2 on Windows too: same weight |
| Qt (PySide6 + QML) | Keeps one language and is light, but a polished custom look takes more hand-tuning than Flutter. **Fallback if the Flutter prototype fails its budget** |
| WinUI 3 (C#) | Most native Windows 11 look, but a full rewrite of the engine in C# |
| Electron | Heavier than what we have |

---

## 4. Architecture today (0.7.0)

### Processes
```
NobadFind.exe (main, Python, normal user, Windows background mode)
 ├─ outer Windows job (kill on close): everything below dies when main exits or crashes
 ├─ WebView2 x7 (the window and the quick find bar)
 └─ worker job (nested, CPU-capped by level)
     ├─ text readers x1..N (ProcessPoolExecutor, extract.work, Windows OCR inside)
     ├─ meaning worker x1 (ONNX all-MiniLM-L6-v2, CPU or DirectML)
     └─ photo worker x1 (ONNX SigLIP base vision, Windows image decoders)
Files opened from Find start outside the job (explorer.exe with CREATE_BREAKAWAY_FROM_JOB).
```

### Threads in the main process
indexer (`indexer.Indexer._run`), governor tick every 2 s (`governor.Governor`), watchdog step inside the tick,
window lifecycle (`lifecycle.Window`), hotkeys (`hotkey.Hotkey` x2), file watcher (`watcher.py`), pywebview UI,
status count refresher (`api.Api`).

### Modules (apps/find/nobadfind)
| Module | Responsibility | Survives the Flutter move? |
|---|---|---|
| `app.py` | Start-up, windows, hotkeys, splash, close/quit wiring | **Split**: engine start-up stays; window code moves to Flutter |
| `api.py` | Methods the page calls (search, open, status, settings…) | **Becomes `rpc.py`**: same methods behind the pipe |
| `bar.py` | Quick find bar window and its API | **Moves** to Flutter (placement logic can stay as a pure helper) |
| `lifecycle.py` | Close/hide/quit decisions, window wishes | Stays (engine decides; Flutter asks) |
| `governor.py` | Work levels + reasons every 2 s | Stays |
| `appmemory.py`, `activity.py` | Learned apps, recent decisions | Stay |
| `watchdog.py` | Kills Find's own runaway workers, page heartbeat | Stays; heartbeat comes over the pipe |
| `jobs.py` | Windows job objects | Stays |
| `indexer.py`, `walker.py`, `watcher.py`, `extract.py`, `ocr.py`, `photo.py`, `embed.py`, `thumbs.py` | Indexing pipeline | Stay (optimized in Phase 1) |
| `store.py` | SQLCipher index (DPAPI key) | Stays |
| `query.py`, `search.py`, `kinds.py` | Understanding questions, ranking | Stay |
| `settings.py`, `const.py` | Settings with validation, defaults | Stay |
| `hardware.py`, `winapi.py` | PC scan, Win32 calls | Stay |
| `hotkey.py` | Global hotkeys | Stays in the engine (it must work while the UI is closed) |
| `wsearch.py` | Windows Search switch (elevated helper) | Stays |
| `ui/` (index.html, app.js, app.css, bar.*) | The current UI | **Replaced** by the Flutter app |

### The API surface the UI uses (keep it; it becomes the pipe protocol)
`search open reveal thumbnail here_folder path_of forget status pause_for resume learned_apps reset_learned
hardware get_settings set_settings pick_folder rescan wipe download_model download_photo_model wsearch_state
wsearch_set use_instead_of_windows_search heartbeat page_visible hide quit`, plus the bar's
`search open reveal to_main hide`.

### Settings keys (const.DEFAULTS)
`roots exclude content content_max_mb semantic photo_meaning allow_model_download allow_photo_model_download src_mail
ocr index_removable index_network pause_on_battery pause_fullscreen (legacy) games_mode pause_on_call workers
keep_background hotkey bar bar_hotkey hide_after_open autostart wsearch_prev theme glass bg_notice_seen`

## 5. Complete feature inventory (nothing here may be lost in the redesign)

Search
- [ ] Names (any part), text inside (Office, ODF, RTF, PDF, EPUB, code, notes, .eml/.mbox), meaning (optional
      model), photos by content (optional model), words in photos/scans (Windows OCR)
- [ ] Plain-language questions: kinds, times, sizes, order, apps, folders ("in my downloads", "here", typed paths),
      drives (USB, network, letters, labels), linking words ("having/containing X")
- [ ] Filter bar (kind, date, size, folder, order), "here" = File Explorer folder the hotkey was pressed in
- [ ] Results: previews (Windows thumbnail cache), Enter open, Ctrl+Enter show in folder, Ctrl+C copy path,
      Shift+Delete forget; window stays up unless "Hide after opening a file"
- [ ] Quick find bar (Ctrl+Alt+Space), up to 8 results, Alt+Enter to the full window, on the monitor with the mouse
- [ ] Home: example chips, quick tiles, recently changed, status line

Indexing and resources
- [ ] Walk of profile + fixed drives (+ optional removable/network), exclusions, secrets never indexed
- [ ] Live changes via folder notifications; rescans
- [ ] Governor levels Full/Gentle/Light/Paused with reasons; games mode Smart/Always/Off; battery; calls;
      presentations; "Pause for 1 hour"; per-app learning with Forget
- [ ] Job objects, CPU caps per level, watchdog, hard exit after 15 s, files opened outside the job
- [ ] Close/Esc stops indexing (one idle process keeps the hotkey) unless "Keep indexing in the background"

Transparency
- [ ] Indexing page: level + reason, pipeline with ETA, own CPU/RAM/disk/GPU per process with a 5-minute chart,
      model cards, recent decisions, folders, drives, encryption note, one-time notice

Settings and system
- [ ] Six pages (General, Indexing, Models, Performance, Privacy & data, About), light/dark theme, glass
- [ ] Model downloads with consent (pinned revisions, SHA-256), Windows Search switch (elevated, undoable), wipe,
      start with Windows, hotkeys, Quit
- [ ] Splash, single instance (second start shows the running copy), refuses to run as admin, encrypted index

---

## 6. The plan

### Phase 0: measure (do this first, it decides everything after)
Build `apps/find/tools/measure.py` (dev-only, not shipped):
- Starts the built app with a temp data dir and a fixed test corpus (a folder of ~5,000 generated files: docs,
  PDFs, images), samples every process in Find's job every second: working set, private bytes, CPU %, GPU %
  (PDH), I/O, handle and thread counts.
- Scenarios: cold start to window shown; idle with window open; indexing at each level; search typing; window
  closed (idle process); models loaded/unloaded.
- Writes a CSV + a summary table. Commit the **summary** of each run to `apps/find/docs/measurements.md` (date,
  commit, PC) so every later change is compared against numbers, not feelings.

**Budgets** (targets; Phase 1 and 3 must meet them or say why):

| Scenario | 0.7.0 today | Target |
|---|---|---|
| Window open, idle, models released | ~425 MB UI + engine | UI ≤ 100 MB, engine ≤ 120 MB |
| Window closed (idle process for the hotkey) | main process (models released) | ≤ 60 MB, CPU ≈ 0 % |
| Indexing, Gentle, 16-thread PC | 549 MB working / 3.98 GB private | ≤ 600 MB private total |
| Search keystroke to results | not measured | ≤ 80 ms for names, ≤ 250 ms with meaning |
| Cold start to usable window | not measured | ≤ 1.5 s |
| Governor tick cost | not measured | ≤ 1 % of one core |

### Phase 1: engine diet (Python; no UI change)
Investigate the ~4 GB commit first, with `measure.py` plus `tracemalloc`/`vmmap`. Likely causes and fixes:
1. **ONNX Runtime arenas:** set `enable_cpu_mem_arena=False` (or `arena_extend_strategy=kSameAsRequested`),
   `enable_mem_pattern=False` for the small batch sizes used, and `intra_op_num_threads` from the level.
2. **Heavy imports in every text reader:** text readers must not import numpy/onnxruntime/tokenizers; check
   with `python -X importtime` inside `extract.init_worker`. Import pypdf/winrt lazily per file type.
3. **Worker recycling:** `ProcessPoolExecutor(max_tasks_per_child=…)` (Python 3.11 supports it with spawn) to
   return memory pdf/zip parsing fragments; and fewer readers at Gentle on many-core PCs.
4. **Vectors in memory:** keep the vector index as float16 (half the RAM) and memory-map it from a file instead of
   holding a copy per process; only the main process needs it.
5. **SQLite/SQLCipher:** cap `cache_size`, use `mmap_size` modestly, check WAL checkpoints.
6. **Idle trimming:** after the level drops to Paused or the window closes, call `EmptyWorkingSet` on Find's own
   processes; release models (already) and end worker pools (already after 60 s paused).

Windows optimizations to apply (each behind a measurement, each on Find's own processes only):
- **EcoQoS / efficiency mode** for workers: `SetProcessInformation(ProcessPowerThrottling,
  PROCESS_POWER_THROTTLING_EXECUTION_SPEED)` so Windows runs them on efficiency cores at low clocks (Task Manager
  shows the leaf icon). Keep the main process normal so search stays snappy.
- **Memory priority low** (`ProcessMemoryPriority = MEMORY_PRIORITY_LOW`) and **I/O priority very low** for
  workers; the main process keeps background mode only while indexing, not while the user types.
- **Job memory limit** on the worker job (`JOB_OBJECT_LIMIT_JOB_MEMORY`) as a hard backstop to the watchdog.
- **GPU:** ship `onnxruntime-directml` only if measurement shows a win on integrated GPUs; DirectML stays Full-only
  (governor rule). Today `directml` is False on the reference PC because the CPU build of ONNX Runtime is shipped.
- **No polling where Windows can notify:** power changes (`RegisterPowerSettingNotification`), foreground changes
  (`SetWinEventHook(EVENT_SYSTEM_FOREGROUND)`) and display/presentation state instead of asking every 2 s; the
  governor tick can then drop to 5 s when nothing changed.
- Out of scope by maintainer decision (2026-11-17): NTFS MFT/USN change-journal reading and running elevated.

Done when: budgets for "indexing" and "closed" are met or the gap is explained in `measurements.md`, and all
tests pass.

### Phase 2: stability foundation (engine as a service with a typed contract)
Prepare the engine so any UI can sit on top, and so a UI crash can't take indexing with it, or the reverse.
1. **`nobadfind/rpc.py`:** JSON-RPC 2.0 over a named pipe `\\.\pipe\NOBADFind-<user SID>`, created with a DACL
   for the current user only, `PIPE_REJECT_REMOTE_CLIENTS`, one message per line, max message size, a protocol
   version in a `hello` call. Methods = the API surface in section 4, plus **events pushed by the engine**
   (`status`, `level`, `activity`, `download`) so the UI never polls.
2. **`nobadfind/engine.py`:** the engine entry point (`NobadFind.exe --engine`): store, indexer, governor,
   watchdog, hotkeys, rpc server. It owns the hotkeys and the idle state; when the user presses the hotkey and no
   UI is running, it starts the UI process.
3. **Contract tests:** `tests/test_rpc_contract.py` checks every method's request/response schema; a recorded
   transcript is replayed so the Flutter side and the Python side test against the same file
   (`apps/find/contract/*.json`).
4. Keep the current WebView UI working on top of `rpc.py` during this phase (pywebview `js_api` calls forward to
   the same handlers) so nothing breaks for users before Flutter is ready.

Done when: the WebView UI runs entirely through `rpc.py` handlers, the pipe server passes contract tests, and the
engine runs headless (`--engine`) with the hotkey.

### Phase 3: Flutter UI
Prototype first (one week max), then the full move.

**Prototype scope:** Search screen + quick find bar against the real engine over the pipe. Measure with
`measure.py`: UI ≤ 100 MB, cold start ≤ 1.5 s, typing latency within budget. If it misses, try Qt (QML) with the
same contract before deciding.

**Full UI (new folder `apps/find/ui_flutter/`):**
- Screens to rebuild: Home, Search results (virtualized list, thumbnails), Indexing (level, pipeline, resources
  chart, models, activity), Settings (six pages), quick find bar, splash, first-run welcome, consent dialogs
  (0.8.0), notices/toasts.
- Windows integration (Flutter plugins or the C++ runner): frameless + acrylic/Mica (`flutter_acrylic` or
  `DwmSetWindowAttribute`), always-on-top bar on the monitor with the mouse (per-monitor DPI), single instance,
  taskbar/Start menu activation, light/dark following the setting.
- Global hotkeys stay in the engine (they must work with the UI closed); the engine starts or focuses the UI.
- Closing the window **exits the UI process**: with background indexing off the engine goes idle
  (the "one small process"), so closed-state memory is just the engine.
- Tests: widget tests + golden screenshots in dark and light, an integration test against a fake engine that
  replays `apps/find/contract/*.json`.

**Python changes in this phase**
- Remove: `pywebview`, `bottle`, pythonnet/clr deps, `ui/` folder, `bar.py` window code, the page heartbeat
  (replaced by pipe liveness: the engine notices a dead UI by the pipe closing), `make_glass`.
- Change: `app.py` → `engine.py` start-up only; `api.py` → `rpc.py` handlers; `watchdog` UI-reload rule becomes
  "UI process not answering pings for 15 s → restart the UI process".
- Keep: everything else in section 4.

**UI-related changes in this phase**
- From string-built DOM to typed widgets with state from engine events: no manual refresh timers, no innerHTML,
  so the escaping, focus and NaN classes of bugs from 0.7.0 reviews disappear.
- Same NOBAD look: one NOBAD orange, dark/light, glass, the mark; same copy (texts are user-facing contracts).

**Packaging:** PyInstaller builds `nobadfind-engine` (no UI deps), Flutter builds the UI; Inno Setup installs
both; the release workflow (`find-release.yml`) builds and attests both; SHA-256 for the installer as today.

### Phase 4: features (only after Phases 0-3, or when the status table parks them)
1. **0.8.0 model tiers** (spec: `docs/superpowers/specs/2026-11-18-find-governor-transparency-models-design.md`
   §4): hardware scan → Light/Balanced/Best; multilingual text models (Hindi and mixed included: multilingual-e5
   small/base, MIT); bigger photo model and an ONNX OCR model for Best; consent dialog per download;
   auto-configure; background vector rebuild with model id on vectors.
2. Polish deferred from 0.7.0 reviews (most disappear with Flutter): Home recent list fetches 500 rows for 8; light
   theme flash at start; glass sub-nav dark on light; Settings re-render during downloads; "a game" wording;
   Alt+Enter keeps a stale "here"; static-only UI tests.
3. Later ideas (ask first): previews inside Find, optional admin "turbo" index (maintainer asked 2026-11-17; the
   app never runs elevated today, so this needs its own design), code signing (SignPath) so SmartScreen and the
   updater stop warning.

### Phase 5: carry the lessons to NOBAD VPN
- Fix the mini-window JSON bug (cause 3): find the trigger (the maintainer to describe what they did before it
  appeared), then make `/mini` and `/` fall back to the page instead of a JSON 404/403 for top-level navigations,
  and block navigation away from the app's pages in both windows.
- Later: the same engine-plus-native-UI split if Find's move proves out.

---

## 7. Rules that never change
- Never touch, throttle or kill other apps. Only Find's own processes (by job membership).
- No new outbound connection without a setting and an entry in the privacy docs; downloads only with consent,
  pinned and SHA-256 checked.
- Never run elevated (except the existing Windows Search helper).
- Learned app data: exe file names only.
- Releases only from CI (`find-v*` tag → `find-release.yml`), and everywhere: version, changelog, docs, website,
  memory repo (`docs/ai/playbooks/release-find.md`).
- Tests and `pyflakes` green before every merge; measurements updated for any performance claim.

## 8. How to resume in the middle
1. Read the [status table](#status) below: the first row that isn't **done** is where you are.
2. Check the branch named in that row (`git log origin/main..<branch>`), run the tests
   (`cd apps/find && python -m pytest -q tests`), and read the last entries of `docs/measurements.md`.
3. Continue the step's "Done when" condition. If you change the plan, edit this file in the same PR and add a
   row to the decisions table (section 3) with the date and why.
4. Before you stop, update the status row (what is done, what is next, any open risk) and push.

## Status

| Phase | Step | State | Branch / PR | Notes |
|---|---|---|---|---|
| 0 | `tools/measure.py` + first baseline in `docs/measurements.md` | not started | | Reference numbers in section 2 are a manual measurement |
| 1 | Find the 4 GB commit; ONNX arenas; reader imports; recycling | not started | | |
| 1 | EcoQoS / memory / I/O priority for workers; job memory limit | not started | | |
| 1 | Event-driven governor inputs (power, foreground) | not started | | |
| 2 | `rpc.py` named-pipe server + contract tests | **done, in review** | find-engine-rpc (draft PR into find-flutter-prototype) | Every section-4 method over the pipe (`nobadfind/rpc/handlers/*`, thin: they call the same `Api` methods as the page), events `status status_full level activity download notice show here quitting`, `contract/` schemas + 4 transcripts + README, `tests/test_rpc_contract.py`. Next: the Dart client against `contract/` |
| 2 | `engine.py` headless with hotkeys; WebView UI on rpc handlers | **engine part done** (same PR) | find-engine-rpc | `--engine` runs headless with both hotkeys, "here", lifecycle idle on `ui_hidden`/pipe close, native folder dialog, notices for taken hotkeys. Open: the WebView page still calls `Api` directly (same methods the handlers call, so no logic is duplicated); a changed hotkey needs an engine restart |
| 3 | Flutter prototype (Search + bar) and measurement | **built, measured; waiting for the maintainer's go/no-go** | find-flutter-prototype (draft PR) | Window 465 MB/7 processes (WebView2) → ~132 MB/1 process (Flutter, Skia), first frame 0.2 s, pipe adds ≤ 3 ms ([measurements](docs/measurements.md)). Misses the ≤ 100 MB window budget (Intel D3D11 driver ~100 MB in-process). Prototype `nobadfind/rpc/` + `engine.py` cover only hello/subscribe/search/open/reveal/thumbnail/status. Fallback: Qt/QML |
| 3 | Full Flutter UI, packaging, release workflow | not started | | |
| 4 | 0.8.0 model tiers (multilingual, consent) | not started | | Spec §4 |
| 5 | NOBAD VPN mini-window bug | waiting | | Needs the steps that trigger it from the maintainer |
