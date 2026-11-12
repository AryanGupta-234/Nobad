# NOBAD VPN release manifest

`releases.json` is the website's release index. The build (`scripts/prepare-site.mjs`) fills the download desk on
`/` and `/products/vpn/` from it, and the VPN page's script reads it too.

- `latest`: the version shown as current.
- `releases`: newest first. Every entry points at a real GitHub Release asset of this repository.
- Don't edit entries by hand: add them with `python scripts/publish_vpn_release.py <version> "<summary>"` after the
  release is published, and roll back with `--latest <version>`. See `docs/RELEASE-PROCESS.md`.
- Never change a published entry. Publish a new version instead.
