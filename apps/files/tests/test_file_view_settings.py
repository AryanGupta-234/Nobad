from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_file_view_preferences_are_exposed_and_persisted() -> None:
    settings = (ROOT / "ui" / "settings_panel.py").read_text(encoding="utf-8")
    main = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")

    assert '("Local Pane Layout", self.local_file_view' in settings
    assert '("Remote Pane Layout", self.remote_file_view' in settings
    assert '"file_browser"' in settings
    assert 'repo.set("file_browser",' in main
    assert 'self.local_panel.set_view_mode' in main
    assert 'self.remote_panel.set_view_mode' in main


def test_remote_tree_view_loads_children_only_when_expanded() -> None:
    source = (ROOT / "ui" / "remote_file_panel.py").read_text(encoding="utf-8")

    assert "self.tree.folder_expanded.connect(self._expand_tree_folder)" in source
    assert "self.remote_ops.list_dir(item.path" in source
