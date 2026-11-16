from __future__ import annotations

from ui.keyboard_shortcuts import _available_key


def test_button_shortcut_keys_are_unique_within_a_panel() -> None:
    used: set[str] = set()
    assert _available_key("Refresh", used) == "r"
    used.add("r")
    assert _available_key("Reconnect", used) == "e"


def test_button_shortcut_key_ignores_punctuation() -> None:
    assert _available_key("A+", set()) == "a"
