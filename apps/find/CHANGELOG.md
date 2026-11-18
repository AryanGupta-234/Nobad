# NOBAD Find changelog

## 0.6.1 · 2026-11-18

### Fixed
- Setup and uninstall no longer look stuck: stopping a running NOBAD Find took about 30 seconds per try
  (up to 3 minutes for an uninstall). Now it takes a moment.
- Opening NOBAD Find from the Start menu while it runs in the background now brings its window up. Before, nothing
  happened, so it looked like the app wouldn't start.
- You can now quit NOBAD Find completely: Settings → Launch → Quit. Closing the window still keeps it in the
  background for the hotkey; Quit stops it, indexing included.
- Started with "Run as administrator", it now says why it won't run instead of silently closing.
- If setup itself was run as administrator, the "Start NOBAD Find" box at the end now starts it as you, not as
  administrator.

### Changed
- New app icon: the NOBAD mark with a yellow "n", like every NOBAD app (each has its own colour).

## 0.6.0 · 2026-11-17

The first release of NOBAD Find: private, offline search for your own files on Windows 10 and 11.

### Added
- Find anything by name, by the words inside (documents, PDFs, Office and ODF files, EPUB, code, notes, e-mail
  files) and, optionally, by meaning with a small model on your PC (23 MB, downloaded only if you allow it).
- Photos by what's in them, optionally (a local image model, about 211 MB, downloaded only if you allow it), and
  the words in photos, screenshots and scanned PDFs with the OCR built into Windows.
- Plain-language questions: kinds, times, sizes, order, apps, your folders, drives and typed paths ("rent pdf
  from last week", "list all pdf here", "pdf in D:\Work bigger than 1 mb", "photos on my usb stick").
- A filter bar (kind, date, size, folder, order), previews in the results, and "here": the File Explorer folder
  you pressed the hotkey (Win+Shift+Space) in.
- Optional USB, external and network drives; unplugged drives stay findable, marked "not connected".
- One click to use NOBAD Find instead of Windows Search, and one click back.
- See-through window on Windows 11, and its own app icon.

### Privacy and security
- Nothing leaves your PC: no account, no telemetry. The only connections are the two optional model downloads,
  pinned and checked by SHA-256.
- The index is encrypted (SQLCipher) with a key only your Windows account can open (DPAPI).
- Runs as your normal account, never as admin. Other people's profiles, Windows itself, AppData and secret
  material (.ssh, key files, password managers) are never indexed. Files are read in separate low-priority
  processes and never run.

### Known
- The installer isn't code-signed yet, so Windows SmartScreen warns: More info, then Run anyway.

## Development builds

The versions below were test builds before the first release.

### 0.6.0 (development build, not released)
- Previews: photos, videos and PDFs in the results show Windows' own thumbnails, so you can see at a glance
  whether a photo match is right.
- More accurate photo meaning: the cut-off was tuned on 55 real photos in 19 topics (precision 0.73 -> 0.82 at
  the same recall); look-alikes ("flowers" -> a colourful cake) are shown dimmed under "Less sure"; when you ask
  for photos, what's in the picture counts most; OCR no longer turns stray marks in a photo into text.
- Light when idle: the models load when you search or when there's indexing work, warm up when you open the
  window, and leave memory after 3 minutes unused (idle memory 315 MB -> about 135 MB). Faster photo pass when
  you're away (photos in batches, out of Windows background mode).
- See-through window on Windows 11 (acrylic), following Windows' own Transparency effects switch (setting).
- The Index tab shows memory in use right now and which models are loaded.
- New app icon: a white magnifier with a spark on NOBAD orange.

### 0.5.0 (development build, not released)
- Photo meaning (optional): "dog on a beach" finds IMG_0042.jpg even with no words in it. A local image-text
  model (SigLIP base by Google, Apache-2.0, about 211 MB, pinned and SHA-256 checked) is downloaded only when you
  allow it. Photos are decoded by Windows' own decoders in a separate low-priority process; about 4 photos a
  second while you're away, gently while you use the PC.
- One click to use NOBAD Find instead of Windows Search: Windows Search indexing off (Windows asks once) and
  NOBAD Find starts with Windows; one click back restores Windows Search exactly as it was.
- NOBAD Find has its own app icon (a magnifying glass holding the NOBAD "n"); the NOBAD brand mark stays inside
  the app.

### 0.4.0 (development build, not released)
- Filter bar: kind, date, size, folder (with a folder picker), order, clear. Filters work with an empty search
  box, so "every PDF in this folder, newest first" is two clicks.
- "here" and "this folder": the folder you were looking at in File Explorer (or the desktop) when you pressed the
  hotkey. "list all pdf here" lists them; a "Here:" button puts that folder in the filter bar.
- Folder paths typed in the question: `pdf in D:\Work\Tax 2024`, `invoices "C:\My Files"`. Spaces are fine;
  something that only looks like a path is left out with a note. Network paths are only used when NOBAD Find
  already knows them, so typing one never makes Windows contact a server.
- Size and order words: "bigger than 100 mb", "under 2 mb", "big videos", "newest", "oldest", "largest".
- Lists of matching files show up to 500 and say when there are more.

### 0.3.1 (development build, not released)
- Your folders in the question: "list all download folder pdf", "photos on the desktop", "invoices in my
  documents". The real folders come from Windows, so Desktop and Documents moved to OneDrive work too.
- Fewer weak meaning matches: a file whose name alone is "car" or "garden" no longer shows up for "rent".
- "list", "all", "every", "give me" are understood as asking, not as words to look for; a question with only
  filters lists the newest matching files.

### 0.3.0 (development build, not released)
- Better meaning search: file and folder names have meaning too, so "seaside pictures" finds
  IMG_goa_beach_sunset.jpg and "power bill" finds electricity-bill-march.pdf; text is read together with its
  file's name. On a test set of vague questions the right file now comes first 16 times in 18 (was 7).
- Fewer misses: the meaning cut-off was tuned on measurements (it hid right answers before), and only matches
  close to the best one are shown.
- Fast on big indexes: 400,000 meaning vectors are searched in about 16 ms (was about half a second), with less
  memory use per search. Vectors of changed or deleted text no longer pile up in memory.
- Results say "name/text has a close / related / loosely related meaning" instead of a percentage.
- Rescans no longer rewrite the name index for files whose name didn't change.

### 0.2.0 (development build, not released)
- Words in photos, screenshots and scanned PDFs, read with the OCR built into Windows (offline, setting on).
- Places in the question: "on my usb stick", "on d:", "on the network drive", or a drive's name. USB, external
  and network drives can be indexed (settings, off by default); unplugged drives stay findable, marked
  "not connected".
- Apps in the question: "photoshop files", "blender projects", "after effects" and more.
- Gentler while you use the PC, full speed when you're away; pauses during calls (microphone or camera in use).
- Uninstalling puts Windows Search back the way it was if NOBAD Find turned it off.

### 0.1.0 (development build, not released)
- First build: instant name search, text inside documents/PDF/Office/EPUB/code/e-mail files, optional local
  meaning search, plain-language kinds and times, live updates, encrypted index, hotkey, Windows Search switch.
