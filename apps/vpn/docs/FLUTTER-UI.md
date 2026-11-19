# NOBAD VPN 2.0: the Flutter window

The window and tray pop-up are moving from pywebview (WebView2 inside the elevated process) to Flutter, running as
the signed-in user and talking to the elevated engine over a private pipe. The pipe's security design is
[UI-PIPE.md](UI-PIPE.md); the contract is [`../contract/`](../contract/README.md); the code is
[`../ui_flutter/`](../ui_flutter/README.md). NOBAD Find made the same move first (`apps/find/ROADMAP.md`,
`apps/find/docs/STRUCTURE.md`); its pipe server, pipe client, RPC session, glass, pressable, controls and dialogs were
copied and adapted. **A shared Dart package for those (and a shared Python `rpc` core) is a later step**, once both
apps have shipped on them and the differences have settled (the VPN's engine is elevated and checks its caller; Find's
runs as the user).

## Status

| Part | State |
|---|---|
| 1. Engine pipe and contract | **Done**: `nobadvpn/rpc/` (server, caller check, access list, parameter allowlist for every method, events, UI launcher), `contract/`, tests against a real pipe |
| 2. Main window: connect, status, servers, free-server guide | **Done**: Home (status, aperture, measured facts, protection chips, notices, throughput, the map, servers), Servers (search, sort, favourites, import files/URL/paste, editor, probe, rescan, folder), free-server guide (the onboarding when there are no servers), setup checklist, splash, offline/refused/update-needed states |
| 3. Tray pop-up | **Done**: frosted (Acrylic) pane next to the tray, everything the old one had, hides on focus loss and Esc, says when NOBAD isn't running |
| 4. Settings and the remaining screens | **Settings done** (every WebView setting, the same words, categories with icons, search, trusted networks, updates, network safety, crash reports, appearance, log). **Not yet ported:** the Network page (network health check, DNS cache, VALORANT and custom game checks, launch diagnostics), Network Intelligence, Streaming Region Intelligence, the Evil Twin report, usage history and session list, the speed test and service checks, QR-image import, drag and drop, the command palette. The engine side of all of them is already on the pipe (`params.SPEC`). |

Until part 4 is complete the WebView stays the default (`NOBAD_VPN_UI` unset); `NOBAD_VPN_UI=flutter` selects the
Flutter window, `both` runs both side by side for comparing.

## Design

- **Look:** frosted spatial glass over Windows' own Mica (main window) and Acrylic (pop-up). Panels are the old
  WebView theme's surface (`#111319` dark / white light, from `nobadvpn/ui/index.html` "g11" and `design.css`) at
  76-80 % with a 1 px white (black) 8 % edge; real blur only in dialogs (Find measured 40-135 MB for blur behind
  content). The NOBAD orange (`#F65000`, `#C94100` light) is the only accent: the live element, buttons, selection.
  Three state colours from the old theme, used only for state: sealed `#3BD69B`, connecting `#FF9A7C`, blocked
  `#FF5268`.
- **Type:** Arial Black upper case for the one display line per screen (PROTECTED, SERVERS, SETTINGS), at most 24 px;
  Segoe UI Variable Text, 400 for secondary text and 600 for titles, labels and values; Cascadia Mono SemiBold for
  numbers and addresses. Scale 12/13/14/16/20/24. Icons: Windows 11's own Segoe Fluent Icons at 16 px (nothing
  bundled; Segoe MDL2 Assets on Windows 10).
- **Density:** desktop-tool compact, an 8 px grid with a 12 px gutter everywhere, rows 44-52 px, radius 8 (controls,
  rows) and 10 (panels). Nothing is stretched to fill: Home is one grid (left column: status, notices, throughput;
  right: the map over the servers; the bottom panels share a height so the edges line up).
- **Hero:** the aperture. The connect button is a ring: open with a gap when not protected, a spring closes it while
  connecting (a pulse breathes out of it), sealed green when protected, sealed red with a bar when the kill switch
  blocks. Next to it, the state as one Arial Black line.
- **The map:** a live, interactive world map in its own panel. Land is a vector dot field (crisp at any zoom), lit as
  the world is now (day, the night side as a vector veil, the twilight band on the terminator; the sun's position is
  the WebView's formula, ported and tested). Every server is a pin, placed from its endpoint by the engine's offline
  country database (no lookup online unless "IP lookup" is on), else from its name; one that can't be placed says
  "location unknown" in the list instead of a wrong pin. Close pins cluster. Hover shows a frosted tooltip (name,
  place, endpoint, last ping, Connect); a click selects (the list and the aperture follow, and the reverse: picking a
  server in the list eases the map to it); a double-click connects. Wheel/pinch zoom, drag to pan, Fit all. When
  connected: the arc from this PC to the server draws in, a light travels along it and the server's pin pulses. A chip
  says "Connected · Tokyo, JP · 61 ms".
- **Motion** (120-240 ms, springs where something is placed): the aperture morphs and pulses, the arc draws, the rail
  and settings indicators slide (a Fluent pill), pages crossfade with a slight slide, rows and buttons lift with an
  orange edge glow on hover, toggles spring, toasts slide in, the chart's line draws each new sample, counters ease.
  Everything stops when the window is hidden or minimized (TickerMode), and with Windows' "Animation effects" off
  nothing moves.
- **Window:** a designed size, not a full screen: 1180 x 760 by default, 960 x 640 to 1440 x 900, no maximize; the
  last size and place are remembered per user and brought back on a monitor that is still there.

## Measurements

- **PC:** Intel Core i5-12500H (16 threads), 15.7 GB RAM, Intel Iris Xe, Windows 11 Home 26300. Flutter 3.50, release
  build, Skia, Skia cache 12 MB.
- **How:** each window on a separate, invisible desktop (`CreateDesktop`, so nothing appeared on the user's screen),
  20-25 s to settle, then 30 s idle; working set and private bytes summed over the process tree (psutil). The WebView
  row is today's UI (`nobadvpn/ui`, served by `docs/ai/tools/ui_preview_mock.py`) in a pywebview window at the same
  size, i.e. the same WebView2 window the app opens, without the engine. The Flutter rows talk to
  `ui_flutter/tool/demo_engine.py` (the real pipe server, fake handlers).

| Window | Working set | Private | Processes | CPU, idle |
|---|---|---|---|---|
| **1.6 WebView window**, Servers tab, not connected | **719 MB** (WebView2 624 MB + python/pywebview 95 MB) | **470 MB** (411 + 59) | 7 | 0.2 % |
| 1.6 WebView window, connected | 777 MB | 517 MB | 7 | 0.3 % |
| **2.0 Flutter main window**, Home, not connected | **160 MB** | **152 MB** | 1 | 0.0 % |
| 2.0 Flutter main window, Home, connected | 163 MB | 145 MB | 1 | 0.0 % * |
| 2.0 tray pop-up, hidden after losing focus | 19 MB | 112 MB | 1 | 0.3 % |

The Flutter window uses about a fifth of the WebView window's memory (working set 160 vs 719 MB; private 152 vs
470 MB) and one process instead of seven. About 100 MB of the Flutter number is the GPU driver loaded in-process
(NOBAD Find measured the same on this PC). Not counted for either: the engine itself (the WebView's pywebview row is
only the window's share of the python process).

\* On an invisible desktop Windows doesn't composite the window, so Flutter draws nothing there: the CPU column is
idle CPU with no frames. While connected and visible, the arc's light and the pin's pulse draw frames (the only
continuous animation); not measured on screen because the maintainer was using the PC. To re-measure on screen:
start the demo engine and the window, leave it on Home, and sample `Get-Process nobad_vpn_ui` for 30 s.

## Before the release (also in the PR)

See the release checklist in the pull request. In short: finish part 4, wire `make_geoip.py`, the Flutter build and
the `ui\` folder into `packaging/build.ps1`, `nobad.spec` and `installer.iss`, test the pipe from an **elevated**
engine on a real PC (including the standard-user-plus-admin-password case), then switch the default to `flutter`.
