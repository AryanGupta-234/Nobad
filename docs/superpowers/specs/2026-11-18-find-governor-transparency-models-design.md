# NOBAD Find: smart resource governor, full transparency, model tiers, UI refresh

Date: 2026-11-18. Status: design, awaiting the maintainer's approval. App: `apps/find/` (current 0.6.1).

## Intent

Make NOBAD Find better on every PC, and honest about what it does. The maintainer's words: "keep user
transparency": show which models run, their progress, and how much of the PC they take. Use bigger models
only when the PC can carry them, and only after the user agrees. Stop pausing for games when there's room to
spare; back off only when the PC is really busy. Never leave processes behind: closing the app ends everything
unless the user chose background indexing. And make the app look finished: a splash screen, a fuller home
screen, and better Indexing and Settings pages.

This is general improvement, not a reaction to complaints.

## Goals

1. **Resource governor (approach A + a little of B):** live measurement of the PC's headroom decides how hard
   Find works, instead of fixed on/off pauses. It learns per app (the "bit of B", below) and explains every
   decision.
2. **Strict process lifecycle:** every Find process lives in one Windows job object; quitting or crashing ends
   them all. Frozen or runaway work is detected and killed automatically.
3. **Transparency:** Indexing shows each phase, each model, live resource use of Find itself and why it is
   working at its current speed.
4. **Model tiers:** a hardware scan recommends Light / Balanced / Best models for text meaning, photo meaning and
   OCR; the user agrees to every download.
5. **UI refresh:** splash screen, richer home screen, reorganized Settings and Indexing, using the NOBAD design
   language already in `ui/app.css` (one NOBAD orange, dark/light, glass).

## Non-goals

- Throttling, pausing or killing **other** apps. Find only ever limits or kills its own processes.
- A trained ML model making governor decisions. Decisions stay rules + per-app memory, readable by a person.
- Any new outbound connection besides the model downloads the user agrees to (house rule: every outbound
  connection needs a setting and an entry in SYSTEM-INTEGRATION.md).
- Telemetry. Learned app profiles and resource stats stay on the PC.
- Running elevated (Find always runs as the normal user; the admin "turbo" idea stays out).

## Anti-goals (fails even if it "works")

- Find makes a game stutter, or a call lag.
- The user can't tell why Find is slow, paused or using memory.
- A process named NOBAD Find is still running after the user quit (with background indexing off).
- A big download starts without the user saying yes.
- Smart behaviour that can't be explained in one sentence in the UI.

## Constraints

- Windows 10 1809+ / 11, x64, Python + pywebview (WebView2), PyInstaller build, Inno Setup installer
  (`apps/find/packaging/`). Normal-user rights only.
- Models: permissive licence (Apache-2.0/MIT), pinned revision, size + SHA-256 verified, downloaded only with
  consent (same as `embed.download_model` / `photo.download_model`).
- UI is a strict-CSP local page (`ui/index.html`: no inline scripts, `script-src 'self'`).
- Releases only from CI (`find-v*` tag → `find-release.yml`), and everywhere: version, changelog, website
  (`nobad-studio/website`), memory repo.
- Existing tests (136) keep passing; `pyflakes` clean.

## Approaches considered

| | Approach | Trade-off |
|---|---|---|
| **A (picked)** | Rule-based governor: measure headroom every few seconds, scale workers, pause only when really busy; job object for processes | Explainable, cheap, predictable. Needs careful thresholds. |
| B | Learned/AI "brain" deciding when to work | Could adapt better, but opaque, heavier, clashes with transparency |
| C | Keep on/off pauses, just show more stats | Simplest; still pauses needlessly during light games |

**Picked: A, with a bit of B** (maintainer, 2026-11-18): A's rules, plus a per-app memory that learns from what
actually happened, so a game that lagged once gets more room next time. Every learned item is visible and
resettable.

## Design

### 1. Resource governor (`nobadfind/governor.py`, new)

A thread in the main process samples every 2 s (cheap Win32 calls through `winapi.py`, no new dependency
required; `psutil` is acceptable if it saves real work, builder's call):

- System: total CPU % (`GetSystemTimes`), memory load and free RAM (`GlobalMemoryStatusEx`), GPU utilisation
  (PDH "GPU Engine" counters; skip if unavailable), disk busy (PDH "% Idle Time" of the drive being read).
- Find's own use: CPU %, working set, I/O bytes, summed over every process in Find's job object
  (`QueryInformationJobObject`), and per process for the transparency panel.
- Context: foreground app exe and full-screen state (existing `busy_fullscreen`), battery (`on_battery`),
  calls (`in_call`), user idle time (`idle_seconds`).
- Lag signal: the foreground window stops answering (`IsHungAppWindow` / `SendMessageTimeout(WM_NULL)` over
  ~250 ms) while Find is working, or system CPU sits ≥ 95 % with Find using a real share of it.

It outputs a **work level** with a one-line reason:

| Level | Meaning | Typical trigger |
|---|---|---|
| Full | all planned workers, models may use GPU | user away (existing `IDLE_AFTER` 120 s), lots of headroom |
| Gentle | today's "while you use the PC" plan | normal use |
| Light | 1 worker, CPU only, longer breaks | a game or heavy app running, but headroom left |
| Paused | nothing runs | headroom gone, lag seen, battery/call rules, user pause |

Rules (thresholds are the builder's to tune; these are the intent):
- A full-screen game alone no longer pauses. It moves Find to **Light**; Find pauses only if system CPU or GPU
  stays above ~85 % for 10 s, free RAM drops under ~1.5 GB, or a lag signal fires.
- Hysteresis: step down immediately, step up only after ~30 s of headroom, one level at a time.
- Battery and call pauses stay as today (user settings). The setting "Pause during games and presentations"
  becomes **"During games: Smart (recommended) / Always pause / Don't change"**. Presentations ("quiet time",
  `QUNS_PRESENTATION_MODE`) always pause.
- Indexer integration: replace `_check_pause` / `_wait_while_paused` / `_breathe` and the gentle/full worker
  choice in `_read_texts` with the governor's level. The worker pool is sized for Full; the level limits how many
  jobs are in flight. Models use GPU (DirectML) only at Full.
- Hard caps by level are enforced by the job object's CPU rate control (`JOB_OBJECT_CPU_RATE_CONTROL`), so even a
  misbehaving worker can't exceed the level (Light ≈ 15 % of the CPU, Gentle ≈ 35 %, Full uncapped; builder
  tunes).

**Per-app memory (the bit of B):** when a lag signal or a step to Paused happens with app X in the foreground,
the governor records it for X (exe name only, not paths or titles): `{exe: {seen, lag_events, worst_cpu,
worst_gpu, start_level, last_seen}}`. Next time X is in the foreground, Find starts at the learned level
(Light or Paused) instead of probing up. Several quiet sessions with X raise its start level again. Stored in
the encrypted index database. Settings shows the list ("Apps NOBAD Find has learned to make room for"), with
the reason per app and a reset button per app and for all.

### 2. Process lifecycle and watchdog

- Two nested job objects. **Outer job** (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, no CPU cap): the main process
  assigns itself at start, so everything Find starts (WebView2 included) is inside; if the main process quits or
  crashes, Windows ends every process in it. **Inner worker job** (nested in the outer one): text readers, OCR,
  the photo worker and a new **meaning worker**; the level's CPU rate caps apply to this job only, so search and
  the window stay responsive during a game.
- Index-time meaning vectors (`_make_vectors`, `_name_vectors`, today in the main process) move into the meaning
  worker, which loads its own model and returns vectors to the main process for the vector index. Live search
  keeps a small CPU-only query encoder in the main process (one short text per search; released when idle as
  today). GPU (DirectML) is used only by workers, and only at Full. The Models cards show memory per process.
- New setting **"Keep indexing in the background after closing"** (default **off**). Off (maintainer's choice,
  2026-11-18): closing the window stops the indexer, ends every worker process and releases the models; only the
  main process stays, idle, so the hotkey still opens Find (indexing resumes when the window opens). On: closing
  hides the window and indexing continues. If the hotkey couldn't be registered, closing quits completely.
  "Start with Windows" keeps today's meaning (starts hidden, hotkey ready) and follows the background setting
  for indexing.
- Upgrade from 0.6.x: the new setting starts off for everyone; the changelog and a one-time notice on the
  Indexing page say how to keep background indexing.
- The existing "Quit NOBAD Find" stays and always quits completely.
- Watchdog (in the governor thread):
  - A reader stuck on one file longer than its limit: kill that pool and mark the file (exists today in
    `_kill_pool`; keep it and log it to the activity list).
  - A worker whose memory passes a cap (say 1.5 GB; builder tunes): kill it, recycle the pool, skip the file.
  - Find's whole job above a memory cap: release models (`release_idle_models` with idle=0), recycle pools.
  - The main UI not responding (the page's heartbeat to the API stops for ~15 s): log it and reload the page;
    if that fails twice, quit cleanly (job closes everything) so a stuck Find never lingers.
  - Every kill shows in the activity list with its reason.

### 3. Transparency (Indexing page)

Redesigned Indexing view (`ui/`), fed by an extended `Api.status()`:

- **Pipeline:** names → text → photos' words (OCR) → meaning → photo meaning → watching. Per phase: state
  (waiting / running / done / off), progress bar with counts, rate, ETA.
- **Right now:** the work level and its reason ("Light: Forza is using 70% GPU, so NOBAD Find uses 1 worker"),
  with a "Pause for 1 hour" / "Resume" control.
- **NOBAD Find's resource use:** live CPU %, memory MB, disk MB/s, GPU % of the whole job, a short 5-minute
  sparkline, and a per-process list (Main, Text reader ×N, Photo worker) with each one's CPU and memory.
- **Models:** one card per model: name, licence, tier, size on disk, in memory or not (and how much), CPU or
  GPU, items done (vectors), download progress (MB, MB/s) when downloading.
- **Activity:** the last ~50 governor and watchdog events with time and reason.

### 4. Model tiers (second release)

A hardware scan (`nobadfind/hardware.py`, new): RAM total/free, CPU cores and AVX2/AVX-512 VNNI, GPU name and
dedicated VRAM through DXGI (DirectML capable or not), free disk on the data drive, SSD or not (`is_ssd`).
Result shown in Settings → Models as "Your PC" and turned into a recommended tier:

| Tier | Typical PC | Text meaning | Photo meaning | Words in photos (OCR) |
|---|---|---|---|---|
| Light | < 8 GB RAM or ≤ 4 cores | all-MiniLM-L6-v2 (current, 23 MB) | off | Windows OCR (current) |
| Balanced | 8–16 GB, 4+ cores | multilingual-e5-small (MIT) | SigLIP base (current, ~211 MB) | Windows OCR |
| Best | 16 GB+ and 8+ cores, or a DirectML GPU with 4 GB+ | multilingual-e5-base (MIT) | e.g. a larger SigLIP / SigLIP 2 (Apache-2.0) | Windows OCR + an ONNX OCR model (e.g. RapidOCR/PaddleOCR, Apache-2.0) for scans and screenshots |

**Multilingual** (maintainer, 2026-11-18): Balanced and Best text models must handle non-English files and
searches, Hindi and mixed Hindi/English included (e.g. multilingual-e5-small for Balanced, multilingual-e5-base
for Best, MIT; they need the "query: " / "passage: " prefixes in `embed.chunk_text`/`name_text` and the query
encoder). Light stays all-MiniLM-L6-v2. Windows OCR uses the installed Windows language packs; the ONNX OCR model
for Best should cover Latin and Devanagari scripts. The test set includes Hindi and mixed-language files.
Model choices in the table are candidates: the builder verifies licence, ONNX availability, quantized size and
quality on a small test set before pinning revisions and SHA-256s. The tier is a recommendation; the user can
pick per feature.

- **Consent:** a dialog per download: model name, licence, size, source (Hugging Face), what it improves, the
  cost on this PC (RAM when loaded, extra indexing time). Nothing downloads without "Download". Existing
  `allow_*_download` settings remain the stored consent.
- **"Auto-configure" button:** applies the recommended tier, then asks for each download it needs.
- Switching the text model rebuilds the meaning vectors in the background (old ones stay usable until the new
  ones are ready; the Indexing page shows the rebuild as its own phase). Vectors carry the model id so mixed
  states can't be searched together.
- First run: after the splash, a short welcome shows "Your PC" and the recommended tier; all optional.

### 5. UI refresh

Use the frontend-design skill; stay within the NOBAD look (one NOBAD orange, dark/light, glass, the mark).

- **Splash:** a native splash while the packaged app unpacks and starts (PyInstaller's `pyi_splash` with the
  NOBAD mark and "Starting…"), closed as soon as the window is ready. No splash when started `--background`.
- **Home (empty search):** keep the search bar first; under it, instead of the long paragraph: example query
  chips (clickable), quick kind tiles (PDFs, Photos, Documents, Downloads…), "Recently changed" (a handful of
  files from the index), and a small status line (files indexed, level, "Details" to Indexing). Keyboard hints
  stay.
- **Settings:** sections become pages in a left sub-nav: General, Indexing (folders, drives, content, OCR),
  Models (Your PC, tiers, per-model cards, consent), Performance (games mode, battery, calls, background
  indexing, workers, learned apps), Privacy & data (wipe, Windows Search), About. Each control keeps today's
  plain-language help text.
- Search results: the fixes from 2026-11-18 (linking words, Enter keeps the window) are already on branch
  `find-0.6.2`.

## Releases

1. **0.7.0:** query fixes (done), governor + per-app memory, job object + watchdog + close behaviour,
   transparency on Indexing, splash, home, Settings reorganisation, hardware scan shown as info.
2. **0.8.0:** model tiers, consent dialogs, auto-configure, vector rebuild.

Each ships through the release playbook (CI tag, website product page and releases.json, memory facts).

## Decided by the maintainer

- Approach A with a bit of B (per-app memory) for the governor.
- Bigger models only when the hardware scan says the PC is eligible, and only with consent.
- Smart game handling: don't pause while resources are fine; pause when the PC is heavily loaded.
- Closing strictly ends every process unless the user checked background indexing.
- Detect lag/crashes of Find's own work and kill it automatically.
- Use subagents and the UI/UX (frontend-design) skill to build it.
- Closing with background indexing off: hotkey stays, everything else stops.
- Bigger text models are multilingual (Hindi and mixed Hindi/English included).

## Calls made by the designer (correctable)

- Background indexing defaults to off (maintainer chose: hotkey stays, everything else stops).
- Job-object caps cover only the worker job; meaning vectors move into a worker (designer's call after the builder check).
- Presentations always pause; games use Smart by default.
- Learned app profiles store exe names only, in the encrypted index.
- Two releases, governor/UI first, models second.
- Thresholds in this document are starting points for tuning, not contracts.

## Left to the builder

Exact thresholds and caps, PDH vs psutil, the UI layout details inside the NOBAD style, model candidates after
verification, how status is streamed to the page (polling today's `status()` is fine), test strategy for
Windows-only APIs (fakes for the governor's sensors).
