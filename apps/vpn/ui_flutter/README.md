# NOBAD VPN window (Flutter)

NOBAD VPN 2.0's window and tray pop-up. It runs **as the signed-in user, never elevated**, owns nothing but the
screen, and talks only to the elevated engine over its private pipe `\\.\pipe\NOBADVPN-<user SID>` (JSON-RPC 2.0;
contract in [`../contract/`](../contract/README.md), security in [`../docs/UI-PIPE.md`](../docs/UI-PIPE.md), design
and measurements in [`../docs/FLUTTER-UI.md`](../docs/FLUTTER-UI.md)).

```
flutter test && flutter analyze
flutter build windows --release
build\windows\x64\runner\Release\nobad_vpn_ui.exe          # the main window
build\windows\x64\runner\Release\nobad_vpn_ui.exe --mini   # the tray pop-up
```

On the maintainer's PC: `E:\dev\flutter\bin\flutter`, `PUB_CACHE=E:\dev\pub-cache`.

## Looking at it without the real app

The real engine runs elevated and changes the firewall, so don't start it to look at the window. Instead:

```
python -I tool\demo_engine.py connected        # or: off connecting blocked error empty; --light
flutter build windows --release --dart-define=NOBAD_VPN_DEV=true   # only such a build honours the dev switches
set NOBAD_VPN_DEV_ENGINE=1
build\windows\x64\runner\Release\nobad_vpn_ui.exe
```

`tool/demo_engine.py` runs the **real** pipe server (the same access list, caller check, parameter allowlist and
events) at normal rights on the development pipe name `NOBADVPN-dev-<SID>`, with made-up handlers: no tunnel, no
firewall rule, no elevation, no browser, nothing outside a temp folder. `NOBAD_VPN_FAKE_ENGINE=1` runs the window on
the in-memory `FakeEngine` with no pipe at all.

## Layout

| Folder | What |
|---|---|
| `lib/app/theme/` | Tokens: colours (the WebView's "g11" theme under the glass), type (Arial Black display line, Segoe UI Variable Text, Cascadia Mono SemiBold), spacing (8 px grid), motion (120-240 ms, springs), DWM Mica/Acrylic (`glass.dart`) |
| `lib/widgets/` | Glass, pressable base with focus ring, buttons, switch, select, chips, text box, dialogs, icons, the aperture (connect button), the throughput chart, eased numbers |
| `lib/map/` | The world map: sun and daylight maths, land mask, place guessing (`world.dart`), the camera, clustering and hit-testing (`camera.dart`), the interactive map (`map_view.dart`), the faint backdrop map (`world_map.dart`), where a server goes (`locate.dart`) |
| `lib/engine/` | The only code that knows the engine: `rpc.dart` (sessions, reconnecting), `pipe_client.dart` (dart:ffi named pipe, owner check), `engine.dart` (typed calls), `models.dart`, `fake_engine.dart` |
| `lib/state/` | `VpnController`: state, traffic samples, selection, busy tasks, toasts; fed by engine events only |
| `lib/features/` | Shell (rail, splash, offline), Home, Servers, Settings (categories), the tray pop-up, notices, onboarding (free servers, setup checklist), shared flows |
| `lib/platform/` | Window moves (hide, front, the pop-up next to the tray, starting the other window), Windows' Open dialog |
| `windows/runner/` | Single-instance mutexes (`Local\NOBADVPNUI-main` / `-mini`), the pop-up's frameless window, the main window's designed size and remembered place (`window_geometry.h`) |
| `test/` | Models, controller, RPC, contract transcripts, map maths, widgets for every screen, goldens (dark and light, default, minimum and maximum size) |

## Switches (development only: debug builds, or `--dart-define=NOBAD_VPN_DEV=true`; a normal release build ignores them all)

| Variable | What |
|---|---|
| `NOBAD_VPN_DEV_ENGINE=1` | Talk to `tool/demo_engine.py` on the development pipe |
| `NOBAD_VPN_FAKE_ENGINE=1` | The in-memory FakeEngine (`NOBAD_VPN_FAKE_CONNECTED=1` starts connected) |
| `NOBAD_VPN_UI_TAB=home\|servers\|settings` | The screen the main window opens on |
| `NOBAD_VPN_UI_ALLOW_SECOND=1` | Skip the single-instance check |
| `NOBAD_VPN_SKIA_CACHE_MB`, `NOBAD_VPN_RENDERER=impeller`, `NOBAD_VPN_NO_BLUR=1` | For measuring |

A shared Dart package for what NOBAD Find and NOBAD VPN both use (the pipe client, the RPC session, glass,
pressable, controls, dialogs) is a later step; for now the files were copied from `apps/find/ui_flutter` and adapted.
