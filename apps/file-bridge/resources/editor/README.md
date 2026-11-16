# Desktop V2 Rich Editor

Desktop V2 uses Monaco Editor 0.56.0. During development, `editor_v2.html` is a pinned CDN fallback.
For an offline/package-ready build, create the bundled ESM assets:

```bash
cd resources/editor/web
npm install
npm run build
```

`EditorController` automatically prefers `resources/editor/web/dist/index.html` when it exists.
The PyInstaller v2 spec already includes the whole `resources/` tree.
