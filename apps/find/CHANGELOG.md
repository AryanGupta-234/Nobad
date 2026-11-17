# NOBAD Find changelog

## 0.5.0 (in development)
- Photo meaning (optional): "dog on a beach" finds IMG_0042.jpg even with no words in it. A local image-text
  model (SigLIP base by Google, Apache-2.0, about 211 MB, pinned and SHA-256 checked) is downloaded only when you
  allow it. Photos are decoded by Windows' own decoders in a separate low-priority process; about 4 photos a
  second while you're away, gently while you use the PC.
- One click to use NOBAD Find instead of Windows Search: Windows Search indexing off (Windows asks once) and
  NOBAD Find starts with Windows; one click back restores Windows Search exactly as it was.
- NOBAD Find has its own app icon (a magnifying glass holding the NOBAD "n"); the NOBAD brand mark stays inside
  the app.

## 0.4.0 (in development)
- Filter bar: kind, date, size, folder (with a folder picker), order, clear. Filters work with an empty search
  box, so "every PDF in this folder, newest first" is two clicks.
- "here" and "this folder": the folder you were looking at in File Explorer (or the desktop) when you pressed the
  hotkey. "list all pdf here" lists them; a "Here:" button puts that folder in the filter bar.
- Folder paths typed in the question: `pdf in D:\Work\Tax 2024`, `invoices "C:\My Files"`. Spaces are fine;
  something that only looks like a path is left out with a note. Network paths are only used when NOBAD Find
  already knows them, so typing one never makes Windows contact a server.
- Size and order words: "bigger than 100 mb", "under 2 mb", "big videos", "newest", "oldest", "largest".
- Lists of matching files show up to 500 and say when there are more.

## 0.3.1 (in development)
- Your folders in the question: "list all download folder pdf", "photos on the desktop", "invoices in my
  documents". The real folders come from Windows, so Desktop and Documents moved to OneDrive work too.
- Fewer weak meaning matches: a file whose name alone is "car" or "garden" no longer shows up for "rent".
- "list", "all", "every", "give me" are understood as asking, not as words to look for; a question with only
  filters lists the newest matching files.

## 0.3.0 (in development)
- Better meaning search: file and folder names have meaning too, so "seaside pictures" finds
  IMG_goa_beach_sunset.jpg and "power bill" finds electricity-bill-march.pdf; text is read together with its
  file's name. On a test set of vague questions the right file now comes first 16 times in 18 (was 7).
- Fewer misses: the meaning cut-off was tuned on measurements (it hid right answers before), and only matches
  close to the best one are shown.
- Fast on big indexes: 400,000 meaning vectors are searched in about 16 ms (was about half a second), with less
  memory use per search. Vectors of changed or deleted text no longer pile up in memory.
- Results say "name/text has a close / related / loosely related meaning" instead of a percentage.
- Rescans no longer rewrite the name index for files whose name didn't change.

## 0.2.0 (in development)
- Words in photos, screenshots and scanned PDFs, read with the OCR built into Windows (offline, setting on).
- Places in the question: "on my usb stick", "on d:", "on the network drive", or a drive's name. USB, external
  and network drives can be indexed (settings, off by default); unplugged drives stay findable, marked
  "not connected".
- Apps in the question: "photoshop files", "blender projects", "after effects" and more.
- Gentler while you use the PC, full speed when you're away; pauses during calls (microphone or camera in use).
- Uninstalling puts Windows Search back the way it was if NOBAD Find turned it off.

## 0.1.0 (in development)
- First build: instant name search, text inside documents/PDF/Office/EPUB/code/e-mail files, optional local
  meaning search, plain-language kinds and times, live updates, encrypted index, hotkey, Windows Search switch.
