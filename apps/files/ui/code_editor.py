from __future__ import annotations

import json
from pathlib import Path
import uuid

from PySide6.QtCore import QObject, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QPlainTextEdit,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    HAS_WEBENGINE = True
except Exception:  # pragma: no cover
    HAS_WEBENGINE = False

from editor.syntax import language_for_path


class EditorBridge(QObject):
    """QWebChannel bridge mediating between PySide6 and Monaco Editor inside QWebEngineView."""

    documentChanged = Signal(dict)
    commandRequested = Signal(str)
    languageChanged = Signal(str)
    diffRequested = Signal(dict)

    text_updated = Signal(str, str)  # (sessionId, text)
    cursor_moved = Signal(str, int, int)  # (sessionId, line, col)
    save_triggered = Signal(str, str)  # (sessionId, text)
    ready = Signal()

    @Slot(str, str)
    def contentChangedFromWeb(self, session_id: str, text: str) -> None:
        self.text_updated.emit(session_id, text)

    @Slot(str, int, int)
    def cursorChangedFromWeb(self, session_id: str, line: int, col: int) -> None:
        self.cursor_moved.emit(session_id, line, col)

    @Slot(str, str)
    def saveFromWeb(self, session_id: str, text: str) -> None:
        self.save_triggered.emit(session_id, text)

    @Slot()
    def webReady(self) -> None:
        self.ready.emit()


class CodeEditorWidget(QWidget):
    """
    Desktop-class Monaco Code Editor Widget.
    Uses Monaco Editor (VS Code core) via QWebEngineView and typed QWebChannel,
    with an automatic fallback to QPlainTextEdit for headless/CLI environments.
    """

    changed = Signal()
    cursor_changed = Signal(int, int)  # (line, col)
    save_requested = Signal()

    def __init__(self, *, path: str = "", text: str = "", readonly: bool = False) -> None:
        super().__init__()
        self.path = path
        self.session_id = uuid.uuid4().hex[:12]
        self._text = text
        self._readonly = readonly
        self._language = language_for_path(path, first_line=text.split("\n", 1)[0] if text else "")
        self._web_ready = False
        self._loading = True

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self._init_editor()
        self._loading = False

    def _init_editor(self) -> None:
        if HAS_WEBENGINE:
            try:
                self._init_webengine_editor()
                return
            except Exception:  # pragma: no cover
                pass
        self._init_native_fallback()

    def _init_webengine_editor(self) -> None:
        self.view = QWebEngineView(self)
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.view.setStyleSheet("background: #09090c; border: none;")
        self.view.page().setBackgroundColor(QColor("#09090c"))

        # Configure WebEngine Settings for local-to-remote resource access & smooth scrolling
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)

        self.bridge = EditorBridge(self)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("editorBridge", self.bridge)
        self.channel.registerObject("editorController", self.bridge)
        self.view.page().setWebChannel(self.channel)

        self.bridge.text_updated.connect(self._on_web_text_updated)
        self.bridge.cursor_moved.connect(self._on_web_cursor_moved)
        self.bridge.save_triggered.connect(self._on_web_save_triggered)
        self.bridge.ready.connect(self._on_web_ready)

        html_path = Path(__file__).resolve().parent.parent / "resources" / "editor" / "editor.html"
        if not html_path.exists():
            html_path = Path(__file__).resolve().parent.parent / "resources" / "editor" / "editor_v2.html"

        self.view.setUrl(QUrl.fromLocalFile(str(html_path)))
        self.view.loadFinished.connect(lambda ok: self._sync_document_to_web())
        self.layout.addWidget(self.view)
        self.native_fallback = None

    def _init_native_fallback(self) -> None:
        self.view = None
        self.bridge = None
        self.native_fallback = QPlainTextEdit(self)
        self.native_fallback.setStyleSheet("""
            QPlainTextEdit {
                background-color: #09090c;
                color: #f4f4f5;
                font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
                font-size: 13px;
                line-height: 1.5;
                border: none;
                padding: 10px;
            }
            QScrollBar:vertical {
                background: #09090c;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #272738;
                min-height: 24px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3f3f5a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background: #09090c;
                height: 8px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #272738;
                min-width: 24px;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #3f3f5a;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        self.native_fallback.setPlainText(self._text)
        self.native_fallback.setReadOnly(self._readonly)
        self.native_fallback.textChanged.connect(self._on_native_text_changed)
        self.native_fallback.cursorPositionChanged.connect(self._on_native_cursor_changed)
        self.layout.addWidget(self.native_fallback)

    def _on_web_ready(self) -> None:
        self._web_ready = True
        self._sync_document_to_web()

    def _sync_document_to_web(self) -> None:
        if not self.view:
            return
        payload = {
            "sessionId": self.session_id,
            "path": self.path,
            "text": self._text,
            "language": self._language,
            "readonly": self._readonly,
        }
        payload_json = json.dumps(payload)
        self.view.page().runJavaScript(f"if (window.rfmEditor) window.rfmEditor.loadDocument({payload_json});")
        if self.bridge and self._web_ready:
            try:
                self.bridge.documentChanged.emit(payload)
            except Exception:
                pass

    def _on_web_text_updated(self, session_id: str, new_text: str) -> None:
        if session_id != self.session_id:
            return
        if self._text != new_text:
            self._text = new_text
            if not self._loading:
                self.changed.emit()

    def _on_web_cursor_moved(self, session_id: str, line: int, col: int) -> None:
        if session_id == self.session_id:
            self.cursor_changed.emit(line, col)

    def _on_web_save_triggered(self, session_id: str, text: str) -> None:
        if session_id == self.session_id:
            self._text = text
            self.save_requested.emit()

    def _on_native_text_changed(self) -> None:
        if self.native_fallback and not self._loading:
            self._text = self.native_fallback.toPlainText()
            self.changed.emit()

    def _on_native_cursor_changed(self) -> None:
        if self.native_fallback:
            cursor = self.native_fallback.textCursor()
            line = cursor.blockNumber() + 1
            col = cursor.columnNumber() + 1
            self.cursor_changed.emit(line, col)

    # --- Public API (Backward Compatible with all callers) ---

    def text(self) -> str:
        if self.native_fallback is not None:
            return self.native_fallback.toPlainText()
        return self._text

    def set_text(self, value: str) -> None:
        self._loading = True
        self._text = value
        if self.native_fallback is not None:
            self.native_fallback.setPlainText(value)
        else:
            self._sync_document_to_web()
        self._loading = False

    def set_language(self, language: str) -> None:
        self._language = language
        if self.view:
            self.view.page().runJavaScript(f"if (window.rfmEditor) window.rfmEditor.setLanguage({json.dumps(language)});")
        if self._web_ready and self.bridge:
            self.bridge.languageChanged.emit(language)

    def language(self) -> str:
        return self._language

    def set_readonly(self, readonly: bool) -> None:
        self._readonly = readonly
        if self.native_fallback is not None:
            self.native_fallback.setReadOnly(readonly)
        else:
            self._sync_document_to_web()

    def is_readonly(self) -> bool:
        return self._readonly

    def run_command(self, cmd: str) -> None:
        if self.view:
            self.view.page().runJavaScript(f"if (window.rfmEditor) window.rfmEditor.command({json.dumps(cmd)});")
        if self._web_ready and self.bridge:
            self.bridge.commandRequested.emit(cmd)

    def find_text(self, needle: str, *, case_sensitive: bool = False) -> bool:
        if not needle:
            return False
        if self.native_fallback is not None:
            flags = QTextDocument.FindFlag.FindCaseSensitively if case_sensitive else QTextDocument.FindFlag(0)
            return bool(self.native_fallback.find(needle, flags))
        # Trigger Monaco's native find widget
        self.run_command("find")
        return needle.lower() in self._text.lower()

    def replace_current(self, replacement: str) -> bool:
        if self.native_fallback is not None:
            cursor = self.native_fallback.textCursor()
            if not cursor.hasSelection():
                return False
            cursor.insertText(replacement)
            return True
        self.run_command("replace")
        return True

    def replace_all(self, needle: str, replacement: str, *, case_sensitive: bool = False) -> int:
        if not needle:
            return 0
        source = self.text()
        if case_sensitive:
            count = source.count(needle)
            updated = source.replace(needle, replacement)
        else:
            import re

            updated, count = re.subn(re.escape(needle), lambda _m: replacement, source, flags=re.IGNORECASE)
        if count:
            self.set_text(updated)
            self.changed.emit()
        return count

    def goto_line(self, line: int) -> None:
        if self.native_fallback is not None:
            cursor = self.native_fallback.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.MoveAnchor, max(0, line - 1))
            self.native_fallback.setTextCursor(cursor)
            self.native_fallback.ensureCursorVisible()
        elif self.view:
            self.view.page().runJavaScript(f"if (window.rfmEditor) window.rfmEditor.revealLine({line});")

    def highlight_lines(self, start: int, end: int, color: str = "#4d3b24") -> None:
        if self.native_fallback is not None:
            selections: list[QTextEdit.ExtraSelection] = []
            document = self.native_fallback.document()
            for line in range(max(0, start), max(start + 1, end)):
                block = document.findBlockByNumber(line)
                if not block.isValid():
                    continue
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(block)
                selection.cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                selection.format = QTextCharFormat()
                selection.format.setBackground(QColor(color))
                selections.append(selection)
            self.native_fallback.setExtraSelections(selections)
