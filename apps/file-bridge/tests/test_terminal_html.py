from __future__ import annotations

from pathlib import Path


def test_terminal_html_uses_xterm_input_and_output_apis() -> None:
    html = Path("resources/terminal/terminal.html").read_text(encoding="utf-8")

    assert "./vendor/xterm.js" in html
    assert "term.onData" in html
    assert "term.write" in html
    assert "bridge.input(data)" in html


def test_terminal_html_does_not_use_manual_arrow_key_map() -> None:
    html = Path("resources/terminal/terminal.html").read_text(encoding="utf-8")

    assert "ArrowUp" not in html
    assert "Backspace" not in html


def test_terminal_html_handles_copy_paste_interrupt_shortcuts_inside_xterm() -> None:
    html = Path("resources/terminal/terminal.html").read_text(encoding="utf-8")

    assert "term.attachCustomKeyEventHandler" in html
    assert "event.ctrlKey && event.shiftKey" in html
    assert 'key === "c"' in html
    assert 'key === "v"' in html
    assert "copySelection()" in html
    assert "pasteClipboard()" in html
    assert "interruptTerminal()" in html
    assert "bridge.copyText" in html
    assert "bridge.pasteFromClipboard" in html


def test_terminal_html_sends_enter_as_carriage_return() -> None:
    html = Path("resources/terminal/terminal.html").read_text(encoding="utf-8")

    assert 'key === "enter"' in html
    assert 'bridge.input("\\r")' in html
    assert "event.preventDefault()" in html


def test_terminal_vendor_assets_exist() -> None:
    assert Path("resources/terminal/vendor/xterm.js").is_file()
    assert Path("resources/terminal/vendor/xterm.css").is_file()
    assert Path("resources/terminal/vendor/addon-fit.js").is_file()


def test_terminal_html_filters_tiny_resize_events() -> None:
    html = Path("resources/terminal/terminal.html").read_text(encoding="utf-8")

    assert "term.cols >= 20" in html
    assert "term.rows >= 5" in html


def test_terminal_html_exposes_settings_hook() -> None:
    html = Path("resources/terminal/terminal.html").read_text(encoding="utf-8")

    assert "window.rfmTerminalApplySettings" in html
    assert "term.options.fontSize" in html
    assert "term.options.scrollback" in html


def test_terminal_copy_paste_uses_xterm_bridge_without_qt_shortcut_conflicts() -> None:
    panel = Path("ui/terminal_panel.py").read_text(encoding="utf-8")
    menu = Path("ui/menu_controller.py").read_text(encoding="utf-8")

    assert "rfmTerminalCopy" in panel
    assert "rfmTerminalPaste" in panel
    assert "rfmTerminalInterrupt" in panel
    assert "copyText" in panel
    assert "pasteFromClipboard" in panel
    assert "class TerminalWebView" in panel
    assert "copyShortcut.emit()" in panel
    assert "pasteShortcut.emit()" in panel
    assert "interruptShortcut.emit()" in panel
    assert 'self._add_shortcut("Ctrl+Shift+C"' not in panel
    assert 'self._add_shortcut("Ctrl+Shift+V"' not in panel
    assert '"Copy", lambda: self._terminal_action(self.window.terminal_panel.copy_current), "Ctrl+Shift+C"' not in menu
    assert '"Paste", lambda: self._terminal_action(self.window.terminal_panel.paste_current), "Ctrl+Shift+V"' not in menu
    assert "Ctrl++" in panel
    assert "Ctrl+-" in panel
    assert "font_up_button" in panel
    assert "font_down_button" in panel


def test_terminal_exit_callback_is_routed_through_a_qt_signal() -> None:
    panel = Path("ui/terminal_panel.py").read_text(encoding="utf-8")

    assert "backend_exited = Signal()" in panel
    assert "self.backend_exited.connect(self._backend_exited, Qt.ConnectionType.QueuedConnection)" in panel
    assert "self.backend.start(self.bridge.append_output, self.backend_exited.emit)" in panel


def test_terminal_background_callbacks_use_explicit_queued_connections() -> None:
    panel = Path("ui/terminal_panel.py").read_text(encoding="utf-8")

    assert "self.rawOutputReceived.connect(self._queue_output, Qt.ConnectionType.QueuedConnection)" in panel
    assert "worker.succeeded.connect(self._backend_started, Qt.ConnectionType.QueuedConnection)" in panel
    assert "worker.failed.connect(self._backend_start_failed, Qt.ConnectionType.QueuedConnection)" in panel
