# NOBAD VPN: the engine pipe for the Flutter window

NOBAD VPN 2.0 replaces the WebView window (pywebview + WebView2 inside the elevated process, talking to a loopback
HTTP server) with a Flutter window that runs **as the signed-in user, never elevated**, and talks to the elevated
engine over one private named pipe. This document is the pipe's security design; [FLUTTER-UI.md](FLUTTER-UI.md) is
the window itself. The message contract is [`../contract/`](../contract/README.md).

During the move both UIs exist. In an **installed build** only the `ui_flutter` setting picks the window
(Settings → Startup & tray → "Try the new NOBAD VPN 2.0 window (preview)"; it lives in `settings.json` in
ProgramData, which only administrators can change). The environment never decides it there: anything running as the
user can set `HKCU\Environment`. In a **source run** `NOBAD_VPN_UI` also works (`rpc/launch.py ui_mode`):

| mode | Windows | Pipe |
|---|---|---|
| unset or `webview` (**default, unchanged 1.6.x behaviour**) | the WebView windows | not created |
| `flutter` | the Flutter window and tray pop-up; the engine owns no window | created |
| `both` | the WebView windows, plus the pipe for a Flutter window next to them (parity checks) | created |

`flutter` and `both` fall back to `webview` when the Flutter UI isn't installed (`{app}\ui\nobad_vpn_ui.exe`, or the
developer's build). The release switches the default once the Flutter UI has parity (release checklist in the PR).

## Why a pipe, and what it replaces

The WebView ran inside the elevated process, so its JavaScript could only be reached by that process; the HTTP
server authenticated callers with a one-time launch code exchanged for an `HttpOnly` cookie, plus `X-Token` for
NOBAD's own processes, and Host/Origin checks against DNS rebinding (ARCHITECTURE.md 7.1). The Flutter window must
not run elevated (an elevated UI renders untrusted text, e.g. Wi-Fi names, with admin rights), so the engine needs a
door that a normal-rights process can open, and nobody else can.

A named pipe is a better door than a TCP port for that:

- it is not on the network stack at all (no DNS rebinding, no browser can `fetch` it, no proxy, no firewall rule);
- Windows enforces an access list on it, so other accounts on the PC can't even open it (the loopback port was
  reachable by every account, which then had to present the secret);
- the engine can ask Windows **who** is at the other end (a token), instead of trusting a secret.

## The four layers

Each layer stops a class of caller on its own (`nobadvpn/rpc/security.py`, `server.py`, `params.py`).

1. **Access list** (`sddl_for`):
   `D:P(D;;GA;;;NU)(A;;0x12019b;;;<user SID>)(A;;GA;;;SY)(A;;GA;;;BA)S:(ML;;NWNR;;;ME)`
   - protected DACL, nothing inherited;
   - network logons denied;
   - the **interactive user of the engine's session** gets read and write only (`FILE_GENERIC_READ |
     FILE_GENERIC_WRITE` without `FILE_APPEND_DATA`, which on a pipe is `FILE_CREATE_PIPE_INSTANCE`): no new
     instance of the engine's pipe (a rogue server under its name), no `WRITE_DAC`, no `WRITE_OWNER`. All rights only
     for SYSTEM and Administrators. (An unelevated development engine gives the user all rights, because it creates
     its own next instances as that user; tests check the effective rights with `GetEffectiveRightsFromAcl`, and that
     a second instance by the user is refused.) The user is
     found with `WTSQuerySessionInformation` + `LookupAccountName`, not taken from the engine's own token: a
     standard user who typed an administrator's password at the UAC prompt runs the engine as that administrator,
     while the window runs as the standard user;
   - an explicit **Medium mandatory label, no-write-up and no-read-up**: Low-integrity and AppContainer processes (sandboxed browser
     tabs, Store apps) can't open it; the window at Medium can. Without the explicit label an elevated creator could
     leave the pipe labelled High, and the normal-rights window couldn't write to it.
2. **Pipe flags** (`server.py`): `PIPE_REJECT_REMOTE_CLIENTS` (nothing from another machine) and
   `FILE_FLAG_FIRST_PIPE_INSTANCE` on the first instance: if any process already holds the name, the engine refuses
   to serve rather than share it. The next instance is created before a connected one is handed off, so the name is
   never free while the engine runs.
3. **The caller check** (`security.decide`, run on a connection's first bytes, before any request is parsed). Through
   identification-level impersonation (which the window asks for: `SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION`,
   so the engine can inspect but never act as the user) the engine reads the client's token:
   - the account must be the session's user, or SYSTEM;
   - it must be in the engine's own Windows session;
   - not an AppContainer; integrity at least Medium;
   - the account may also be the engine's own (a second launch of NobadVPN.exe or the Start-menu repair, elevated);
   - in an installed build, the client's program file must be `{app}\ui\nobad_vpn_ui.exe` or `NobadVPN.exe`. This
     is a **filter against stray programs, not a security layer**: a program running as the user can start NOBAD's
     own window and drive it (see Residual risk). Source runs skip it.
   - a client must speak within 3 s or it is dropped; at most 8 requests per connection wait for an answer.
   A refused client gets one error (`-32001 "This program may not control NOBAD VPN."`) and is dropped; the engine
   logs the program and the reason.
4. **Every request against an allowlist** (`params.SPEC`): a method that isn't listed doesn't exist on the pipe (the
   WebView-only `window` and `ui_state` aren't); every parameter has a type, a length cap and, where it names
   something, a pattern: server names are config names (`[A-Za-z0-9_=+.-]{1,32}`), files from the free-server guide
   are bare names from the engine's own scan (no separators), links are keys from a fixed list (`proton_signup`,
   `firewall_settings`, ...), repair levels are `undo | quick | full`, settings values are true/false, short text or
   a short list of short names. Unknown parameters are refused. Then the same handler the WebView called runs, with
   every check it already made (`settings.coerce`, `configstore._safe`, `netinfo`, ...). **No parameter is ever a
   path, a URL the elevated side fetches on the window's behalf (only `import_url`, which was already HTTPS-only to
   public hosts), or a command line.** Config files the user picks are read by the window, at the user's rights,
   and only their text is sent (`import`), so the elevated engine never opens a path someone chose.
   **Configs over the pipe are strict** (`confparse.STRICT`, set around every pipe request): `PreUp`, `PostUp`,
   `PreDown`, `PostDown`, `Table` and unknown keys are refused for `import`, `config_save`, `config_validate`,
   `import_url` and `free_import`. WireGuard runs hook commands as SYSTEM when
   `HKLM\Software\WireGuard\DangerousScriptExecution` is set, so a hook saved by a program at the user's rights
   would have been a way to SYSTEM. As defence in depth the runtime copy WireGuard runs never contains a hook line,
   whatever the stored config says (`tuned_conf_text`). This is a change from 1.6: hooks added in the classic
   window's editor no longer run.
   The pipe never sets where NOBAD downloads updates from or sends crash reports (`update_url`,
   `crash_report_url`): it may only clear them; an administrator sets them with `NobadVPN.exe --set-url update|crash
   <https link>`. `import_url` downloads from the one address it checked (all of the host's addresses must be public;
   no second DNS answer is used) and never follows a redirect. Error sentences carry no file paths or OS error codes.

Lines are capped at 1 MiB (a 400 KB pasted config fits); a bigger one is answered with an error, then the client is
dropped. A client that stops reading is dropped after 5 s, so it can't stall the engine. At most 6 connections.
Errors never carry exception text (it could hold a path or a key fragment): the client gets `Internal error`, the
log gets the exception's type.

**The other direction.** The window opens the pipe with `GENERIC_READ | FILE_WRITE_DATA` only, and checks it before
sending anything: its owner must be Administrators or SYSTEM (`pipe_client.dart ownerAllowed`), i.e. it was made by
an elevated process, and in an installed build the serving process must be `{app}\NobadVPN.exe`
(`GetNamedPipeServerProcessId`, `serverAllowed`). Release builds of the window ignore every development switch
(`NOBAD_VPN_FAKE_ENGINE`, `NOBAD_VPN_DEV_ENGINE`, ...): they only exist in debug builds or with
`--dart-define=NOBAD_VPN_DEV=true`, so an environment variable can't make the real window show a fake state. A program running as the user
that grabbed the name first can't pose as the engine and show a false "Protected". The unelevated demo engine used
for screenshots has a different name (`NOBADVPN-dev-<SID>`), owned by the user, so a real window never talks to it.

## Starting the window as the user

The engine never starts the window with its own token. `rpc/launch.py`:

1. When a window connected over the pipe already serves the window wanted, the engine sends it a `show` event and the
   window brings itself up (the tray click, the second launch's hand-off).
2. Otherwise the engine starts `ui\nobad_vpn_ui.exe` (fixed path; the only argument is `--mini` or nothing) with
   `CreateProcessWithTokenW` and a primary copy of the **desktop shell's token** (explorer.exe of the session: the
   signed-in user at Medium integrity).
   The token is refused if it is elevated or above Medium integrity (a shell started elevated, UAC off).
3. If that fails, a one-shot scheduled task with an interactive, limited principal starts it, the route
   `syscmd.open_url_as_user` already takes for links. The engine starts the window at most once every 4 s, whoever
   asks.

The pop-up starts the main window itself (and vice versa) when the engine has none to show; it is already at the
user's rights.

## Residual risk, said plainly

A program that already runs as the signed-in user can drive the window: send it input, inject code into it, start it
under a debugger. It could then do what the window can do: disconnect, turn the kill switch off, delete a config, run
a network repair, quit. The WebView window ran elevated and was out of reach of such programs (UIPI and integrity
levels kept them out), so **this is weaker than 1.6 against malware already running as the user**, and it can't be
avoided by a window that runs at normal rights, as required. It is the same model as other VPN clients whose UI runs
as the user (a user-level UI talking to a privileged service).

What limits it:

- such a program gains nothing it couldn't get without NOBAD: it can already read the user's files, and turning
  protection off doesn't give it admin rights. Nothing the pipe accepts runs code, writes a path or changes an ACL
  with the engine's rights;
- calls that lower protection, change Windows networking or change what the VPN connects to (`disconnect`,
  `panic_reset`, `net_repair`, `quit`, `config_delete`, `ni_fix`, `flush_dns`, `update_install`, `elevate`,
  `import`, `config_save`, `import_url`, `free_import`, `connect`, a protection setting turned off as the engine
  stores it, and any change of `fallback_dns`, `ni_reference_dns`, `ip_lookup`, the update and crash settings) are
  written to the log with the calling program and its PID (`rpc/methods.py _audit`), and when that program isn't
  NOBAD's own window the window shows it ("A server was added by <program>.");
- other accounts on the PC, remote machines, browsers, sandboxed and Low-integrity processes can't reach the engine
  at all (they could reach the old loopback port, if not use it).

## What did not change

The kill switch, the DNS leak block, the fail-safe and recovery paths (watchdog, boot guard, `--panic`,
`--repair-network`, the Start-menu "Restore internet") are untouched: the pipe only calls the handlers the WebView
called. The loopback HTTP server stays for the WebView mode. With the pipe on, the single-instance hand-off (a second
launch asks the running copy to show its window: `ui_show`) and the Start-menu "Restore internet" / "Repair network"
forwarding (`net_repair`) go over the pipe first (`rpc/client.py`, the same owner check as the window) and fall back
to the HTTP `X-Token` route only when the pipe doesn't answer.

## Tests

- `tests/test_rpc.py`: framing, the allowlist (path-like names, shell strings, wrong types, unknown parameters,
  oversized text: all refused before any handler runs), the caller policy, events, the UI launcher (fixed program,
  fixed argument, never elevated), the window mode, and a **real pipe** on Windows at normal rights (round trip,
  events, oversized message, refused caller, the real impersonation check admitting this process, the name never
  shared, concurrent clients).
- `tests/test_rpc_contract.py`: the method schema is the one `params.SPEC` generates; the transcripts replay against
  the real `api.HANDLERS` with a fake tunnel.
- Not covered by automated tests: the pipe created by an **elevated** engine with a Medium client (needs an elevated
  test run on a real PC; listed in the release checklist).
