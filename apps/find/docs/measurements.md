# NOBAD Find: measurements

Numbers decide (ROADMAP §3). Every performance claim points at a row here. Newest first. Working set = RAM in use
now; private = committed memory only this process can use (`Get-Process` `WorkingSet64` / `PrivateMemorySize64`,
summed over the process tree).

## 2026-11-19: frosted glass redesign, maximized (Phase 3)

- **How:** release build, fake engine (`NOBAD_FIND_FAKE_ENGINE=1`), the window maximized on the 1920 x 1200 (125 %)
  screen, 10 s to settle, then 15 s idle. RAM from `Get-Process`; GPU from the `GPU Process Memory` and
  `GPU Engine` counters for the UI's PID; frames from `NOBAD_FIND_UI_FRAMES` (frames drawn per 5 s).

| Maximized, Home, idle | Working set | Private | GPU memory | GPU busy | CPU | Frames per 5 s |
|---|---|---|---|---|---|---|
| Before (the first full UI) | 152 MB | 156 MB | 76 MB | 0.7 % | 0.05 % | 10 (caret) |
| Redesign, with Flutter blur on the palette (sigma 28) | 296 MB | 300 MB | 117 MB | 2.8 % | 0.16 % | 10 (caret) |
| Redesign, palette blur sigma 12 | 201 MB | 210 MB | 79 MB | 1.5 % | 0.05 % | 10 (caret) |
| **Redesign as shipped** (blur only in dialogs) | **163 MB** | **167 MB** | **72 MB** | 1.2 % | 0.1 % | 10 (caret) |
| Redesign as shipped, window not focused | 160 MB | 163 MB | 73 MB | 0 % | 0.03 % | **0** |

The redesign costs about 11 MB more than the first full UI, mostly the variable font file registered for the thin
display weights (1.8 MB on disk) and the larger glass layers. Flutter's `BackdropFilter` over the palette cost
40-135 MB with only the still backdrop behind it, so it is used for dialogs only; the frost is Windows' Mica (and
Acrylic for the bar), composited by Windows outside this process. Idle and focused, the only frames are the text
caret blinking in the search box (about 2 a second); not focused, nothing is drawn.

## 2026-11-19: full Flutter UI (Phase 3)

- **Branch:** `find-flutter-ui` (draft PR #77), Flutter 3.50, release build, Skia, the same PC as below.
- **How:** the UI process only (`Get-Process` on its PID), sampled once a second. Engine: `python -m nobadfind --engine`
  from source on a throwaway data folder (`NOBAD_FIND_DATA_DIR`) with a 362-file made-up corpus. The UI typed its own
  searches (`NOBAD_FIND_UI_DEMO=1`) or went through every screen (`NOBAD_FIND_UI_DEMO=tour`).

| UI process | Working set | Private | Notes |
|---|---|---|---|
| Main window, Home, just started | 128 MB | 128 MB | real engine |
| Main window after 5 searches | 140 MB | 139 MB | real engine |
| Main window after every screen, dark and light, then 10 s idle | 150-168 MB | 150-162 MB | real engine and fake engine runs |
| Quick find bar, shown with 8 rows | ~140 MB | ~130 MB | |
| Quick find bar, hidden (Esc) | 2-10 MB | 109 MB | hiding empties Skia's cache and the working set |

Skia's GPU resource cache, after the full tour (fake engine): 8 MB cap → 145 MB, 12 MB → 150 MB, 24 MB → 163 MB,
64 MB → 212 MB, 256 MB (Flutter's default) → 207 MB and still growing. The UI caps it at 12 MB
(`NOBAD_FIND_SKIA_CACHE_MB`) and empties it while hidden. The ≤ 100 MB window budget is still missed, as for the
prototype: about 100 MB of each number is the Intel D3D11 driver loaded in-process.

## 2026-11-18: Flutter prototype vs the 0.7.0 WebView2 window (ROADMAP Phase 3 step 1)

- **Commit:** `610921b` (branch `find-flutter-prototype`), Flutter 3.50 stable (Dart 3.14), release build, Skia renderer.
- **PC:** the maintainer's: Intel Core i5-12500H (16 threads), 15.7 GB RAM, Intel Iris Xe, Windows 11 Home 26300.
- **Corpus:** 3,000 generated files (text, Markdown, CSV, JSON, code, small PNGs; 9.9 MB), 2,702 index entries,
  in a temp data folder (`NOBAD_FIND_DATA_DIR`). Same corpus and data folder for every row.
- **How:** a dev-only PowerShell harness (not committed) starts the engine (`python -m nobadfind --engine`, from
  source) and the UI, lets the UI type five fixed searches into its own box (`NOBAD_FIND_UI_DEMO`, one letter
  every 120 ms), then samples memory. The WebView2 row is the 0.7.0 app (`python -m nobadfind`, from source) on
  the same data folder, with its window open about 20 s. Only processes the harness started were stopped, by PID.
- The PC was locked for the first runs, so there are no screen captures from them; the UI saved pictures of itself.

### The window (what the move to Flutter changes)

| Window | Processes | Working set | Private | Notes |
|---|---|---|---|---|
| 0.7.0 WebView2 window, idle, same corpus | 7 | **465 MB** | 238 MB | today's UI (ROADMAP §2 measured 425 / 212 MB on the full index) |
| Flutter main window, just started | 1 | 114 MB | 114 MB | home screen, connected |
| Flutter main window, after 5 searches (up to 500 results, previews) | 1 | **132 MB** | **132 MB** | 20 s later: 132 / 132 MB |
| Flutter quick find bar, shown, 8 results | 1 | 132 MB | 121 MB | |
| Flutter quick find bar, hidden (Esc) | 1 | **8.6 MB** | 110 MB | hiding hands the working set back to Windows |
| Flutter main window with Impeller (Flutter's default) | 1 | 183 MB | 187 MB | after searches; not used, see below |
| Flutter, no engine, home screen only (floor) | 1 | 118 MB (Skia) / 172 MB (Impeller) | 117 / 176 MB | |

Where the Flutter window's memory goes (floor, Skia, `VirtualQueryEx`): 104 MB private, 205 MB image (DLLs, mostly
shared), 54 MB mapped. Most of the private part is the GPU driver: Intel's D3D11 driver and its shader compiler
(`igc64.dll`, an 83 MB image) load in-process because Flutter draws with ANGLE on Direct3D 11. Flutter itself is
`flutter_windows.dll` (20.5 MB) + the app's AOT code (5 MB). The WebView2 window pays the same driver cost in its
GPU process, on top of the browser.

**Result: the window drops from 465 MB in 7 processes to about 130 MB in one (−72 %).** That's still over the
ROADMAP target of ≤ 100 MB for the window. The rest is mostly the Intel driver; see "What would get it under 100 MB".

### Start and search

| What | 0.7.0 WebView2 | Flutter prototype | Target |
|---|---|---|---|
| UI process start to first frame | n/a (the window shows 1.8 s after the app starts, engine included) | **0.20 s** main, **0.13 s** bar (Impeller: 0.84-0.99 s) | ≤ 1.5 s cold start |
| Pipe + JSON round trip on top of the search | n/a (pywebview bridge) | **≤ 1 ms** (UI time − engine time; 4 ms for 500 results) | |
| Search keystroke to answer, engine side, 2,702 files (last 40 searches in the log) | not measured | median **2.8 ms**, 90th percentile 98 ms, max 122 ms; 6 of 40 over 80 ms, all short words that also match text inside files | ≤ 80 ms names, ≤ 250 ms meaning |

The engine log (`rpc search … ms (ranking … ms)`) and the UI timing file agree: the pipe adds under a millisecond;
the time is the ranking in `search.py`. Short words that hit text inside files (e.g. "tax": 95-121 ms) are over
the 80 ms names budget: that's Phase 1 engine work, not the UI.

### The engine (unchanged by the prototype, for reference)

| Engine | Processes | Working set | Private |
|---|---|---|---|
| `--engine`, idle after indexing, UI connected | 3 (venv launcher, console host, engine) | 132 MB | 567 MB |
| 0.7.0 app's engine process (same corpus) | 1 (+7 WebView2) | 147 MB | 583 MB |

The engine commits about 560 MB with nothing loaded: the Phase 1 "commit" problem (ROADMAP §2 cause 2), seen here
on a small index too. Running it headless doesn't change it.

### Impeller vs Skia (why the prototype uses Skia)

Same build, same runs, `NOBAD_FIND_RENDERER` switch: Impeller (Flutter 3.50's default on Windows) took 0.84-0.99 s
to the first frame and 183-188 MB; Skia 0.20 s and 132 MB. On this PC Impeller compiles more shaders at start through
the Intel compiler. Skia is still supported on Windows in 3.50, but Flutter is moving to Impeller: re-measure each
Flutter upgrade, and re-check on a PC with another GPU (AMD/NVIDIA) before the full move.

### What would get the window under 100 MB (not done in the prototype)
- Release GPU memory when the window is hidden or idle (Skia resource cache limits; `EmptyWorkingSet` already gives
  back the working set when the bar hides).
- Close the UI process when the window closes (planned: the engine starts it on the hotkey). Then "window closed"
  costs nothing for the UI, which matters more than the open-window number.
- One process for the main window and the bar (two engines and two driver copies today if both are open).
- Try Flutter's software renderer fallback for the bar only, and Impeller again on future Flutter versions.
