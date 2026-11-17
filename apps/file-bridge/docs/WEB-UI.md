# NOBAD File Bridge web UI

File Bridge's interface: HTML/CSS/JS in a pywebview window, styled as a sibling of NOBAD VPN with File Bridge's own
blue accent. It is the app's window (`nobad-file-bridge`, `python -m app.main`). The previous Qt window was removed
in stage 7b; the stage notes below mention it where they describe what was ported from it.

```bash
python -m app.main            # app window (Edge WebView2 on Windows, GTK/Qt WebKit on Linux)
python -m app.main --browser  # the same UI in your default browser
python -m app.main --db x.db  # use another database (testing)
python -I scripts/ui_screenshots.py <folder> [screen ...]   # headless-Edge screenshots, temporary database
```

## How it fits together

```
pywebview window ──GET /?k=<code>──▶ app_web/server.py (127.0.0.1, random port)
      │   (code swapped for an HttpOnly, SameSite=Strict cookie)
      ├─ POST /api/<name> ──▶ app_web/api.py ──▶ app_web/handlers/<screen>.py ──▶ existing backend services
      └─ GET /events (SSE) ◀── app_web/bus.py ◀── handlers, tasks.run_task, backend events
```

* **Server** (`app_web/server.py`): the NOBAD VPN model. One-time launch code, session cookie, Host/Origin checks,
  CSP `script-src 'self'` (no inline scripts or `on*=` handlers anywhere), static files from an allow-list.
* **API** (`app_web/api.py`): `@handler("screen.action")` functions take `(body, ctx)` and return
  `{ok, error?, data?}`. Use `from_result()` to turn an `OperationResult` into a reply. Messages are scrubbed.
* **Long work** (`app_web/tasks.py`): `run_task(key, coro)` returns at once; the work reports through its own
  events and always ends with `task_done {key, error}`. In the page, `NB.task(key, button, "Working…")` marks the
  button busy until then.
* **Events** (`app_web/bus.py`): `broadcast(kind, payload)`, `log(message, level, source)`. High-rate streams
  (transfer progress, terminal output) go through a `Coalescer` (one event per key every 50 ms).
* **Settings** (`app_web/settings_store.py`): declared once in `FIELDS`; validated by `coerce`; stored in the same
  rows the Qt UI uses. The Settings screen draws itself from `settings.schema`. Only list settings that really
  change something.

## NOBAD title bar

On Windows the window is frameless and the header is the title bar, exactly as in NOBAD VPN
(`apps/vpn/nobadvpn/window.py`, `ui/app_ext.js` `titlebar()`):

* `app_web/window.py` `WindowController.action()` backs `POST /api/window.action`: `minimize`, `maximize` (toggle,
  keeps the taskbar visible), `close`, `drag` (`WM_NCLBUTTONDOWN` on the caption: Windows' own move loop, so
  snapping works), `resize` with an edge `l r t b tl tr bl br` (`WM_SYSCOMMAND SC_SIZE`), and `state`.
* After the window appears it gets `WS_MINIMIZEBOX | WS_SYSMENU`, so its taskbar button minimises it and Win+Down
  works. Size and position are remembered (`web_ui.window` row) and clamped back on screen.
* pywebview opens a frameless window 16×39 px smaller than asked; the controller measures that once and adds it
  back when saving, so the window doesn't shrink on every start.
* `ui/titlebar.js` adds the 46 px window buttons (close turns `#c42b1c`), drag and double-click on empty header
  space, invisible resize edges, and a 150 ms fade before minimise/close.
* Setting **NOBAD title bar** (`web_ui.custom_titlebar`, on by default) turns it off: the system title bar
  (dark caption) is used from the next start. Linux and macOS always use the system title bar.

## Motion

Ported from NOBAD VPN (`index.html`, `design.css`, `app_ext.css`, `app.js`), in `ui/motion.css` and `ui/motion.js`:

| Effect | VPN original |
|---|---|
| Hover glow that follows the pointer on buttons (`--bx/--by`), spotlight on cards (`--mx/--my`) | `ptrFrame` + radial gradients |
| Ripple from the press point | `.rip` / `@keyframes rip` |
| Screens rise in, children staggered 40 ms | `nxTab`, `nxRise`, `nth-child` delays |
| A lens that slides between the active rail item and between dock tabs | `#dockLens` / `lens()` |
| Banners slide in, a row flashes when the palette jumps to it, running pulse | `nxBarIn`, `nxFlash`, `nb-pulse` |
| Connected status pill: blinking dot and a shimmer | `.pill.on` `blink` + `shimmer` |
| A light drifting along the dock's top edge | `#deck:before` `deckline` |
| **Visual effects** setting (off by default): ambient glow and frosted header, dock and dialogs | `body.fx` + `drift1/2` |

Rules: animate transform and opacity only; one pointer update per frame; nothing ambient unless Visual effects is
on; every animation stops under `prefers-reduced-motion`. VPN's map, comet and connect-button effects stay VPN's.

## Connections, Files and transfers (stage 3)

* `app_web/session.py` (`SessionService`): one active connection, saved profiles (shared with the classic window;
  secrets stay in the OS keyring) and the host-key flow. An untrusted key stops the connection and sends a
  `hostkey` event with a one-time token (also included in `conn.state`, so a reloaded page still asks); only
  `conn.trust {token, accept: true}` trusts it and reconnects. A changed key shows a red warning with Cancel as the
  default action.
* `app_web/files.py`: compact listings (`[name, kind, size, mtime, perms]`) for fast large folders; local folders
  are listed on the request thread so a busy server can't slow the local pane; typed names must be one plain path
  component (and valid on Windows); listing errors include the server's own reason.
* `app_web/transfers.py` (`TransferService`): `xfer.plan` finds conflicts first, the page asks once
  (Keep both / Skip / Replace for the whole batch), `xfer.start` queues with that choice (otherwise "ask", which
  fails safely). Queueing runs on the asyncio thread; job updates reach the page at most every 100 ms per job.
* Page: `screens/files.js` (dual pane, `vlist.js` virtual list, keyboard map below, drag between panes, context
  menu, splitter), `screens/connections.js` (saved servers, new connection form, paste an ssh command),
  `session.js` (status pill, host-key dialog, password prompts), `transfers.js` (dock queue, overall progress).
* Deep links: `#/connections?new=1` opens the form, `#/files?dock=transfers|activity` opens the dock.
* Tests: `tests/test_web_e2e_sftp.py` runs a real AsyncSSH SFTP server on 127.0.0.1 (chrooted to a temp folder):
  host-key prompt and trust, connect, browse, mkdir/rename/delete, upload, conflict "keep both", folder
  download, disconnect, wrong password, declined key, reload during a prompt.

## Terminal (stage 4a)

* `app_web/terminals.py` (`TerminalService`): tabs for the connected server (`SSHTerminalSession`) and this
  computer (`LocalPtyTerminalSession`: ConPTY on Windows, PTY elsewhere), up to 12. Output callbacks can fire on any
  thread; `OutputBuffer` appends chunks and sends one `term.out` per terminal every 16 ms (capped at 2 MB pending).
  Each terminal keeps its last 256 KB so a reloaded window redraws it (`term.history`). The server's tabs close
  with its connection (`SessionService.on_closed`). Output is never logged.
* `screens/terminal.js`: xterm.js (vendored in `ui/vendor/xterm/`) with the theme taken from the tokens; keys go
  to the terminal while it has focus (app shortcuts like Ctrl+K are skipped there); keystrokes are sent in order,
  one request at a time; Ctrl+Shift+C / Ctrl+Shift+V copy and paste; tabs survive switching screens.
  "Open terminal here" in the Files context menu opens one in that folder.
* Tests: `tests/test_web_terminal.py` (a real SSH shell on an AsyncSSH server: echo, resize seen by the server,
  history, tabs closing on disconnect; a real local shell; input limits; output ordering and cap).

## Editor (stage 4b)

* `app_web/editor.py` (`EditorService`): tabs for server files (`RemoteEditManager`: private temp workspace,
  backup before saving, and **saving is refused when the file changed on the server after it was opened**) and
  local files (same 5 MB / binary limits, atomic write, same check with the file's modification time). Server tabs
  stay open across a disconnect, so no edits are lost; saving needs that server again. Edited text is never logged.
* `screens/editor.js`: Monaco, **bundled** (`resources/editor/vendor/monaco/`, shared with the classic window and
  served at `/static/vendor/monaco/`; no CDN, issue #30), NOBAD dark/light themes, tabs with an unsaved-changes dot,
  Ctrl+S, and on a conflict: Compare (side-by-side diff: current version left, yours right), Overwrite with mine,
  or Reload theirs. Monaco loads only when a file is first opened. Enter or double-click on a file in Files opens it.
* CSP: Monaco embeds its icon font as `data:` and starts its workers from a `blob:` that loads the same-origin worker
  file, so the page allows `font-src 'self' data:` and `worker-src 'self' blob:`. `script-src` stays `'self'`.
* Tests: `tests/test_web_editor.py` (server open/save/conflict/overwrite/compare/reload against a real SFTP
  server, tabs surviving a disconnect, local atomic save and conflict, binary refusal, no CDN in any editor page,
  every Monaco worker file present, CSP).

## Credential vault (stage 5a)

* `app_web/vault.py` (`VaultFacade`) on `CredentialVaultService` (Argon2id, AES-256-GCM per value, audit log).
  Lists and details carry metadata only; a value reaches the page only for an explicit Reveal or Copy
  (`vault.reveal`), and the service records each one in the audit log. Editing keeps the stored secret, notes and
  custom fields unless new ones are typed.
* Auto-lock after `vault.auto_lock_minutes` (Settings, default 10, 0 = off; the key only lives in memory). After 3
  wrong master passwords each try waits 2, 4, 8 … s (max 5 min). Master password: at least 12 characters.
  `vault.generate` makes strong passwords with `secrets`. Nothing logs a value or a master password.
* `screens/vault.js`: create/unlock card (strength meter, "no recovery" warning), projects / credentials / details
  columns, Reveal hides again after 30 s, Copy clears the clipboard after 30 s if the secret is still on it, edit
  form with a generator. The page re-locks when the app locks the vault.
* Tests: `tests/test_web_vault.py`.

## Sync folders (stage 5b)

* `app_web/sync.py` (`SyncService`) on the existing `SyncPlanner`, `SyncConflictResolver`, `SyncExecutor` and
  `SyncBaselineService`; this replaces the logic that lived in `ui/sync_panel.py` for the new interface.
* **Preview first.** `sync.preview` lists both folders and plans every file, changing nothing:
  * the local folder is walked without following links
  * the server folder is listed folder by folder, joining only plain names (`is_unsafe_entry_name`)
  * skip names prune whole folders
  * both listings stop at 200,000 files
  * two-way conflicts with equal sizes are compared by SHA-256 first
  The result is kept under a one-time token for 15 minutes; rows come from `sync.entries`.
* **Two-way and baselines.** A saved two-way job compares against the baseline saved after its last successful run,
  so a change or deletion on one side crosses over. A baseline only counts for the same local folder, server folder
  and server it was taken for. A new baseline is read back from both sides after a run, never assumed.
* **Conflicts.**
  * Every conflict needs a choice: keep mine, keep the server's, keep both, or skip.
  * Choices a file can't support are refused, such as "keep mine" for a file deleted here.
  * `sync.compare` shows text files up to 2 MB side by side (`NB.diffModal`, read-only Monaco).
* **Run.**
  * `sync.run` refuses to replace or delete files without `confirmed`. Whether a file is replaced is decided from the
    listings, not from sizes.
  * The plan is built again first. If anything changed since the preview, nothing runs and the page gets the new
    preview.
  * Copies go through the transfer queue (shown in the Transfers dock). Deletes happen only after every copy
    finished.
* Not in the new interface yet: the rsync engine (jobs saved with it run through the transfer queue).
* Tests: `tests/test_web_sync.py` (real AsyncSSH SFTP server).

## Deployments (stage 5c)

* `app_web/deploy.py` (`DeployService`) runs on the existing `DeploymentPlanner`, `DeploymentExecutor`,
  `DeploymentHistoryService` and `ManualRollbackService`. Jobs are stored in the same table the classic window uses.
* **Preview.**
  * The optional local build runs first, and its output streams as `deploy.output`.
  * The planner then lists what is added, replaced and (in mirror mode) deleted. Nothing on the server changes.
  * The result is kept under a one-time token for 15 minutes, tied to the connection.
* **Deploy.**
  * `deploy.run` needs `confirmed` and saves the job first, because history and backups belong to a saved job.
  * The executor locks the target and builds the preview again under the lock; if the plan changed, nothing runs.
  * It then backs up, uploads (through the transfer queue), runs the job's commands and health checks, and rolls back
    automatically when a step fails.
  * Each stage is sent as `deploy.stage` and lights up the pipeline. A stale lock (older than 2 hours) is removed
    only if the user confirms.
* **History.** `deploy.history` and `deploy.stages` show every run and its stages with output excerpts.
  `deploy.scan` imports backups and releases found on the server. `deploy.rollback` restores one under the lock,
  after confirmation, and records the run.
* Deployments need a connection that can run commands (SSH). FTP connections are refused with a plain message.
* Tests are in `tests/test_web_deploy.py`.
  * End to end, against a real AsyncSSH server whose commands run in a real POSIX shell: deploy with backup and
    history, automatic rollback after a failed health check, manual rollback, and "changed after the preview". These
    run on Linux.
  * Validation and refusals run everywhere.

## Server health and Services (stage 6a)

* `app_web/server_tools.py` contains `HealthService` and `ServicesService`, built on `core.health_monitor` and
  `core.services_manager`.
* **Health sampling.**
  * Each sample is one batch command (`/proc`, `df`, `ps`).
  * Sampling runs only while the screen asks for it: `health.watch` must be renewed at least every 30 s (the page
    renews every 10 s). It stops on leave, when renewals stop, and when the connection changes.
  * Samples arrive as `health.sample`. The screen redraws inside one persistent frame, so the entrance animation
    plays only once.
  * Charts are single-series sparklines with a crosshair readout. Meters show the status colour with a written level.
* **Stopping a process** checks kill's exit status.
* **Services.**
  * Unit names always go through `validate_unit_name` before any command.
  * Actions use `sudo -n` unless the login is root, so a server that wants a sudo password says so at once.
  * Logs are read without sudo first, and with `sudo -n` only when the journal refuses.
  * Stopping or restarting SSH warns first.
* **Core fix, which also helps the classic window.** `core/remote_command.py`: `run_command` reports that a command
  *ran*, and its exit status says whether it *worked*. `control_service`, `daemon_reload`, `install_unit_file` and
  `kill_remote_process` used to call a failed command a success. They now check the exit status, show sudo's or
  systemctl's own reason, and use `sudo -n`, so sudo can't wait forever for a password on a channel nobody types into.
* Tests: `tests/test_web_server_tools.py`.

## Tunnels and Live logs (stage 6b)

* `app_web/tunnels_logs.py` contains `TunnelService` and `LogsService`, built on `core.tunnel_manager` and
  `core.log_streamer`.
* **Tunnels.**
  * Saved in one settings row, each with its server. They open on the current SSH connection and all close when it
    closes.
  * A local or SOCKS forward listens on loopback unless "Let other devices on my network use it" is ticked. (A SOCKS
    proxy on 0.0.0.0 lets anyone on the network browse through your server.)
  * A reverse forward listens on the server's loopback unless public access is ticked.
  * Port collisions are refused with a suggested free port. Each tunnel shows the matching `ssh` command.
* **Live logs.**
  * Logs are followed with `tail -F` or `journalctl -f`, using `sudo -n` when asked.
  * Lines are batched every 100 ms into `logs.lines`. A batch holds at most 500 lines; the rest are counted as skipped
    and kept in the 10,000-line buffer for `logs.tail`.
  * At most 8 logs at once. A log that ends by itself reports why (core fix: the process's stderr is read).
* **Disconnect cleanup** runs on the asyncio loop itself (a new connection replacing the old one), so it hands the
  work to the loop instead of waiting for it.
* **Server fix.** `BridgeServer.request_queue_size = 128`. A page load opens a connection per file at once, and with
  the default backlog of 5 a busy server (live logs) refused some on Windows: after a reload, a random script was
  missing. The test `test_a_burst_of_page_requests_is_never_refused` covers it.
* Tests: `tests/test_web_tunnels_logs.py`, against a real AsyncSSH server: traffic through a real forward, logs over
  real exec channels.

## Playbooks (stage 6c)

* `app_web/playbooks.py` (`PlaybookService`) runs on `core.playbooks_manager`: the bundled recipes, custom
  snippets and the PTY runner.
* **Values are checked before anything is rendered** (core fix, the classic window too). `interpolate_template`
  pastes values into the shell script as they are, and its docstring wrongly said it sanitized them. A domain like
  `example.com; rm -rf ~` would have run. `check_variable_values` now checks every value by its type:
  * booleans, numbers and choices must match their type
  * free text may only hold letters, digits, spaces and `. , _ - / : @ + =`
  * a value used only inside single quotes may hold anything but `'` and line breaks, which keeps regexes like
    `nginx|node` working
  * undeclared keys are dropped
* **Sudo, chosen per run:**
  * Type the password. It is answered only to the app's own random prompt, once, and masked in the output (#32).
  * Or run without one, which turns every `sudo` in the script into `sudo -n` with a shell function.
  * The password is never stored or logged.
* **Review:** sudo and destructive playbooks show the exact script first. Destructive ones need `confirmed`.
* **Running:** output streams into a read-only xterm (`pb.out`), one run at a time with Stop. The history keeps the
  last 2,000 characters of each run.
* **Custom snippets:** their variables are found from `{{NAME}}` and `{{#if NAME}}`. Bundled recipes are read-only
  ("Save a copy").
* Tests are in `tests/test_web_playbooks.py`, against a real AsyncSSH server with PTY exec channels.

## Fixes after the screens (Files, Terminal, Linux)

* **Files, double-click.** Every mousedown redraws the virtual rows, so the two clicks of a double-click hit
  different elements and the browser never fired `dblclick`. The double-click is now read from the click count on
  mousedown (`e.detail === 2`).
* **Files, other drives.**
  * A "Drives and places" button on the local pane lists drives with Explorer-style labels ("Data (D:)", "USB drive
    (E:)"). Elsewhere it lists `/` and the disks mounted under `/media`, `/run/media` and `/mnt` (and `/Volumes` on
    macOS), plus Home, Desktop, Documents and Downloads.
  * Clicking the empty part of the path bar, or Ctrl+L, lets you type or paste any path, on both panes.
* **Terminal scrollbar.** xterm's text area covered the scrollbar, so the bar couldn't be grabbed. The fit addon
  takes the parent's computed width, which includes the parent's padding under border-box, but subtracts only the
  padding of `.xterm`. All spacing now lives on `.xterm`, with room on the right, and the scroll viewport still
  reaches the edge.
* **Scrollbars everywhere.** They are thin (8 to 10 px to grab), rounded and themed (`--sb`, `--sb-hover`, accent
  while dragging) through `::-webkit-scrollbar`, which WebView2 and WebKitGTK both use.
* **Linux.**
  * `window.linux_gui()` picks GTK/WebKit2GTK when available. Otherwise it uses Qt WebEngine through the bundled
    PySide6 (`QT_API=pyside6`, `qtpy` added for Linux only). If neither is there, the error names the packages to
    install.
  * Linux keeps its system title bar, and the Windows-only "NOBAD title bar" setting is hidden there.
  * The font stacks gained common Linux fonts.

## Page structure (`app_web/ui/`)

| File | What |
|---|---|
| `tokens.css` | colours, radii, spacing, fonts, dark and light (`:root[data-theme="light"]`) |
| `components.css` | buttons, inputs, segmented control, cards, chips, banners, empty states, toast, modal |
| `shell.css` | header, rail, content, dock, palette, settings page |
| `theme.js` | sets the theme before first paint |
| `core.js` | `NB.$`, `NB.esc`, `NB.api`, `NB.on/emit`, `NB.task`, `NB.toast`, `NB.modal`, theme, `NB.uiState` |
| `shell.js` | screen list (`NB.SCREENS`), rail, routing (`#/screen`), dock, keyboard, start-up |
| `palette.js` | Ctrl+K: screens, actions, settings |
| `motion.css`, `motion.js` | hover glow, ripple, screen entrance, sliding lens, flash, status motion, Visual effects |
| `titlebar.js` | NOBAD title bar: window buttons, drag, double-click, resize edges, fade |
| `screens/*.js` | one file per screen: `NB.screens.<id> = {ready: true, render(el, screen, opts), leave?()}` |

## Rules for new screens

* **Untrusted text** (server names, paths, file contents, errors) goes through `NB.esc()` before `innerHTML`, or
  is set with `textContent`. Remote servers are untrusted (see `../AGENTS.md`).
* **Tokens only**: no raw colours in screen CSS; use `--acc`, `--ok`, `--busy`, `--warn`, `--bad` and the surface
  and text tokens. Remote panes use the accent tint (`--remote-tint`, `--acc-line`) so they never look local.
* **Spacing** on the 4/8 px rhythm; hit targets at least 32 px; `tabular-nums` for sizes, times and speeds.
* **Keyboard**: everything reachable with Tab; arrows inside lists and groups; `:focus-visible` ring from
  `components.css`; dialogs via `NB.modal` (focus trap, Esc, focus return).
* **Motion**: transform/opacity only, and nothing that ignores `prefers-reduced-motion`.
* **Copy**: plain, second person, sentence case, a status then the next step. Never claim more than the code
  measures. Loading text ends with "…".
* Check new screens with `scripts/ui_screenshots.py` in dark and light at 1280×820 and 1060×700.

## Keyboard

| Keys | Action |
|---|---|
| Ctrl+K | command palette |
| Ctrl+1 … Ctrl+7 | Files, Connections, Terminal, Editor, Sync jobs, Deployments, Credential vault |
| Ctrl+, | Settings |
| Ctrl+J | show or hide the dock |
| In a file pane: ↑ ↓ Home End PgUp PgDn, Shift/Ctrl to select, Space toggle, Ctrl+A | move and select |
| Enter / Backspace or Alt+↑ | open / up one folder |
| F5 · F2 · F7 · Delete | copy to the other pane · rename · new folder · delete |
| Ctrl+R · type letters | refresh · jump to a name |
| Ctrl+B | collapse or expand the sidebar |
| ↑ ↓ in the sidebar, ← → in the dock and segmented controls | move |
