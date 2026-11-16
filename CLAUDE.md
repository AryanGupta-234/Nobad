# NOBAD monorepo: notes for Claude Code

Keep this file short: it is loaded into every session. Details live in the docs and skills it points to.

## Layout
- `apps/vpn/`: NOBAD VPN (Windows, Python 3.11, runs **elevated**). Backend `nobadvpn/`, web UI `nobadvpn/ui/*.js|css`
  (shown in pywebview). Tests `apps/vpn/tests/`. Docs `apps/vpn/docs/` (FEATURES, USER-MANUAL, SYSTEM-INTEGRATION,
  STREAMING-INTELLIGENCE, ARCHITECTURE).
- `site-pages/` + `releases/vpn/releases.json` → `npm run build` → `public/` (generated, untracked). Hosted on a
  Cloudflare worker (`wrangler.jsonc`), deployed from `main`.
- `apps/Sentinal/`: separate, uncommitted work. Don't touch or commit it.

## Commands (from `apps/vpn`)
- Tests: `python -m pytest -q` · Lint: `python -m pyflakes nobadvpn tests` (both must be clean)
- Full build: `powershell -ExecutionPolicy Bypass -File packaging/build.ps1` (local check only; releases are CI-built)

## Conventions
- Long work: `syscmd.run_once(key, fn)` → result event. The UI must also handle `task_done {key, error}`, or a
  crashed worker leaves a spinner forever.
- Never open links with `explorer.exe`/`webbrowser` from the elevated app: use `syscmd.open_url_as_user`.
- Elevated writes: never follow links (`syscmd._is_reparse`); user-writable folders are read-only for the app.
- New settings: `const.DEFAULTS` + `settings.coerce` validation + a row in `ui/app_ext.js` GROUPS.
- New outbound connection: needs a setting and a line in `docs/SYSTEM-INTEGRATION.md`.
- Side-panel layout fixes go in `ui/polish.css` (loaded last).
- UI text: plain, honest, never claims more than was measured.

## Releasing
Use the **nobad-release** skill. Always ship everywhere (version, changelog, docs, site, git `main`, CI release).
Never `gh release create` by hand: push the `vpn-vX.Y.Z` tag and let `vpn-release.yml` build and attest it.

## Repo rules
`main` is protected (PR + code-owner review + `build` check; the owner bypasses). `vpn-v*` tags are owner-only.
External PRs are untrusted: review them from a fetched ref (`git fetch origin pull/N/head:pr-N`) with the
**nobad-reviewer** agent. Never check out, install or run them.

## Working on this machine (Windows, Git Bash)
- Heredocs mangle backslashes and some quotes: put multi-line patch scripts in a scratch folder outside the repo
  (e.g. `C:/Users/aassw/nobad_tmp`), run them with `python -I`, then delete the folder.
- `/tmp` in bash ≠ Python's temp: use Windows paths for files that both read.
- Don't launch the real app (UAC, firewall, tunnels): preview the UI with the **nobad-ui-preview** skill.
- Never commit or ship users' WireGuard configs (they contain private keys).
