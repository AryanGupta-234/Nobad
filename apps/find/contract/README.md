# NOBAD Find: the UI ⇄ engine contract

The only thing the Flutter UI and the Python engine know about each other. If code and this folder disagree, the
tests fail (`tests/test_rpc_contract.py` on the Python side; the Dart side replays the same transcripts).

| File | What it is |
|---|---|
| [`methods.schema.json`](methods.schema.json) | Every method: JSON Schema of its `params` and its `result`, plus shared shapes in `$defs` |
| [`events.schema.json`](events.schema.json) | Every event the engine pushes: JSON Schema of its `params` |
| [`transcripts/*.jsonl`](transcripts) | Recorded sessions, replayed by both test suites |

Protocol version: **1** (`"protocol"` in both schema files and in `hello`'s answer). Version 1 only ever grows:
new methods, new events, new keys in an answer. A change that breaks an old UI raises the version.

## The connection

- Pipe `\\.\pipe\NOBADFind-<user SID>`, only for the current user, no remote clients. Before trusting it, the UI
  checks the pipe's server process runs as the same user (the prototype's `pipe_client.dart` does this).
- JSON-RPC 2.0, **one JSON object per line** (`\n`), UTF-8, at most 1 MiB per line either way. The engine writes
  ASCII only (non-ASCII as `\uXXXX`).
- Requests carry an `id` (number or string). Replies can come in any order: match them by `id`.
- Events are notifications (no `id`): `{"jsonrpc":"2.0","method":"<event>","params":{...}}`. Ignore event names you
  don't know.
- Errors: `{"jsonrpc":"2.0","id":…,"error":{"code":…,"message":"…"}}`. Codes: `-32700` not JSON, `-32600` not a
  request (also "Message too big", after which the engine closes the pipe), `-32601` unknown method, `-32602` bad
  params, `-32603` the engine failed (never with details). Wrong *types* are errors; a well-formed request the engine
  can't carry out is a normal result with `"ok": false` and a sentence in `"error"`. The engine checks what the
  schema says (types, the filter words, lengths, `seconds ≥ 1`): a request the schema refuses gets `-32602`.
  `NaN` and `Infinity` are not JSON: `-32700`.
- Unknown keys in `params` are ignored by the engine, but the schemas don't allow them: don't send them.
- At most 8 connections. Requests run on a pool of 4 threads, so a slow call doesn't hold up a search; the calls
  that wait for the user (`pick_folder`, `wsearch_set`, `use_instead_of_windows_search`, `turbo_set`) run on threads of their own
  and only one of each waits at a time, so search, status and quit always get an answer.

### Start-up order for a UI

1. `hello`: check `protocol` is 1 (refuse a newer engine and say why). `pid` is the engine's process id: call
   `AllowSetForegroundWindow(pid)` before `pick_folder` and `wsearch_set`, so their windows can come to the front.
2. `subscribe` to what this window needs (main window: `status level activity download notice show here quitting`;
   bar: `show quitting`).
3. `status` once (events only report changes), then `ui_shown` when the window is on screen.
4. On `ui_hidden`/close, say `ui_hidden`. If the pipe breaks, reconnect with backoff, unless `quitting` came first.

## Methods

Types below are short; the schema is exact. `Ok` = `{ok: bool, error: string}` (`error` is `""` when `ok`, and may
be `""` when not). Files are always named by a result **`id`** from `search`, never by a path.

### Connection

- **`hello`** `{}` → `{protocol, app, version, pid, events: [string], methods: [string]}`. Who's there.
- **`subscribe`** `{events: [string]}` → `{events: [string]}`: start getting these events on this connection;
  the answer lists everything this connection now gets. Unknown names are ignored. If notices were waiting for a
  listener, they arrive just *before* this reply.
- **`unsubscribe`** `{events: [string]}` → `{events: [string]}`: stop getting them.

### Search and results

- **`search`** `{text?: string (≤ 2000), filters?: Filters}` → `{results: [Result], understood: [string], terms:
  [string], notes: [string], more: bool, ms: int, error: string, parts: [Part], best: BestGuess|null}`. Empty text
  with no filter gives no results.
  `filters` is an object or left out (`null` is refused). `understood`
  is how the question was read (show as chips), `terms` the words to highlight, `notes` sentences for the user,
  `more` = there were more matches than shown, `error` = `""` or a sentence when the search failed.
  - `Filters` (all optional, `""` = off): `kind` (`pdf document spreadsheet slides text code email image video audio
    archive ebook app folder`), `modified` (`today week month year`), `size` (`small medium large`), `folder`
    (`here`, a known folder word, or a folder path already in the index; ≤ 2000), `sort` (`newest oldest largest
    name`). Any other key or word is refused (`-32602`).
  - `Result`: `{id: int, path, name, dir, kind: string, size: int|null, mtime: number|null (seconds since 1970),
    ago: string, why: [string], snippet: string, weak: bool}`. `weak` = a loose match, show it as less sure.
    Every string is untrusted text from the user's disk: show it as plain text, never as markup.
  - `Part` (0.8.5, smart search): `{kind, label, without}`, how the question was understood, in display order
    (where, what kind, when, size, order, then what it's about): `kind` is `folder drive kind time size sort meaning
    words` (`meaning`: what it's about, searched by meaning with a model; `words`: the same by words only). `label`
    is the chip's text ("Downloads", "Images", "2 boys"); `without` is the question with that part taken out, so a
    chip's remove x just searches `without` (the engine stays the one place questions are understood).
    "2 boys in an image in downloads" → `[folder Downloads] [kind Images] [meaning "2 boys"]`, and "2 boys" goes to
    photo meaning restricted to Downloads.
  - `BestGuess`: `{id, reason}`, the one result the engine is sure of (an exact name, the only name that starts like
    what was typed, the only match, the picture that clearly fits best, a clear winner on name and content). When
    there is one it is always `results[0]`, so Enter opens it. `null` when unsure.
  `channel` (optional, default `"main"`): which search of the UI this is (`"home"` for the Home list, `"bar"`). A newer search on the same connection and channel cancels the one still running, which then answers with `cancelled: true` (and no results): ignore that answer. Other channels are left alone.
- **`suggest`** `{text: string (≤ 2000), channel?: "main"|"bar"|...}` → `{items: [Suggestion], complete: string}`:
  autocomplete for every keystroke (well under a millisecond on the eval corpus, `docs/measurements.md`). Up to 8
  items (5 for `channel: "bar"`), in order: the user's own past questions (only while `search_history` is on), the
  phrases search understands that complete the last words ("in d" → "in downloads", "ima" → "images", "last w" →
  "last week", folders under the user's folders "in pro" → "in Projects", other drives "on d drive"), then names in
  the index whose words start with the last word typed. `Suggestion`: `{text, kind: history|filter|file|folder,
  label, detail, id?}`: `text` is the whole question to search, `label` what to show (plain text), `detail` a file's
  folder or a filter's kind, `id` a file's or folder's result id. `complete` is the inline (ghost) completion, it
  starts with exactly the typed text, or `""`. It never fails a keystroke: a problem gives no items.
- **`history_add`** `{text}` → `{ok, saved}`: the UI tells the engine a question was used (Enter, a result opened, a
  suggestion picked). Kept for autocomplete inside the encrypted index (at most 200, oldest dropped) while
  `search_history` is on; `saved: false` when it's off or the text is too short. Only the user's own typed questions:
  no activity history (maintainer decision 2026-11-19).
- **`history_forget`** `{text}` → `Ok`: the x on a history suggestion. `ok: false` when it wasn't kept.
- **`history_clear`** `{}` → `Ok`: Settings > Privacy, "Clear search history". Turning `search_history` off clears it
  too.
- **`open`** `{id}` → `Ok`: open with the default program (outside NOBAD Find's process group, so it survives Quit).
- **`open_with`** `{id}` → `Ok`: Windows' "Open with" list for that result. It runs in a small helper started outside
  NOBAD Find's process group, so the program chosen there survives Quit like `open`. By id only, never a path.
- **`reveal`** `{id}` → `Ok`: File Explorer with the file selected.
- **`thumbnail`** `{id}` → `{url: string}`: `data:image/png;base64,…` (or jpeg/bmp) from Windows' thumbnail cache for
  photos, videos and PDFs, or `""` (keep the kind badge).
- **`path_of`** `{id}` → `{path: string}`: for Copy path; `""` if the file is gone.
- **`forget`** `{id}` → `Ok`: remove from the index and add to the excluded folders.
- **`here_folder`** `{}` → `{path: string}`: the File Explorer folder the hotkey was pressed in (what "here" means), or
  `""`. The `here` event brings the same value as soon as it is known.
- **`to_main`** `{text?: string (≤ 2000)}` → `{ok: true}`: the bar's Alt+Enter. The engine sends `show {what: "main", text}`,
  so the main window comes up with the same words in its search box.

### Status and the governor

- **`status`** `{}` → `StatusBrief` = `{level, reason, phase, files: int, paused: string}`: the status line.
  `level` is `full gentle light paused` (or `""` before the first decision), `reason` a sentence, `phase` one of
  `starting names text images meaning photos watching error`, `paused` = `""` or why indexing is paused.
- **`status_full`** `{}` → `Status`: everything the Indexing page shows. Always has: the counters (`files texts
  vectors with_text chunks name_vectors photo_vectors errors rate last_scan db_bytes`), `encrypted`, `version`,
  `model`/`photo_model` (`{state: missing|downloading|ready, got, size: bytes, error}`), `memory_mb`,
  `models_loaded`, `admin`, `roots`, `ocr` (`true`, or a sentence saying why Windows OCR isn't there), `drives`
  (`[{root, type, label, present}]`), `level`, `reason`, `paused`, `phase`, `plan`, `history` (the last 5 minutes:
  `[{t, cpu, gpu, find_cpu, find_mb, level}]`, one point per 2 s), `resources` (`{cpu, memory_mb, read_mb_s, gpu,
  processes: [{name, pid, cpu, memory_mb}]}`), `phases` (`[{id: names|text|ocr|meaning|photos|watching, label,
  state: off|running|waiting|done, done, total|null, rate, eta_s|null}]`), `models` (cards: `[{id:
  meaning|photo|ocr, name, license, size_mb, on_disk, loaded, memory_mb|null, device, items, download:
  null|{got_mb, size_mb, mb_s}}]`), `activity` (newest first, at most 50: `[{t, kind, text}]`). Other keys may
  appear (indexer details); ignore them.
- **`pause_for`** `{seconds: int ≥ 1}` → `Ok`: pause indexing (at most 24 hours; less than 1 is `-32602`).
- **`resume`** `{}` → `Ok`: end a pause now.
- **`learned_apps`** `{}` → `{apps: [{exe, seen: int, lag_events: int, worst_cpu: number|null, worst_gpu:
  number|null, start_level: level|null, last_seen: number|null, reason: string}]}`: what was learned about apps
  NOBAD Find slowed down (program file names only).
- **`reset_learned`** `{exe?: string (≤ 260)|null}` → `Ok`: forget one app, or every app (`exe` null or left out).
- **`hardware`** `{}` → `{ram_gb, cores, threads, avx2, avx512_vnni, gpu, vram_gb, directml, disk_free_gb, ssd:
  bool|null}`: the "Your PC" facts (measured once per engine run).

### Settings and the index

- **`get_settings`** `{}` → `Settings`: every setting (names and types: `$defs/settings` in the schema; they are
  `const.DEFAULTS`).
- **`set_settings`** `{changes: {name: value}}` → `{changed: [string], settings: Settings}`: the engine checks every
  value (`settings.coerce`); a value that doesn't fit becomes the default, unknown names and `wsearch_prev` are
  ignored. `changed` lists what really changed, `settings` is the result. A new hotkey takes effect after the
  engine restarts.
- **`pick_folder`** `{}` → `{path: string, busy: bool}`: Windows' folder dialog, shown by the engine, topmost;
  `path` `""` if cancelled. The answer comes when the user closes the dialog: **no time limit** on this call. Only
  one dialog at a time: while one is open, another call answers at once with `busy: true` (and `path: ""`) and
  brings the open dialog to the front again; don't treat that as a cancel.
- **`rescan`** `{}` → `Ok`: walk every folder again now.
- **`wipe`** `{confirm: string}` → `Ok`: delete the whole index and start over, only with `confirm: "DELETE"`; any
  other word gives `ok: false` and nothing happens.

### Models

- **`download_model`** `{}` → `Ok`: download the meaning model; needs `allow_model_download` on (else `ok: false` with a
  sentence). Progress comes as `download` events.
- **`download_photo_model`** `{}` → `Ok`: the same for the photo model (`allow_photo_model_download`).
  Both stay for older UIs; the 0.8.0 Settings → Models page uses the methods below.
- **`models`** `{}` → `{pc: Hardware, tier_recommended: light|balanced|best, tier_current: light|balanced|best|custom,
  language_focus: english|multilingual|hindi, models: [Model]}`. `Model` = `{id, feature: text|photo|ocr, name, tier,
  licence, source, size_mb, ram_mb, speed_note, languages: [string], improves, builtin, state:
  not_downloaded|downloading|ready|active|failed, capable, capable_reason, recommended, quality?:
  {english, hindi}|null}`. `quality`: a text model's measured search quality on the English and Hindi test sets
  (nDCG@10 of the whole search, 0-1). `ram_mb` and `speed_note`
  were measured on the reference PC (0 / "" when not measured); `improves`, `licence`, `size_mb`, `source` and
  `ram_mb` are what the consent dialog shows. `recommended`: in the recommended tier for this PC and language focus.
  The `models` event brings the same object whenever it changes.
- **`model_use`** `{feature, id}` → `{ok, error, needs_download: bool}`: choose the model for a feature (and turn the
  feature on). Not downloaded yet: it is chosen, `needs_download` is true, and it's used once downloaded. A new text
  model rebuilds the meaning vectors in the background (`status_full.phases` has `{id: "rebuild"}`); the old vectors
  and their model stay in use until the new ones are complete, then they swap at once. Vectors of two models are
  never searched together.
- **`model_download`** `{id, consent}` → `Ok`: download a model, only with `consent: "DOWNLOAD"` (the consent dialog's
  button; anything else is `ok: false`). Pinned revision, exact size and SHA-256 are checked before a file is used.
  Progress comes as `download` events with `id` = the model id.
- **`model_remove`** `{id}` → `Ok`: delete a downloaded model's files; not for built-in models or the one in use.
- **`auto_configure`** `{}` → `{tier, steps: [{feature, id, needs_download}]}`: apply the recommended tier for this PC
  and language focus. Everything that needs no download is applied at once; for each step with `needs_download`, the
  UI asks for consent and calls `model_download`. A step's `id` is `""` when the tier turns that feature off.
- **`model_language`** `{focus: english|multilingual|hindi}` → `Ok`: "English first", "Many languages" or "Hindi" in
  Settings → Models. It changes the recommendation only; nothing is downloaded or switched by itself. Until it is
  set, the focus comes from Windows' display and keyboard languages (read from Windows, no network).

### Windows Search

- **`wsearch_state`** `{}` → `WsearchState` = `{missing: bool, start: ""|auto|delayed-auto|demand|disabled, running:
  bool, saved: same words}`: how Windows Search indexing is set up (`saved` = how it started before NOBAD Find
  turned it off, `""` if it didn't). Takes about 100 ms.
- **`wsearch_set`** `{off: bool}` → `{ok, error, state: WsearchState}`: Windows Search indexing off, or back as it was.
  Windows shows a permission prompt; the answer comes after it: **no time limit**. While a prompt is open, another
  call answers at once with `ok: false` and a sentence.
- **`use_instead_of_windows_search`** `{on: bool}` → `{ok, error, state: WsearchState}`: the one switch: Windows Search
  off and NOBAD Find starts with Windows (on), or Windows Search back (off). Same prompt.

### What is indexed, and the turbo index

- **`scope_info`** `{}` → `{scope: whole_pc|my_files|custom, roots: [string], categories: [Category]}`: what NOBAD Find
  indexes, for Settings. Nothing is skipped silently: every category is listed. `Category` = `{id, name, why,
  examples: [string], included: bool, locked: bool, count: int|null}`, `id` one of `system` (Windows, Program Files,
  ProgramData: setting `include_system`), `caches` (AppData, temp, node_modules, .git, venv: `include_caches`),
  `secrets` (keys, browser passwords, cookies and history, Windows Credentials/Vault/Protect, chat and developer
  tokens, password vaults, wallets: `include_secrets`, **off by default, names only**, the content is never read;
  browser profiles and app databases are names only in `caches` too), `other_profiles` (other accounts' files, recycle bins, System Volume Information: always out, `locked`),
  `removable` (`index_removable`), `network` (`index_network`). `locked` = the user can't change it here (other
  people's files; system folders aren't part of My files; USB/network in Custom come from the folder list). `count`
  = entries of that category in the index, `null` when it can't be counted cheaply. Show `name`, `why` and
  `examples` as plain text. Change the switches with `set_settings` (`scope`, `include_*`); the engine walks again.
- **`turbo_state`** `{}` → `TurboState` = `{available, enabled, running: bool, volumes: [{drive, ntfs: bool, files:
  int, usn_ok: bool, last_scan: number|null}], error: string}`: the optional turbo index, an elevated helper that
  reads NTFS's own file list and change journal (names, sizes, times and changes only, never file contents).
  `available` = an NTFS fixed drive is there, `enabled` = the `turbo` setting, `running` = the helper is connected,
  `usn_ok` = changes on that drive come from the change journal, `error` = `""` or why it isn't running (the normal
  folder walk is used then).
- **`turbo_set`** `{on: bool}` → `{ok, error, state: TurboState}`: on: Windows shows a permission prompt (once per engine
  run); the answer comes after it: **no time limit**. No at the prompt gives `ok: false` with a sentence and the
  setting stays off. Off: the helper ends. While a prompt is open, another call answers at once with `ok: false`.
  The `turbo` setting is read-only for `set_settings`: only `turbo_set` changes it.

### The window and quitting

These replace the 0.7.0 page's `heartbeat`, `page_visible` and `hide`: the engine knows the UI is alive because the
pipe is open.

- **`ui_shown`** `{window?: "main"|"bar"}` → `{ok: true}`: this UI's window is on screen (default `main`). For the
  main window, indexing starts (the engine starts idle unless "Keep indexing in the background" is on, as the
  0.7.0 app does when started with Windows) or resumes after a close stopped it, and the models warm up. A
  `ui_shown` still queued when its connection's pipe closed changes nothing.
- **`ui_hidden`** `{window?: "main"|"bar"}` → `{ok: true}`: the window was hidden or closed. For the main window
  with "Keep indexing in the background" off, indexing stops and only the engine's one idle process stays (the
  hotkey still works). A UI whose pipe closes after `ui_shown` counts as `ui_hidden`. Another UI still showing its
  main window keeps indexing as it is.
- **`quit`** `{confirm: string}` → `Ok`: end NOBAD Find, only with `confirm: "QUIT"`; any other word gives `ok:
  false`. The `quitting` event goes out before the reply; the engine stops only after the reply is written, and
  both stay readable after the engine closes the pipe.

## Events

Subscribe with `subscribe`. Each is `{"jsonrpc":"2.0","method":"<name>","params":{…}}`.

- **`status`** → `StatusBrief` (as the `status` method), every 2 s.
- **`status_full`** → `Status` (as the `status_full` method), every 2 s. It costs the engine real work: subscribe only
  while the Indexing page is open, `unsubscribe` when it closes.
- **`level`** → `{level, reason, paused}`: the work level, its reason or the pause changed (seen within half a second).
  Not sent for the state at the time you subscribed: read `status` once.
- **`activity`** → `{t, kind: level|kill|model|info, text}`: a new Recent decisions entry (within half a second).
- **`download`** → `{id: meaning|photo|<model id>, state: missing|downloading|ready, got_mb, size_mb, mb_s, error}`: a model
  download moved on: progress up to twice a second while `downloading`, then `ready`, or `missing` with `error` saying
  why it failed.
- **`notice`** → `{text}`: a sentence to show as a toast (for example a hotkey another app took). A notice nobody was
  subscribed to waits (the last 5) and goes to the first connection that subscribes to `notice`.
- **`models`** → the `models` result: something in it changed (a download changed state, a model was chosen,
  removed or became active, the language focus changed). Looked at about once a second.
- **`show`** → `{what: main|bar|settings|index, text: string|null}`: bring that window up (`settings`, `index`: the
  main window on that page, from the tray menu). `text` null: a hotkey was pressed, keep the
  search box as it is; a string: the bar's Alt+Enter (`to_main`), put it in the search box and search. The engine
  has already allowed the UI processes to take the front.
- **`here`** → `{path}`: after the main hotkey, the File Explorer folder it was pressed in (`""` if none). Comes shortly
  after `show`; a newer press wins.
- **`quitting`** → `{}`: the engine is ending. Exit instead of reconnecting.
- **`turbo`** → `TurboState` (as `turbo_state`): the turbo index started, stopped, read a drive, lost a change journal
  (it reads the drive again) or hit an error.

## Transcripts

`transcripts/*.jsonl`, one JSON object per line, in order:

- `{"send": <request>}`: the UI sent this.
- `{"recv": <response or event>}`: the engine sent this.
- `{"engine": {"do": …}}`: something happened inside the engine (a tick of the event clock, a level change, a hotkey,
  a download moving on). The Python replay performs it; a UI test skips it.
- `{"note": "…"}`: a comment.

They are recorded from the real handlers and events over a fake Api with fixed answers (`tests/contract_fake.py`), so
they never depend on a PC. The Python test replays every `send`/`engine` line and checks each `recv` comes out exactly
the same, and checks every line against the schemas (a deliberately bad request must be refused by the schema too).
After a deliberate contract change: `python tests/test_rpc_contract.py --record` (keeps the `send`/`engine`/`note`
lines, rewrites the `recv` lines), then review the diff.

| Transcript | Covers |
|---|---|
| `01-connect-and-search.jsonl` | hello, subscribe, status, ui_shown, search (words, filters only, empty), thumbnail, open, reveal, path_of, a path instead of an id (refused), a filter word that does not exist (refused), an unknown method, status events, ui_hidden |
| `02-events.jsonl` | every event: status, level, activity, download progress/ready/failed, show (hotkeys and to_main), here, a notice waiting for a listener, unsubscribe, quit and quitting |
| `03-settings-and-system.jsonl` | get/set_settings (and a bad one), pick_folder, Windows Search, model downloads with and without consent, rescan, wipe and quit confirm words |
| `04-indexing-page.jsonl` | status_full method and event, pause_for/resume with level events, bad pauses (a string, 0), learned_apps, reset_learned, hardware, forget |
| `05-scope-and-turbo.jsonl` | scope_info before and after a scope change, turbo_state, turbo_set declined at the prompt (and a bad one), turbo events (running, helper ended), turbo_set off |
| `06-models-and-tray.jsonl` | models (method and event), model_language, model_use (and a model for the wrong feature), model_download without and with consent and its download events, model_remove (downloaded, built-in, a bad id), auto_configure, open_with, show settings / index (the tray) |
| `07-smart-search.jsonl` | search with parts and a best guess, suggest (empty, typed, the bar's), history_add (kept, too short, with the setting off), history_forget (kept, never typed), history_clear |
