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
    assert "bg_notice_seen" in JS


def test_no_inline_scripts_or_handlers():
    for m in re.finditer(r"<script\b([^>]*)>", HTML, re.IGNORECASE):
        assert "src=" in m.group(1)
    assert not re.search(r"\son[a-z]+\s*=", HTML, re.IGNORECASE)
    assert 'style="' not in HTML


def test_now_panel_is_built_once_and_updated_in_place():
    body = JS.split("function paintNow(s) {", 1)[1].split("\n}\n", 1)[0]
    assert "innerHTML" not in body, "paintNow must not rebuild the button/live region every tick"
    assert 'id="ixPause"' in HTML and 'id="ixNowText"' in HTML
    assert 'aria-live="polite"' in HTML.split('id="ixNowText"')[0].rsplit("<", 1)[1] + HTML.split('id="ixNowText"')[1].split(">")[0]
    assert 'tab("index")' not in JS and "ixTick();" not in JS.split("function tab(name)")[1].split("}\n", 1)[0]


def test_settings_pages_exist():
    for ident in ("sp-general", "sp-indexing", "sp-models", "sp-performance", "sp-privacy", "sp-about"):
        assert f'id="{ident}"' in HTML, ident


def test_every_setting_key_has_a_control():
    from nobadfind.const import DEFAULTS
    internal = {"wsearch_prev", "pause_fullscreen", "bg_notice_seen", "welcome_seen",     # old/internal: no control
                # chosen on the Flutter UI's Settings -> Models page (the models methods), not in this 0.7.0 page
                "text_model", "photo_model", "language_focus",
                # 0.8.5: Flutter Settings -> Privacy only (the WebView page is being removed)
                "search_history"}
    for key in set(DEFAULTS) - internal:
        assert f'"{key}"' in JS, f"no control for setting {key}"
    for label in ("Smart (recommended)", "Always pause", "Don't change"):
        assert label in JS


def test_home_sections_exist():
    for ident in ("home", "homeChips", "homeTiles", "homeRecent", "homeStatus"):
        assert f'id="{ident}"' in HTML, ident
    assert "<kbd>" in HTML.split('id="home"')[1]               # the keyboard hints stay


def test_theme_setting_is_applied():
    assert "dataset.theme" in JS


def test_native_dialogs_pause_the_heartbeat_check():
    """I-6: confirm()/prompt() stop the page's timers; each goes through ask(), which tells the watchdog the page
    is not on screen first, so a slow answer is never taken for a hung window (reload, then quit)."""
    helper = re.search(r"async function ask\(fn, \.\.\.a\) \{(.*?)\n\}", JS, re.S)
    assert helper and 'api("page_visible", false)' in helper.group(1) and "finally" in helper.group(1)
    bare = re.findall(r"(?<![\w.])(confirm|prompt)\(", JS)
    assert bare == [], "a native dialog outside ask()"
    assert JS.count("ask(confirm,") == 2 and JS.count("ask(prompt,") == 1


def test_background_notice_is_remembered_in_settings():
    """I-7: the WebView runs InPrivate, so localStorage is gone every start; the notice's "seen" is a setting."""
    from nobadfind import settings
    from nobadfind.const import DEFAULTS
    assert DEFAULTS["bg_notice_seen"] is False
    assert settings.coerce("bg_notice_seen", "yes") is False and settings.coerce("bg_notice_seen", True) is True
    assert "nf-bg-notice" not in JS
    assert 'set_settings", { bg_notice_seen: true }' in JS
