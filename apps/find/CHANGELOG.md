# NOBAD Find changelog

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
