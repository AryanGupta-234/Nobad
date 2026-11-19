# NOBAD VPN: the engine pipe for the Flutter window

NOBAD VPN 2.0 replaces the WebView window (pywebview + WebView2 inside the elevated process, talking to a loopback
HTTP server) with a Flutter window that runs **as the signed-in user, never elevated**, and talks to the elevated
engine over one private named pipe. This document is the pipe's security design; [FLUTTER-UI.md](FLUTTER-UI.md) is
the window itself. The message contract is [`../contract/`](../contract/README.md).

During the move both UIs exist. `NOBAD_VPN_UI` picks one at start (`rpc/launch.py ui_mode`):

| `NOBAD_VPN_UI` | Windows | Pipe |
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
   `D:P(D;;GA;;;NU)(A;;GA;;;<user SID>)(A;;GA;;;SY)(A;;GA;;;BA)S:(ML;;NW;;;ME)`
   - protected DACL, nothing inherited;
   - network logons denied;
   - full access for the **interactive user of the engine's session**, SYSTEM and Administrators only. The user is
     found with `WTSQuerySessionInformation` + `LookupAccountName`, not taken from the engine's own token: a
     standard user who typed an administrator's password at the UAC prompt runs the engine as that administrator,
     while the window runs as the standard user;
   - an explicit **Medium mandatory label, no-write-up**: Low-integrity and AppContainer processes (sandboxed browser
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
   - in an installed build, the client's program file must be `{app}\ui\nobad_vpn_ui.exe` or `NobadVPN.exe` itself,
     both in Program Files, which only administrators can change. (Source runs skip this: the build folder is the
     developer's own, so pinning it would prove nothing.)
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

Lines are capped at 1 MiB (a 400 KB pasted config fits); a bigger one is answered with an error, then the client is
dropped. A client that stops reading is dropped after 5 s, so it can't stall the engine. At most 6 connections.
Errors never carry exception text (it could hold a path or a key fragment): the client gets `Internal error`, the
log gets the exception's type.

**The other direction.** The window checks the pipe before sending anything: its owner must be Administrators or
SYSTEM (`pipe_client.dart ownerAllowed`), i.e. it was made by an elevated process. A program running as the user
that grabbed the name first can't pose as the engine and show a false "Protected". The unelevated demo engine used
for screenshots has a different name (`NOBADVPN-dev-<SID>`), owned by the user, so a real window never talks to it.

## Starting the window as the user

The engine never starts the window with its own token. `rpc/launch.py`:

1. When a window connected over the pipe already serves the window wanted, the engine sends it a `show` event and the
   window brings itself up (the tray click, the second launch's hand-off).
2. Otherwise the engine starts `ui\nobad_vpn_ui.exe` (fixed path; the only argument is `--mini` or nothing) with
   `CreateProcessWithTokenW` and a primary copy of the **desktop shell's token** (explorer.exe of the session: the
   signed-in user at Medium integrity).
3. If that fails, a one-shot scheduled task with an interactive, limited principal starts it, the route
   `syscmd.open_url_as_user` already takes for links.

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
- calls that lower protection or change Windows networking (`disconnect`, `panic_reset`, `net_repair`, `quit`,
  `config_delete`, `ni_fix`, `flush_dns`, `update_install`, `elevate`, and any protection setting turned off) are
  written to the log with the calling program and its PID (`rpc/methods.py _audit`);
- other accounts on the PC, remote machines, browsers, sandboxed and Low-integrity processes can't reach the engine
  at all (they could reach the old loopback port, if not use it).

## What did not change

The kill switch, the DNS leak block, the fail-safe and recovery paths (watchdog, boot guard, `--panic`,
`--repair-network`, the Start-menu "Restore internet") are untouched: the pipe only calls the handlers the WebView
called. The loopback HTTP server stays for now: the WebView mode uses it, and the single-instance hand-off and the
CLI repair forwarding still use its `X-Token` route (moving those to the pipe is listed in FLUTTER-UI.md).

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
