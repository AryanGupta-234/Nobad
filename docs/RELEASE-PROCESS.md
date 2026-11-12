# NOBAD VPN release process

Releases are built by GitHub Actions from a version tag, never on a personal PC, and published to GitHub Releases.
The website only links to files that exist there.

## 1. Prepare

1. Bump `APP_VER` in `VPN_dev/nobadvpn/const.py` (semantic versioning).
2. Add a `## <version> · <date>` entry at the top of `VPN_dev/CHANGELOG.md`. The workflows refuse a tag whose
   version doesn't match both.
3. Push to `main` and wait for **NOBAD VPN tests** (Windows, hash-pinned dependencies) and **Validate and build NOBAD**
   to pass.
4. Optional dry run: Actions → *NOBAD VPN release* → *Run workflow*. It builds the installer as a workflow artifact
   and publishes nothing. Install it on a test PC: install, upgrade over the previous version, connect, kill switch,
   *Restore internet*, uninstall.

## 2. Release

```
git tag vpn-v<version>
git push origin vpn-v<version>
```

`.github/workflows/vpn-release.yml` then:

* **build** (read-only token): runs the tests and pyflakes, builds the app with PyInstaller, bundles the signed
  WireGuard installers, builds the Inno Setup installer and writes `latest.json`, the `.sha256` file and the SBOM.
* **publish** (the only job that can write): creates a signed build-provenance attestation for the files and
  publishes the GitHub Release with the notes from `CHANGELOG.md`.

Anyone can check a download came from this repository's workflow:

```
gh attestation verify NobadVPN-Setup-<version>.exe -R AryanGupta-234/Nobad
```

## 3. Put it on the website

```
python scripts/publish_vpn_release.py <version> "<one-line summary>"
git add releases/vpn/releases.json && git commit -m "site: publish NOBAD VPN <version>" && git push
```

The script reads the release from GitHub, takes the size and the SHA-256 GitHub computed for the uploaded installer,
checks it against the `.sha256` file, and adds the entry first. The site build fills the download desk from it.

## Rollback

Published versions are never changed or re-uploaded. If a release is bad:

1. Point the website back: `python scripts/publish_vpn_release.py --latest <previous version>`, commit and push.
2. On GitHub, edit the bad release: untick *Set as the latest release* (or delete it if it must not be downloaded).
3. Fix the problem and release a **higher** version. The updater never installs an older version, so users who
   already installed the bad one move forward only.

## Code signing

Releases are not code-signed yet; see `VPN_dev/docs/CODE-SIGNING.md`. Until they are, the app can't update itself
(it only installs signed updates), so users install new versions by hand.
