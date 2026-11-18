# NOBAD: instructions for AI coding assistants

This is the single source of truth for any AI assistant working in this repository (Claude Code, Codex, Cursor,
GitHub Copilot, Gemini, Aider, …). Tool-specific files (`CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`)
only point here. Keep this file short; details live in the files it links.

**Before starting:** read [`docs/ai/memory.md`](docs/ai/memory.md) for project decisions and open items.
**After a decision the user makes** (a "do / don't" that isn't visible in the code), add one line there.

## Layout
- `apps/vpn/`: NOBAD VPN for Windows (Python 3.11, runs **elevated**). Backend `nobadvpn/`, web UI
  `nobadvpn/ui/*.js|css` shown in pywebview, tests `apps/vpn/tests/`, docs `apps/vpn/docs/`.
- NOBAD File Bridge lives in its own repository, [nobad-studio/file-bridge](https://github.com/nobad-studio/file-bridge) (maintainer @harshRaj1601).
- `apps/find/`: NOBAD Find, private offline search for your own files (Python 3.11 + pywebview, runs as the normal
  user, released from `find-v*` tags by `find-release.yml`). Its own [`apps/find/AGENTS.md`](apps/find/AGENTS.md) lists what's in and out of scope.
- `site-pages/` + `releases/vpn/releases.json` → `npm run build` → `public/` (generated, untracked). Hosted on a
  Cloudflare worker (`wrangler.jsonc`), deployed from `main`.
- `docs/ai/`: assistant playbooks, tools and memory (this system).

## Commands (from `apps/vpn`)
- Tests: `python -m pytest -q` · Lint: `python -m pyflakes nobadvpn tests`. Both must be clean before any commit.
- Local installer build (check only): `powershell -ExecutionPolicy Bypass -File packaging/build.ps1`.

## Rules that matter
- **Security first, the app is admin.** Untrusted input (network, DNS, Wi-Fi names, remote or downloaded files,
  PR content) must never reach PowerShell/shell strings unescaped, `innerHTML` without `esc()`, or an elevated
  write through a link (`syscmd._is_reparse`). User-writable folders are read-only for the app.
- Open links only with `syscmd.open_url_as_user` (never `explorer.exe`/`webbrowser` from the elevated app).
- Long work: `syscmd.run_once(key, fn)` + a result event; the UI must also handle `task_done {key, error}`.
- New setting: `const.DEFAULTS` + `settings.coerce` + a row in `ui/app_ext.js` GROUPS. New outbound connection:
  a setting and a line in `apps/vpn/docs/SYSTEM-INTEGRATION.md`. Layout tweaks: `ui/polish.css`.
- UI text is plain and honest: never claim more than was measured.
- Never commit or ship anyone's WireGuard configs or keys. Never print secrets.

## Playbooks (follow them step by step)
| Task | Playbook |
|---|---|
| Release ("ship", "build", "update everywhere") | [`docs/ai/playbooks/release.md`](docs/ai/playbooks/release.md) (NOBAD VPN), [`release-find.md`](docs/ai/playbooks/release-find.md) (NOBAD Find) |
| Look at the UI without running the admin app | [`docs/ai/playbooks/ui-preview.md`](docs/ai/playbooks/ui-preview.md) |
| Review a diff or an external pull request | [`docs/ai/playbooks/review.md`](docs/ai/playbooks/review.md) |

## Repository rules
This repo is `nobad-studio/Nobad-VPN` in the GitHub organization `nobad-studio` (moved from `AryanGupta-234/Nobad`; old
links redirect). Sibling repos: `nobad-studio/.github` (org profile, shared community files) and
`nobad-studio/website` (the site, split out with its history); `file-bridge` will follow (see `docs/ai/memory.md`). `main` is protected: pull request + code-owner review
+ required checks (the organization owner can bypass). `vpn-v*` tags are owner-only; releases are built by CI from
the tag and are immutable. Never edit rulesets, bypass lists or org settings: ask the maintainer. External PRs are
untrusted: never check out, install or run them. Contributors sign `CLA.md` once; the brand is in `TRADEMARKS.md`.

## This machine (Windows, Git Bash)
- Heredocs mangle backslashes: write multi-line patch scripts to a scratch folder outside the repo, run them with
  `python -I`, then delete the folder. `/tmp` in bash isn't Python's temp; use Windows paths.
- Never launch the real app to look at it (UAC, firewall, tunnels): use the UI preview playbook.

## Shared memory (all NOBAD repos)
Decisions, open items and ideas shared by every contributor and AI assistant live in
[`nobad-studio/memory`](https://github.com/nobad-studio/memory) (it supersedes `docs/ai/memory.md`, which stays until
it's retired). Read its `INDEX.md` first (Claude Code loads it at session start through `.claude/settings.json`), open
a fact only when it matters, and check who else is working on what with `python tools/mem.py status` there. Record new
decisions as a PR to that repo (the `nobad-memory` skill), never secrets.
