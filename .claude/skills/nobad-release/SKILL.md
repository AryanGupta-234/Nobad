---
name: nobad-release
description: Ship a NOBAD VPN release everywhere - version bump, changelog, docs, tests, git main, CI-built tagged GitHub Release with attestation, releases.json and the live site. Use whenever VPN changes are done and the user wants them released, built, pushed or "updated everywhere".
---

# Release NOBAD VPN everywhere

Run every step, in order. Stop and report on the first failure. Work from the repo root unless noted.

1. **Version.** New feature → minor (1.4.x → 1.5.0); fixes only → patch. Set `APP_VER` in `apps/vpn/nobadvpn/const.py`.
2. **Changelog.** New top section `## X.Y.Z · YYYY-MM-DD` in `apps/vpn/CHANGELOG.md` with `### Added / Fixed /
   Changed / Security` as needed, in plain user language. CI refuses the tag unless this matches `APP_VER`.
3. **Docs.** Update `apps/vpn/docs/FEATURES.md` (and SYSTEM-INTEGRATION.md for any new outbound connection). If a
   feature is user-visible, add a line to the VPN product page in `site-pages/products/vpn/index.html`.
4. **Check.** In `apps/vpn`: `python -m pytest -q` and `python -m pyflakes nobadvpn tests` must both be clean.
5. **Commit and push `main`.** Stage only `apps/vpn` plus the files you changed (never `apps/Sentinal/`, never
   unrelated uncommitted work without asking). End the message with the Co-Authored-By line. `git push origin main`.
6. **Tag. CI builds and publishes. Do NOT `gh release create`.**
   `git tag -a vpn-vX.Y.Z -m "NOBAD VPN X.Y.Z" && git push origin vpn-vX.Y.Z`, then wait:
   `gh run watch $(gh run list --workflow vpn-release.yml --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status`
   Both jobs, `build` and `publish`, must succeed.
7. **Verify the published installer** (in a scratch folder outside the repo):
   `gh release download vpn-vX.Y.Z -p "NobadVPN-Setup-X.Y.Z.exe*"`, compare `sha256sum` with the `.sha256` file, and run
   `gh attestation verify NobadVPN-Setup-X.Y.Z.exe -R AryanGupta-234/Nobad` (exit 0).
8. **Manifest.** Insert a new first entry in `releases/vpn/releases.json` (same fields as the others; `size` is
   decimal MB, e.g. 24547952 bytes → "24.5 MB") using the **CI** installer's sha256 and size, and set `latest`.
   Bump the example version in `.github/ISSUE_TEMPLATE/bug_report.yml`.
9. **Site.** `npm run build`. Both `public/index.html` and `public/products/vpn/index.html` must contain the new version.
   Commit `site: publish NOBAD VPN X.Y.Z`, push `main`.
10. **Live check.** Wait for the `Validate and build NOBAD` run, then poll
    `https://nobad-platform.aassworld99.workers.dev/releases/vpn/releases.json` until `latest` is the new version.

Report: version, the release URL, the CI and attestation result, and that the site is live. The installer is not
code-signed yet (SmartScreen warns); say so until signing is set up.
