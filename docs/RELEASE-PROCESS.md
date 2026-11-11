# NOBAD VPN release process

1. Build and test the Windows installer from the actual VPN source repository.
2. Verify installation, upgrade, uninstall, connectivity, DNS behavior, fail-closed behavior (where applicable), and crash recovery.
3. Sign the installer with the product publisher's Authenticode certificate. Keep the signing private key outside this repository and outside CI logs.
4. Compute SHA-256 from the final signed installer:

   ```powershell
   Get-FileHash .\NOBAD-VPN-Setup-1.0.0.exe -Algorithm SHA256
   ```

5. Create a GitHub Release in the designated public downloads repository, using an immutable semantic version tag such as `v1.0.0`.
6. Upload the installer, checksum file and release notes.
7. Update `releases/vpn/releases.json` with the exact asset URL and actual SHA-256 digest.
8. Verify the public download URL, checksum, Authenticode signature and manifest from a clean machine before announcing the release.

## Manifest format

```json
{
  "product": "NOBAD VPN",
  "channel": "stable",
  "latest": "1.0.0",
  "releases": [
    {
      "version": "1.0.0",
      "platform": "windows-x64",
      "status": "published",
      "filename": "NOBAD-VPN-Setup-1.0.0.exe",
      "download_url": "https://github.com/OWNER/RELEASES_REPO/releases/download/v1.0.0/NOBAD-VPN-Setup-1.0.0.exe",
      "sha256": "ACTUAL_64_CHARACTER_SHA256"
    }
  ]
}
```

Never put an invented hash, fake release URL, untested binary, signing certificate or secret into the public manifest/repository.
