# NOBAD Find (in development)

A private, offline search engine for your own files on Windows: describe something vaguely ("that PDF about
rent from last week") and it finds it by name, by the words inside it and by meaning.

Out of scope (decided 2026-11-17): no activity timeline (Recent items, browser history, event logs, programs run)
and no raw NTFS/MFT or change-journal reading. Files are found with the normal-user folder walk and kept up to
date with standard folder-change notifications.

Status: released (0.6.0, 2026-11-17) from `apps/find/` (pywebview + HTML UI, runs as the normal user). Every item below is
built; context filters are time, kind, app and place (drive / USB / network), since activity history is out of
scope. Installer: `apps/find/packaging/`.

## What it indexes
- File and folder names on your drives (your own profile, never other users' profiles or Windows itself).
- Text inside documents, PDF, Office/ODF, EPUB, code, notes and e-mail files (.eml/.mbox).

## Speed
- Parallel folder walk as the normal user, then folder-change notifications for updates.
- Worker-process pipeline (Python threads can't use several cores): scanner → extractor pool (text, PDF, OCR) →
  embedder (GPU via DirectML if present) → writer.
- Tuned to the machine: leave 1-2 cores free; SSD = parallel readers, HDD = one sequential reader; pause on battery,
  full screen, games and calls; full speed when idle; Windows background priority for CPU and disk.

## Replacing Windows Search
- Optional switch to stop/disable the `WSearch` service. Off by default, one-click undo, original state saved and
  restored on uninstall. Must say plainly that Start menu, Explorer and Outlook search stop working.
- Hotkey (e.g. Win+Shift+Space) opens NOBAD Find.

## Search
- Hybrid: keyword (SQLite FTS5) + meaning (local embeddings) + context filters (time, app, network, device).
- Plain-language time ("last week", "in March") and file kinds ("pdf", "photos") understood in the question. Indexed documents are untrusted input to the AI.

## Privacy and security (non-negotiable)
- The index is the most sensitive file on the PC: encrypted at rest (SQLCipher), key protected with DPAPI.
- Runs as the normal user. Only the Windows Search switch asks for admin, as a one-shot helper with fixed arguments.
- Nothing leaves the PC: no cloud, no telemetry, local models only.
- Default exclusions (password managers, key folders, `.ssh`), user exclusions, "forget this" for any file or folder.
- Same rules as NOBAD VPN: untrusted file names and contents never reach shell strings or `innerHTML` unescaped.

## Build order
1. Instant file-name search (parallel walk + change watcher), hotkey, UI.
2. Content search: extraction pool + FTS5 + encryption.
3. Meaning search: embeddings + GPU/CPU auto-tuning.
4. Plain-language time and file-kind filters in the question.
5. Email files (.eml/.mbox) and the Windows Search switch.

Stack: Python 3.11, `multiprocessing`, SQLCipher (SQLite FTS5), ONNX Runtime (DirectML when available), pywebview.
