# Playbook: release NOBAD Find everywhere

Same rules as the NOBAD VPN playbook (`release.md`): releases come only from CI, never `gh release create` by hand,
and every release goes everywhere. Stop and report on the first failure.

1. **Version.** `APP_VER` in `apps/find/nobadfind/const.py` (new feature → minor, fixes only → patch).
2. **Changelog.** New top section `## X.Y.Z · YYYY-MM-DD` in `apps/find/CHANGELOG.md` (`### Added / Fixed /
   Changed / Privacy and security / Known`), plain user language. CI refuses a tag that doesn't match `APP_VER`,
   or a top entry still marked "(in development)".
3. **Docs.** `apps/find/README.md`; new outbound connections also in `apps/find/AGENTS.md` and the README's
   privacy section; user-visible features on the website's `site-pages/products/find/index.html`
   (nobad-studio/website first). One line in `docs/ai/memory.md`.
4. **Check.** In `apps/find`: `python -m pytest -q tests` and `python -m pyflakes nobadfind tests`; a local
   `packaging/build.ps1` run must pass.
5. **Merge to `main`** through a PR (code-owner review). Stage only your own files.
6. **Tag. CI builds and publishes.**
   `git tag -a find-vX.Y.Z -m "NOBAD Find X.Y.Z" <main commit> && git push origin find-vX.Y.Z`, then
   `gh run watch <id of the latest find-release.yml run> --exit-status`. `build` and `publish` must both succeed.
   Find releases are created with `--latest=false`, so NOBAD VPN stays the repository's "latest" release.
7. **Verify the published installer** in a scratch folder outside the repo:
   `gh release download find-vX.Y.Z -R nobad-studio/Nobad-VPN -p "NobadFind-Setup-X.Y.Z.exe*"`, compare
   `sha256sum` with the `.sha256` file, and `gh attestation verify NobadFind-Setup-X.Y.Z.exe -R nobad-studio/Nobad-VPN
   --signer-workflow nobad-studio/Nobad-VPN/.github/workflows/find-release.yml --source-ref refs/tags/find-vX.Y.Z
   --deny-self-hosted-runners` (exit 0).
8. **Website.** In nobad-studio/website: `python scripts/publish_find_release.py X.Y.Z "<summary>"` (it reads the
   CI release's SHA-256 and size; never type checksums), `npm run build`, check `/products/find/`, PR to `main`,
   then confirm `/build.json` and `/releases/find/releases.json` on the live site.

Report: the version, the release URL, CI and attestation results, that the site is live, and that the installer
is unsigned until code signing is set up.
