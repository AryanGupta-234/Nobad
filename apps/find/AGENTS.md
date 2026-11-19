# NOBAD Find: notes for AI assistants

The repository rules in the root [`AGENTS.md`](../../AGENTS.md) apply.

**Start with [`ROADMAP.md`](ROADMAP.md):** the order of work (resources first, then stability, the Flutter UI,
then features), the architecture, the feature inventory, and a status table to resume from.

Specific to this app:

- **Runs as the normal user, never as admin** (`app.py` and `engine.py` refuse to start elevated). There are
  exactly two elevated helpers; don't add others:
  - `wsearch.helper_main`: accepts the four words in `wsearch.STARTS` and runs `sc.exe` with a fixed argument list.
  - `ntfs.helper_main` (the **turbo index**, maintainer decision 2026-11-19, setting `turbo`, **off by default**):
    accepts only the words in `ntfs.WORDS` (`serve`, `selftest`), reads NTFS metadata (MFT enumeration, file
    records, change journal), never file contents, and talks only to its parent engine over a pipe whose DACL is the
    user's SID (both ends check PIDs and the session). It drops other users' profiles, recycle bins, System Volume
    Information, NTFS metafiles, everything outside the user's scope and categories, and folders the user couldn't
    list (AccessCheck with the user's token) before anything leaves it; the engine applies its own rules again. Read
    the module docstring before changing it. Content reading (text, OCR, models) stays in the normal-user workers.
  Tests never trigger UAC: the turbo tests use fake links and synthetic USN/MFT buffers (the pipe's DACL and PID
  checks are tested on a real, unelevated pipe). From source the helper is dev only and refuses without
  `NOBAD_FIND_DEV_TURBO=1`; don't relax that (the prompt would name python.exe, imports come from the source tree).
- **Out of scope (maintainer decision 2026-11-17):** no activity timeline or usage history (Recent items, browser
  history, event logs, programs run). Indexing is the normal-user folder walk (`walker.py`) plus folder-change
  notifications (`watcher.py`); the turbo helper above is the one optional exception for names and changes.
- **Everything indexed is untrusted:** file names, folder names and file contents go to the UI only through
  `esc()`; FTS queries only through `store.fts_quote`; nothing builds a shell string; files are never executed
  except by the user's explicit Open (by result id, never a path from the page).
- What's indexed follows `scope.Rules` (maintainer decision 2026-11-19: nothing skipped silently; every category
  is shown by `scope_info`): system folders and caches are user choices (default on), secrets (`const.SECRET_*`:
  keys, browser passwords/cookies/history, Windows Credentials/Vault/Protect, chat and developer tokens, wallets) are
  off by default and **names only** when on (never read, never thumbnailed), browser profiles and app databases
  (`const.NAMES_ONLY_*`) are names only even with caches on, other people's files and
  `const.FIXED_NAMES` are always out. The walk, `Walker.excluded` (live changes) and the turbo helper's `ntfs.Filter`
  all use `scope.Rules`; keep them in step.
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
- New setting: `const.DEFAULTS` + `settings.coerce` + a row in `ui/app.js` GROUPS + `contract/methods.schema.json`
  (`$defs/settings` and `settings_changes`).
- The UI ⇄ engine pipe (`nobadfind/rpc/`) follows `contract/`: a new or changed method or event updates the schema,
  `contract/README.md`, a transcript (`python tests/test_rpc_contract.py --record`) and the Dart side together.
  Handlers stay thin (check params, call the `Api` method, shape the result); files only by result id.
- Tests: `python -m pytest -q tests`. Lint: `python -m pyflakes nobadfind tests`. Both clean before a commit.
