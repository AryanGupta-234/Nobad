# NOBAD public release process

## Before publishing

1. Build the installer from a clean, tagged source commit.
2. Test install, upgrade, uninstall, rollback and supported OS/architecture combinations.
3. Scan the artifact and review dependencies; investigate all material findings.
4. For Windows binaries, sign with the project's trusted Authenticode certificate and verify the signature on a clean machine.
5. Write release notes describing changes, known issues, requirements and upgrade steps.
6. Confirm the product page's protocol, encryption, logging, permissions and network-behavior disclosures are accurate. Do not claim "no logs" or specific security guarantees without evidence.

## Publish

From the project root, run `python scripts/publish_vpn_release.py --help` and then supply the tested artifact, semantic version, date, platform, architecture, channel, summary and release-notes path.

The publisher copies the artifact to an immutable versioned directory, calculates SHA-256, and prepends metadata to `releases/vpn/releases.json`. Commit the manifest, notes and artifact; deployment copies all three into the static `public/` output.

## Hosting requirements

- Serve the site over HTTPS.
- Preserve exact case-sensitive paths.
- Configure correct MIME types for installers and JSON.
- Keep old versioned artifacts available for rollback and reproducibility.
- Back up release artifacts and manifest.
- Do not put secrets or signing keys in this repository or static site.
- Consider object storage/CDN for large binaries and rate limiting for abuse prevention.

## Release manifest

The VPN product page reads `/releases/vpn/releases.json`. An empty `releases` array intentionally displays a release-pending state. A SHA-256 hash detects changes relative to trusted metadata; it does not prove who published the file. Authenticode signatures and a trusted HTTPS origin provide additional publisher assurance.
