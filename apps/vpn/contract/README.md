# NOBAD VPN: the window ⇄ engine contract

The only thing the Flutter window (`../ui_flutter`) and the elevated engine (`../nobadvpn`) know about each other.
If code and this folder disagree, tests fail: `tests/test_rpc_contract.py` (Python) and
`ui_flutter/test/contract/transcripts_test.dart` (Dart) replay the same transcripts. The security design is
[`../docs/UI-PIPE.md`](../docs/UI-PIPE.md).

| File | What it is |
|---|---|
| [`methods.schema.json`](methods.schema.json) | Every method and its `params` (JSON Schema). **Generated** from `nobadvpn/rpc/params.py SPEC`: `python -m nobadvpn.rpc.params > contract/methods.schema.json` |
| [`events.schema.json`](events.schema.json) | The events the window reads, and the `State` snapshot |
| [`transcripts/*.jsonl`](transcripts) | Recorded sessions: `send` (window → engine), `recv` (engine → window), `engine` (a broadcast inside the engine). Re-record after a deliberate change: `python tests/test_rpc_contract.py --record` |

Protocol version **1** (`"protocol"` in both schemas and in `hello`). Version 1 only grows; a change that breaks an
older window raises it, and the window then says "Update needed" instead of guessing.

## The connection

- Pipe `\\.\pipe\NOBADVPN-<SID of the session's user>`, made by the elevated engine. The window checks the pipe's
  owner is Administrators or SYSTEM before sending anything. The development engine
  (`ui_flutter/tool/demo_engine.py`, unelevated) uses `\\.\pipe\NOBADVPN-dev-<SID>`.
- JSON-RPC 2.0, **one JSON object per line**, UTF-8, at most 1 MiB per line either way. The engine writes ASCII only.
- Requests carry an `id`; replies can come in any order. Events are notifications named after the event:
  `{"jsonrpc":"2.0","method":"traffic","params":{...}}`. Ignore event names you don't know.
- Errors: `-32700` not JSON, `-32600` not a request (also "Message too big", then the pipe closes), `-32601` no such
  method, `-32602` a parameter has the wrong type, length or form, `-32603` the engine failed (never with details),
  `-32001` this program may not control NOBAD VPN (sent once, with `id: null`, then the pipe closes).
- A well-formed request the engine can't carry out is a normal result `{"ok": false, "error": "<a sentence>"}`. The
  engine guarantees `error` is a non-empty sentence (never a bare `{"ok": false}`).

### Start-up order for a window

1. `hello` → check `protocol` is 1. `methods` lists what this engine serves.
2. `subscribe {events: [...]}`: main window `state traffic health direct_health probe log error_action notify
   fix_result task_done ipinfo endpoint_report net_repair_start net_repair_done update show quitting`; pop-up
   `state traffic error_action show quitting`.
3. `state` once (events only report changes).
4. `ui_shown {window}` / `ui_hidden {window}` whenever it comes on screen or goes: the engine samples traffic every 2 s
   only while a window is visible, otherwise every 30 s.
5. On a broken pipe reconnect with backoff, unless `quitting` came first.

## Methods

`params.SPEC` is the list; the schema has each one's parameters. Groups:

- **The pipe:** `hello`, `subscribe`, `unsubscribe`, `state`, `ui_shown`, `ui_hidden`, `ui_show {window}` (show the
  other window: `{shown, launched}`; both false means "start it yourself").
- **Connection:** `connect {name}`, `disconnect`, `fastest`, `smart {service?}`, `probe`, `favorite {name}`,
  `endpoint_check {name}`, `dismiss_error`, `panic_reset`, `net_repair {level}`, `net_changes`.
- **Settings:** `settings {key, value}` (validated by `settings.coerce` after the shape check), `theme {value}`,
  `wizard_done`, `trusted_add {name?}`, `current_network`.
- **Servers and configs:** `rescan`, `open_configs`, `import {name, content}` (the text of a file the window read),
  `import_url {url}`, `free_scan`, `free_import {files}` (bare names from `free_scan`), `config_get/validate/save/
  delete {name, text?}`.
- **Checks and tools, setup, links, reports, updates:** as in `api.HANDLERS`, plus Network Intelligence (`ni_*`) and
  Streaming Region Intelligence (`si_*`).

Every method answers like the WebView's `/api/<name>` did, so the WebView's behaviour is the reference.
