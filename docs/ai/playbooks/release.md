# Playbook: release NOBAD VPN everywhere

The human-facing process is [`docs/RELEASE-PROCESS.md`](../../RELEASE-PROCESS.md); this is the full checklist an
assistant runs. Stop and report on the first failure. Work from the repo root unless noted.

1. **Version.** New feature → minor (1.5.x → 1.6.0); fixes only → patch. Set `APP_VER` in `apps/vpn/nobadvpn/const.py`.
2. **Changelog.** New top section `## X.Y.Z · YYYY-MM-DD` in `apps/vpn/CHANGELOG.md` with `### Added / Fixed /
   Changed / Security`, in plain user language. CI refuses the tag unless it matches `APP_VER`.
3. **Docs.** `apps/vpn/docs/FEATURES.md`, and `SYSTEM-INTEGRATION.md` for any new outbound connection or system
   change. User-visible features also go on `site-pages/products/vpn/index.html`. Add a line to `docs/ai/memory.md`.
4. **Check.** In `apps/vpn`: `python -m pytest -q` and `python -m pyflakes nobadvpn tests` must both be clean.
5. **Commit and push `main`.** Stage only the files you changed (never `apps/Sentinal/` or other people's
   uncommitted work without asking). `git push origin main`.
6. **Tag. CI builds and publishes. Never `gh release create`.**
   `git tag -a vpn-vX.Y.Z -m "NOBAD VPN X.Y.Z" && git push origin vpn-vX.Y.Z`, then
   `gh run watch <id of the latest vpn-release.yml run> --exit-status`. Both `build` and `publish` must succeed.
7. **Verify the published installer** in a scratch folder outside the repo:
   `gh release download vpn-vX.Y.Z -R nobad-studio/nobad -p "NobadVPN-Setup-X.Y.Z.exe*"`, compare `sha256sum` with
   the `.sha256` file, and run `gh attestation verify NobadVPN-Setup-X.Y.Z.exe -R nobad-studio/nobad --signer-workflow
   nobad-studio/nobad/.github/workflows/vpn-release.yml --source-ref refs/tags/vpn-vX.Y.Z --deny-self-hosted-runners`
   (exit 0). Without the last three options the check accepts any workflow in the repo.
8. **Manifest.** New first entry in `releases/vpn/releases.json` (same fields as the others; `size` in decimal MB,
   e.g. 24547952 bytes → "24.5 MB") with the **CI** installer's sha256 and size; set `latest`. Bump the example
   version in `.github/ISSUE_TEMPLATE/bug_report.yml`.
9. **Site.** `npm run build`; `public/index.html` and `public/products/vpn/index.html` must show the new version.
   Commit `site: publish NOBAD VPN X.Y.Z`, push `main`.
10. **Live check.** Poll `https://nobad-platform.aassworld99.workers.dev/releases/vpn/releases.json` until `latest`
    is the new version. If Cloudflare's build never starts for the commit (no "Workers Builds" check after about 5
    minutes), push an empty commit to retrigger it.

Report: the version, the release URL, CI and attestation results, and that the site is live. Until code signing is
set up, say that the installer is unsigned.
