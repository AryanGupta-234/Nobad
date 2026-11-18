# NOBAD Find

**Software with a point of view.** Private, offline search for everything on your PC.

Describe what you're looking for the way you remember it: *"rent pdf from last week"*, *"beach photos in
march"*, *"budget.xlsx"*. NOBAD Find looks at file names, the words inside files and, if you turn it on, what
they're about, and tells you why each result matched.

> **Download:** the installer is on the [NOBAD Find releases](https://github.com/nobad-studio/Nobad-VPN/releases?q=find-v)
> (per-user, no admin). It isn't code-signed yet, so Windows SmartScreen warns: **More info**, then **Run anyway**.

## What it does
- **Names, instantly.** Any part of a file or folder name, across your profile and every fixed drive.
- **The text inside.** Documents (Word, ODF, RTF), spreadsheets, slides, PDFs, EPUBs, code, notes and e-mail
  files (.eml, .mbox). Word forms match ("landlords" finds "landlord").
- **Meaning, optionally.** A small model on your PC lets "rent" find "lease agreement", and reads file and
  folder names for meaning too: "seaside pictures" finds `IMG_goa_beach_sunset.jpg`, "power bill" finds
  `electricity-bill-march.pdf`.
- **Photos by what's in them (optional).** "Dog on a beach" finds `IMG_0042.jpg` even with no words in it, with
  a local image model you download once (about 211 MB) and only if you want it.
- **Words in photos and scans.** Screenshots, photos of documents and scanned PDFs are read with the OCR built
  into Windows. Offline; it runs after everything else because it's slower.
- **Plain-language filters.** Kinds ("pdf", "photos", "spreadsheet", "code"), times ("yesterday",
  "last week", "in March", "3 weeks ago", "2024"), apps ("photoshop files", "blender") and places
  ("on my usb stick", "on d:", "on the network drive") and your folders ("in my downloads", "on the desktop")
  are understood and shown as chips.
- **Filters and folders.** A filter bar (kind, date, size, folder, order) next to the search box. Type a path
  ("pdf in D:\Work\Taxes") or say "here" for the File Explorer folder you opened NOBAD Find from:
  "list all pdf here".
- **USB, external and network drives** (optional). Indexed while plugged in; when you unplug one, its files
  stay findable and are marked "not connected".
- **Always current.** Folder-change notifications put new, changed and deleted files in the index within seconds.
- **Stays out of your way, and says why.** Every two seconds it checks how much of the PC is free and works at
  full speed, gently, lightly (one worker) or not at all, always with a one-line reason. A game alone doesn't
  stop it: it only pauses when the PC is really busy, an app stops responding or memory runs low. It remembers
  apps that lagged (by program name only) and gives them room next time. It pauses on battery, during
  presentations and during calls. Its own processes run in Windows background mode inside one Windows job, so
  quitting or a crash ends every one of them; a watchdog ends its own stuck or oversized workers.
- **Full transparency.** The Indexing page shows each phase with progress and time left, NOBAD Find's own CPU,
  memory, disk and graphics use per process, every model (size, licence, in memory or not, CPU or GPU) and
  every decision it made.
- **Optional: turn off Windows Search indexing**, with one-click undo (see below).
- Hotkey **Win+Shift+Space** from anywhere. ↑ ↓ to move, Enter to open, Ctrl+Enter to show in its folder, Ctrl+C
  to copy the path, Shift+Delete to forget a result. The window stays up after Enter (Settings → Launch → Hide after
  opening a file hides it, like a launcher).
  Closing the window (or Esc) stops indexing and every worker; one small idle process stays so the hotkey works.
  **Settings → Performance → Keep indexing in the background** keeps indexing after closing; **Settings → About →
  Quit** stops it completely.
- **Quick find bar** on **Ctrl+Alt+Space**: a small floating search bar with up to 8 results. Enter opens,
  Ctrl+Enter shows in its folder, Alt+Enter moves the search into the full window, Esc hides it.

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
  files are size-limited and read in separate low-priority processes, images are decoded only by Windows' own
  decoders, and nothing is ever run.
- **Its only connections:** two optional one-time model downloads from Hugging Face, each off until you allow it
  in Settings, pinned to one revision and checked against its SHA-256 before use: the meaning-search model
  (23 MB, all-MiniLM-L6-v2) and the photo model (about 211 MB, SigLIP base by Google, Apache-2.0). (Network drives, if you turn them on, are read over your
  own network like any other program opening files there.)

## Windows Search switch
Turning Windows Search indexing off frees CPU and disk, but the Start menu, Explorer and Outlook stop finding
files by their content. It's off by default. When you turn it off, NOBAD Find saves the start type Windows had
and puts it back when you turn it on again, or when you uninstall NOBAD Find.

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

## Build the installer
`powershell -ExecutionPolicy Bypass -File packaging\build.ps1` (from `apps/find`) builds a per-user installer
that needs no admin rights; see [`packaging/README.md`](packaging/README.md).

MIT License.
