# NOBAD Find

**Software with a point of view.** Private, offline search for everything on your PC.

Describe what you're looking for the way you remember it: *"rent pdf from last week"*, *"beach photos in
march"*, *"budget.xlsx"*. NOBAD Find looks at file names, the words inside files and, if you turn it on, what
they're about, and tells you why each result matched.

> **Status: in development.** There is no installer yet. Run it from source (below).

## What it does
- **Names, instantly.** Any part of a file or folder name, across your profile and every fixed drive.
- **The text inside.** Documents (Word, ODF, RTF), spreadsheets, slides, PDFs, EPUBs, code, notes and e-mail
  files (.eml, .mbox). Word forms match ("landlords" finds "landlord").
- **Meaning, optionally.** A small model on your PC lets "rent" find "lease agreement".
- **Plain-language filters.** Kinds ("pdf", "photos", "spreadsheet", "code") and times ("yesterday",
  "last week", "in March", "3 weeks ago", "2024") are understood and shown as chips.
- **Always current.** Folder-change notifications put new, changed and deleted files in the index within seconds.
- **Stays out of your way.** It sizes its work to your CPU and drive (SSD or hard disk), runs in Windows
  background mode, and pauses on battery and during full-screen games or presentations.
- **Optional: turn off Windows Search indexing**, with one-click undo (see below).
- Hotkey **Win+Shift+Space** from anywhere. ↑ ↓ to move, Enter to open, Ctrl+Enter to show in its folder, Ctrl+C
  to copy the path, Shift+Delete to forget a result.

## Privacy and security
- **Nothing leaves your PC.** No account, no cloud, no telemetry.
- **Encrypted index.** The index is a SQLCipher database. Its random key is protected with Windows DPAPI, so only
  your Windows account on this PC can open it.
- **Runs as you, not as admin.** It refuses to start elevated. Only the Windows Search switch asks for
  permission, through a one-shot helper that accepts four fixed words.
- **Never indexed:** other people's profiles, Windows itself, `AppData`, and secret material such as `.ssh`,
  `.gnupg`, cloud credential folders, password-manager folders and key files (`.pem`, `.key`, `.pfx`, `.kdbx`, ...).
  Add your own folders to *Never search*; *Forget* removes a result and keeps it out.
- **Files are untrusted.** Office files are checked for zip bombs, XML is parsed without external entities,
  files are size-limited and read in separate low-priority processes, and nothing is ever run.
- **Its only connection:** the optional one-time download of the meaning-search model (23 MB,
  all-MiniLM-L6-v2 from Hugging Face). It's off until you allow it in Settings, it's pinned to one revision, and
  each file is checked against its SHA-256 before use.

## Windows Search switch
Turning Windows Search indexing off frees CPU and disk, but the Start menu, Explorer and Outlook stop finding
files by their content. It's off by default. When you turn it off, NOBAD Find saves the start type Windows had
and puts it back when you turn it on again.

## Run from source
```
cd apps/find
python -m pip install --require-hashes -r requirements-lock.txt
python -m nobadfind              # or: python -m nobadfind --background
```
Windows 10 (1809+) or 11, Python 3.11. Data lives in `%LOCALAPPDATA%\NOBAD\Find`.

## Develop
```
python -m pytest -q tests
python -m pyflakes nobadfind tests
```
MIT License.
