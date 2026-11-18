"""Static checks of the Find UI files (no browser needed)."""
import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "nobadfind" / "ui"
HTML = (UI / "index.html").read_text(encoding="utf-8")
JS = (UI / "app.js").read_text(encoding="utf-8")


def test_index_view_has_sections():
    for ident in ("ixNow", "ixPipeline", "ixResources", "ixSpark", "ixModels", "ixActivity", "roots", "drives", "rescan"):
        assert f'id="{ident}"' in HTML, ident
    assert re.search(r'<canvas[^>]*id="ixSpark"', HTML)


def test_index_refresh_only_when_visible():
    assert 'document.visibilityState === "visible"' in JS
    guard = re.search(r"function ixTick\(\)\s*\{[^}]*visibilityState", JS)
    assert guard, "the 2 s timer must check visibility"
    assert "2000" in JS
    assert "nf-bg-notice" in JS


def test_no_inline_scripts_or_handlers():
    for m in re.finditer(r"<script\b([^>]*)>", HTML):
        assert "src=" in m.group(1)
    assert not re.search(r"\son[a-z]+\s*=", HTML)
    assert 'style="' not in HTML
