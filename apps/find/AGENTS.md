# NOBAD Find: notes for AI assistants

The repository rules in the root [`AGENTS.md`](../../AGENTS.md) apply.

**Start with [`ROADMAP.md`](ROADMAP.md):** the order of work (resources first, then stability, the Flutter UI,
then features), the architecture, the feature inventory, and a status table to resume from.

Specific to this app:

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
- OCR (`ocr.py`) uses only the Windows built-in `Windows.Media.Ocr` through the pinned `winrt-*` 3.2.1 packages
  (keep every winrt package on one version), inside the text worker processes. No OCR model downloads.
- Call detection (`winapi.in_call`) reads the user's own CapabilityAccessManager records; stale records from
  crashed apps must not pause indexing forever (age limit + process check).
- `--uninstall` (run by the installer's uninstaller) only undoes what the app changed outside its data folder.
- The index is SQLCipher with a DPAPI-protected key. The only outbound connections are the two optional model
  downloads, both through `embed._fetch_verified` (HTTPS, exact size, SHA-256): the text model
  (`const.MODEL_FILES`, gated by `allow_model_download`) and the photo model (`photo.PHOTO_FILES`, SigLIP base,
  Apache-2.0, gated by `allow_photo_model_download`). Keep model licences permissive for shipping (OpenAI CLIP's
  model card rules out deployment, so it isn't used).
- Photos for photo meaning are decoded only by Windows' decoders in the one photo worker process (`photo.py`).
  Result previews come from Windows' thumbnail cache (`thumbs.py`), asked for by result id, never a page path.
- Models are `embed.Lazy`: loaded on use, released when idle. Don't hold a model outside that wrapper.
- Typed network paths (\\server\share) are never looked up on disk (`search.folder_checker`): only folders already
  in the index or the folder list count, so typing one can't make Windows contact a server.
- New setting: `const.DEFAULTS` + `settings.coerce` + a row in `ui/app.js` GROUPS.
- Tests: `python -m pytest -q tests`. Lint: `python -m pyflakes nobadfind tests`. Both clean before a commit.
