# Editor files

The web UI's editor uses the bundled Monaco Editor 0.56.0 in `vendor/monaco/` (see `vendor/monaco/VERSION.txt` for
the source and its npm checksum). Nothing is loaded from a CDN (issue #30). `app_web/server.py` serves these files at
`/static/vendor/monaco/`, used by `app_web/ui/screens/editor.js`.

To update Monaco, download the new `monaco-editor` tarball from the npm registry, check its `integrity`, copy
`min/vs` here without `vs/nls/lang`, `*.d.ts` and `vs/language`, and update `VERSION.txt`. `tests/test_web_editor.py`
checks that every worker file `editor.main.js` refers to is present.
