# NOBAD VPN release manifest

`releases.json` is the public release index consumed by `/products/vpn/`.

- `latest`: version string of the current recommended release, or `null` while no release is public.
- `releases`: newest-first list of published releases.
- Never add an entry until the installer exists, has been tested, and its SHA-256 digest has been calculated.
- Use immutable versioned artifact paths such as `/downloads/vpn/1.2.0/nobad-vpn-setup.exe`.
- Do not overwrite an already published version. Publish a new version instead.

The manifest is intentionally empty. No installer or VPN capabilities have been fabricated.
