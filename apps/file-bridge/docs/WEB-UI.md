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
