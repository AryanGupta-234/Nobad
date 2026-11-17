# Editor pages

Both windows use the same bundled Monaco Editor 0.56.0 in `vendor/monaco/` (see `vendor/monaco/VERSION.txt` for
the source and its npm checksum). Nothing is loaded from a CDN (issue #30).

* Classic window: `editor.html` (and the fallback `editor_v2.html`), loaded from disk by `ui/code_editor.py`.
* Web UI: the same files are served at `/static/vendor/monaco/` (`app_web/server.py`), used by
  `app_web/ui/screens/editor.js`.

To update Monaco, download the new `monaco-editor` tarball from the npm registry, check its `integrity`, copy
`min/vs` here without `vs/nls/lang`, `*.d.ts` and `vs/language`, and update `VERSION.txt`. `tests/test_web_editor.py`
checks that every worker file `editor.main.js` refers to is present.

`web/` holds an older experiment with a Vite build of the editor; it isn't used by either window.
