"""What closing the window does.

- "hide": "Keep indexing in the background after closing" is on: the window hides, indexing goes on.
- "hide_idle": the setting is off (the default): indexing stops, every worker process ends, the models leave
  memory and the window hides. Only the main process stays, idle, so the hotkey still opens NOBAD Find;
  indexing resumes when the window opens again.
- "quit": "Quit NOBAD Find" was chosen, or the hotkey isn't working (a hidden Find could never be opened again).
"""


def on_close(settings, hotkey_ok, quitting):
    if quitting or not hotkey_ok:
        return "quit"
    return "hide" if settings.get("keep_background") else "hide_idle"
