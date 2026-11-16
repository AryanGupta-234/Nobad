# NOBAD Find: notes for AI assistants

The repository rules in the root [`AGENTS.md`](../../AGENTS.md) apply. Specific to this app:

- **Runs as the normal user, never as admin** (`app.py` refuses to start elevated). The only elevated code is
  `wsearch.helper_main`, which accepts the four words in `wsearch.STARTS` and runs `sc.exe` with a fixed argument
  list. Don't add other elevated paths.
- **Out of scope (maintainer decision 2026-11-17):** no activity timeline or usage history (Recent items, browser
  history, event logs, programs run) and no raw NTFS/MFT or change-journal reading. Indexing is the normal-user
  folder walk (`walker.py`) plus folder-change notifications (`watcher.py`).
- **Everything indexed is untrusted:** file names, folder names and file contents go to the UI only through
  `esc()`; FTS queries only through `store.fts_quote`; nothing builds a shell string; files are never executed
  except by the user's explicit Open (by result id, never a path from the page).
- Secret folders and key files in `const.ALWAYS_EXCLUDE_*` are never indexed. Keep the walk and `Walker.excluded`
  in step.
- The index is SQLCipher with a DPAPI-protected key. The only outbound connection is the optional model download
  (`embed.download_model`): pinned revision, sizes and SHA-256 in `const.MODEL_FILES`, gated by
  `allow_model_download`.
- New setting: `const.DEFAULTS` + `settings.coerce` + a row in `ui/app.js` GROUPS.
- Tests: `python -m pytest -q tests`. Lint: `python -m pyflakes nobadfind tests`. Both clean before a commit.
