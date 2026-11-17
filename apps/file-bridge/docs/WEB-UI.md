# NOBAD File Bridge web UI

The new interface: HTML/CSS/JS in a pywebview window, styled as a sibling of NOBAD VPN with File Bridge's own blue
accent. It's being built screen by screen next to the classic Qt window (`python -m app.main`), which stays the
default until the web UI covers everything.

```bash
python -m app.web             # app window (Edge WebView2 on Windows, GTK/Qt WebKit on Linux)
python -m app.web --browser   # the same UI in your default browser
python -m app.web --db x.db   # use another database (testing)
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
| Ctrl+B | collapse or expand the sidebar |
| ↑ ↓ in the sidebar, ← → in the dock and segmented controls | move |
