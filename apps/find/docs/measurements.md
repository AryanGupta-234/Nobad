# NOBAD Find: measurements

Numbers decide (ROADMAP §3). Every performance claim points at a row here. Newest first. Working set = RAM in use
now; private = committed memory only this process can use (`Get-Process` `WorkingSet64` / `PrivateMemorySize64`,
summed over the process tree).

## 2026-11-19: engine baseline with `tools/measure.py`, and the Phase 1 engine diet

- **Commits:** baseline `b945911` (= `find-flutter-prototype` `1e8a1e2` + the harness); after = the Phase 1 commit on
  branch `find-measure`.
- **PC:** the maintainer's (i5-12500H, 16 threads, 15.7 GB, Iris Xe, Windows 11 26300). Nothing else heavy running.
- **How:** `python tools/measure.py --files 3000 [--entry launch]` (dev only, see its docstring). 3,000 generated files
  (750 txt, 390 png, 360 pdf, 300 docx, 300 py, 240 md, 240 csv, 150 html, 150 json, 120 eml; 7.5 MB) → 5,161 index
  entries, 2,790 with text, 8,314 chunks. Each level runs on a fresh temp index with the level fixed
  (`NOBAD_FIND_MEASURE_LEVEL`) and its own pipe (`NOBAD_FIND_MEASURE_PIPE`), so it can run next to another engine.
  The harness samples every process in the engine's tree once a second. No models: the meaning and photo models
  aren't downloaded on this PC, so ONNX Runtime isn't in these numbers. Only processes the harness started were
  stopped, by PID.
- **`--entry launch`** starts the engine through `packaging/launch.py`, the script `NobadFind.exe` runs. That matters:
  a pool worker runs the parent's entry *script* again, but multiprocessing never re-runs a package's `__main__`, so
  `python -m nobadfind` workers looked fine while the shipped exe's didn't.
- Private = committed memory (`PagefileUsage`), working set = RAM in use, both summed over the tree. CPU % is of one
  core. Means over the scenario's samples, then the max.

### The ~4 GB commit, found

| | Private while indexing, Gentle (mean / max) | Full | Per text reader | Engine alone, idle |
|---|---|---|---|---|
| Baseline, `--entry launch` (like the exe) | **4,460 / 4,866 MB** | **8,002 / 8,474 MB** | 544 MB | 518 MB |
| After | **390 / 608 MB** | 549 / 689 MB | ≤ 60 MB | 34 MB |

Both causes come from numpy's OpenBLAS. As it loads, it commits about 32 MB per CPU thread: 515 MB on 16 threads
(measured: 1 thread 19 MB, 2 threads 53 MB, 4 threads 120 MB, 8 threads 255 MB, 16 threads 525 MB).
1. `packaging/launch.py` imported `nobadfind.app` at the top, so every worker of the exe loaded the whole app, numpy
   included (`-X importtime`: 0.78 s, 0.68 s of it numpy). Now the import comes after `freeze_support()`. A reader
   imports only `extract`: 35 ms, down from 219 ms, now that mail parsing loads only for .eml/.mbox files.
2. The main process paid the same cost. `nobadfind/__init__.py` now loads numpy with `OPENBLAS_NUM_THREADS=1`, then
   puts the variable back so programs Find opens don't inherit it (a value the user set wins). One thread is as fast
   or faster for Find's numpy work: scoring a 65,536 x 384 block takes 47.8 ms on 1 thread vs 47.4 ms on 16; the PCA
   fit (SVD of 8,000 x 384) takes 0.47 s on 1 thread vs **4.1 s** on 16.

### Indexing got 3-6x faster: background mode was thrashing the readers

Windows background mode (`PROCESS_MODE_BACKGROUND_BEGIN`) is what every worker used. Entered as a process starts, it
pins the working set near 32 MB, and a reader parsing PDFs then page-faults constantly. 30 PDFs in a real pool worker
took **6.2 s with 3.0 million page faults** (4.6 s of it kernel time), against **0.31 s and 7 thousand** at normal
priority. Workers now set the three priorities themselves (`winapi.worker_priority`): idle CPU class, low memory
priority (2) and very low I/O priority (0). Measured per process: memory 2, I/O 0 (before: 1 and 0, through
background mode).

| Indexing 3,000 files | Baseline `-m` | Baseline `--entry launch` | After (both entries) |
|---|---|---|---|
| Gentle (8 readers, 35 % CPU cap) | 17.1 s, 394 % CPU | 51.1 s, 547 % CPU | **15.0 s**, 180 % CPU |
| Full (15 readers, no cap) | 16.4 s | 58.3 s | **10.0 s**, 390 % CPU |
| Light (1 reader, 15 % cap; EcoQoS on) | 50.1 s | | **31.0 s** |

For the same files, the workers' CPU time fell from 56 core-seconds (baseline `-m`) to about 25. The working set
while indexing is higher (Gentle 308 → 515 MB mean) because the readers are no longer squeezed into 32 MB each. Low
memory priority puts those pages first in line when Windows needs memory back.

### Every scenario, after (`--entry launch`, Gentle; baseline in brackets)

| Scenario | Procs | Working set MB (mean / max) | Private MB (mean / max) | CPU % mean | Handles | Threads |
|---|---|---|---|---|---|---|
| Cold start (5 s) | 2 | 50 / 54 (53 / 56) | **32 / 34** (515 / 519) | 7.1 (12.7) | 365 | 12 (27) |
| Idle, no UI | 2 | 54 (56) | **34** (519) | 0.0 | 365 | 12 |
| Indexing, Gentle | 17 (10) | 515 / 783 (332 / 344) | **390 / 608** (4,460 / 4,866) | 182 (547) | 3,393 | 78 (215) |
| Idle, UI connected | 2 | 88 (90) | **62** (545) | 0.0 | 448 | 16 |
| Search typing | 2 | 96 (98) | **70** (554) | 13.5 | 449 | 13 |
| Window closed (`ui_hidden`) | 2 | **17** / 97 (91 / 99) | **64** / 71 (546 / 554) | 0.1 | 450 | 14 |

The 2 processes are the engine and its console host (it was started from a console). The engine is ready in 0.39 s
and gives its first pipe answer at 0.66 s. Search typing over the pipe (114 keystrokes, 10 questions): round trip
median 2.6 ms, 90th percentile 78 ms, max 94 ms, with 9 keystrokes over 80 ms (baseline: 2.9 / 69 / 105 ms, 5 over).
The pipe adds well under 1 ms. The slow keystrokes are short words that hit text inside files (as in the prototype
run below); that's ranking work, still open.

### Each change, and what it bought

| Change | Before → after | Kept because |
|---|---|---|
| `launch.py` imports the app after `freeze_support()` | 544 → ≤ 60 MB private per reader (exe) | it was the 4 GB commit |
| numpy with one OpenBLAS thread | engine 518 → 34 MB private idle; PCA fit 4.1 → 0.47 s | win |
| Mail parsing imported only for .eml/.mbox | reader import 219 → 35 ms | win (readers restart, see below) |
| `worker_priority` instead of background mode | Gentle 51 → 15 s, Full 58 → 10 s; 3.0 M → 7 k faults per 30 PDFs | win |
| `EmptyWorkingSet` when indexing goes idle (window closed) | closed: 91 → 17 MB working set (engine 10 MB) | win |
| Text readers end after 200 files (`max_tasks_per_child`) | no growth to give back on this corpus (readers ≤ 60 MB); a restart costs ~35 ms of imports | backstop for pdf/zip heap fragmentation. Tested on 3.11.9 with the indexer's submit/wait pattern (400 tasks, no stall) |
| Worker job memory limit (`JOB_OBJECT_LIMIT_JOB_MEMORY`, ¼ of RAM, 1-4 GB) | 4 GB on this PC; normal indexing commits ≤ 0.7 GB | backstop above the watchdog: a worker over it gets a `MemoryError` (already handled) instead of the PC paging. The baseline exe (8 GB at Full) would have hit it, so the import fix had to come first |
| EcoQoS for workers at Light and Paused only | Light 31 s with it; in a test run with EcoQoS at Gentle too, a thrashing reader was 1.6x slower again | Light and Paused mean a game, a call or a busy PC, where staying out of the way matters most; Gentle and Full keep full clocks. The power saving can't be measured here |
| ONNX Runtime arenas | not measured: no model on this PC (and no download) | open |

### Against the ROADMAP budgets

| Budget | Target | Now |
|---|---|---|
| Indexing, Gentle, 16-thread PC | ≤ 600 MB private total | **390 MB mean, 608 MB max** (no models). Met on average. The max comes from 15 processes alive at once: while recycling, the pool keeps up to the Full count (`max(gentle, full)`) |
| Window closed (idle process) | ≤ 60 MB, CPU ≈ 0 % | **17 MB working set** (engine alone 10 MB), **64 MB private**, 0.1 % CPU. Private is 4 MB over: Python, SQLCipher, the pipe server and their threads |
| Engine with the window open, idle, models released | ≤ 120 MB | 88 MB working set, 62 MB private |
| Cold start to usable engine | ≤ 1.5 s (window) | engine 0.39 s, first pipe answer 0.66 s |
| Search keystroke | ≤ 80 ms names | median 2.6 ms; 9 of 114 over 80 ms (short words matching text inside files) |

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
