# Getting a Windows code-signing certificate for NOBAD VPN

A VPN installer runs with administrator rights. Unsigned, it has three problems:

* Windows shows "Windows protected your PC" (SmartScreen).
* Users can't verify who published it.
* NOBAD's auto-updater refuses to install unsigned updates, by design.

`packaging/build.ps1` supports all three signing routes below.

## Recommended for NOBAD: free signing for open source (SignPath Foundation)

NOBAD VPN is MIT-licensed and built by GitHub Actions from the public repository, which is exactly what the
**SignPath Foundation** supports **free of charge** for open-source projects: <https://signpath.org/apply>. The
certificate is issued to the SignPath Foundation, the key stays in SignPath's HSM, and every release needs a manual
approval in SignPath.

What their terms ask for, and where NOBAD stands:

| Condition | Status |
|---|---|
| OSI licence, actively maintained, already released | MIT; several releases on GitHub Releases (1.2.0 onward) |
| Verifiable build from source; manual approval per release | `.github/workflows/vpn-release.yml` builds from the tag |
| *Code signing policy* on the home page, with team roles and a privacy policy | `/code-signing-policy/` and `/privacy/`, linked from the home page footer |
| Product name and version on the binaries | `packaging/make_version_info.py` |
| Uninstaller; system changes disclosed | Inno Setup uninstaller; `docs/SYSTEM-INTEGRATION.md` |
| MFA for every team member (GitHub and SignPath) | the maintainer must have two-factor authentication on |
| No non-open-source components | **check with SignPath:** the installer bundles WireGuard LLC's signed MSIs (not re-signed by NOBAD). If they object, switch the installer to download WireGuard at install time (the app's `wginstall.py` already can). |

After approval, SignPath gives you an organization id, a project slug, a signing policy and an API token. Store the
token as a GitHub Actions secret, and add SignPath's GitHub Action to `vpn-release.yml` **between the build step and
the release step**, following SignPath's documentation for the exact inputs: it uploads the unsigned installer and
waits for your approval. The workflow then publishes the signed files.

**Updater note.** A SignPath Foundation certificate is shared by every project SignPath signs, so its subject or
thumbprint alone can't tell a NOBAD installer from another project's. Before turning on automatic updates for
SignPath-signed builds, the updater must also check something only NOBAD's release can produce, for example the
GitHub build-provenance attestation the release workflow now creates, or a NOBAD-held key that signs
`latest.json`. Until then, keep `UPDATE_SIGNER_SUBJECTS` empty and update by hand.

Paid alternatives are below, if signing under NOBAD's own name is needed later.

## Which route fits

| Route | Who can use it | Notes |
|---|---|---|
| **Microsoft Artifact Signing** (formerly "Trusted Signing") | Organizations in the US, Canada, EU, UK, Australia, New Zealand, Japan, South Korea, Singapore, Switzerland, Norway and Israel. **Individual developers: US and Canada only.** | Cheapest and easiest if you qualify. Needs a paid Azure subscription. Identity validation takes 1–20 business days. Certificates are re-issued every few days; the service handles that. |
| **OV code-signing certificate from a certificate authority** (DigiCert, Sectigo, SSL.com, Certum, GlobalSign, ...) | Anyone. Companies get the company name on the certificate; individuals get their own name. | Works from **India** and everywhere else. The private key must live on a hardware token or the CA's cloud HSM; downloadable `.pfx` files are no longer issued. Validity is limited to about a year. |
| **EV certificate** | Registered organizations | More validation, higher price. It **no longer** skips SmartScreen reputation, so it's rarely worth it for an app like this. |

If you're in India (or anywhere outside the Artifact Signing lists), buy an **OV certificate with cloud signing**. Examples are
Certum *SimplySign*, SSL.com *eSigner*, DigiCert *KeyLocker* and Sectigo/GlobalSign cloud HSM offers. Cloud signing means no USB token to
lose, and it works on a build server.

## Steps (OV certificate)

1. **Decide whose name is on it.** Your registered company (recommended, e.g. "NOBAD Technologies Pvt Ltd") or you
   as an individual. Users see this name in the UAC prompt and the file's *Digital Signatures* tab.
2. **Prepare documents.**
   * Company: incorporation certificate, GST/registration, a business address and phone number that can be verified (e.g. a
     directory listing), and a company-domain email.
   * Individual: government photo ID (passport, Aadhaar, PAN) and proof of address.
3. **Buy the certificate** from the CA or a reseller and choose cloud signing (or a hardware token). Expect
   ID verification and a phone call; it usually takes a few days.
4. **Install the signing client** the CA provides (e.g. SimplySign Desktop, eSigner CKA). It exposes your certificate
   in the Windows certificate store as a "virtual card".
5. **Find the thumbprint.** Run `certmgr.msc`, open *Personal → Certificates*, then your certificate's *Details* →
   *Thumbprint*. Or in PowerShell:
   `Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Format-List Subject, Thumbprint`
6. **Install the Windows SDK signing tools.** Get the *Windows SDK* and select only "Signing Tools for Desktop Apps".
7. **Build signed:**
   ```powershell
   $env:NOBAD_SIGN_THUMBPRINT = "AB12CD..."      # from step 5
   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
   ```
   The script signs `NobadVPN.exe`, the uninstaller and the setup. At the end it prints the certificate subject.
8. **Pin the publisher.** Optional, but recommended: copy the printed subject into `UPDATE_SIGNER_SUBJECTS` in `nobadvpn/const.py`. By default
   NOBAD only accepts updates signed with the same publisher name as the running app, so a renewed certificate in the same name keeps
   working.

## Steps (Microsoft Artifact Signing, if eligible)

1. Get a paid Azure subscription. Register the `Microsoft.CodeSigning` resource provider and create an Artifact Signing account.
2. Complete **identity validation** (Organization or Individual) in the Azure portal, then create a **Public Trust** certificate profile.
3. Install the client tools: `winget install -e --id Microsoft.Azure.ArtifactSigningClientTools`
4. Create `metadata.json`:
   ```json
   {"Endpoint": "https://<region>.codesigning.azure.net", "CodeSigningAccountName": "<account>",
    "CertificateProfileName": "<profile>"}
   ```
5. Sign in with `az login`, then build:
   ```powershell
   $env:NOBAD_SIGN_DLIB = "C:\...\bin\x64\Azure.CodeSigning.Dlib.dll"
   $env:NOBAD_SIGN_METADATA = "C:\...\metadata.json"
   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
   ```
   The script switches to Microsoft's timestamp server automatically.

## After signing: SmartScreen reputation

Signing proves who you are. SmartScreen *reputation* still builds up with downloads, so a brand-new publisher may see
the warning for the first releases. To speed it up:

* Always sign with the same certificate name.
* Keep the download URL stable.
* Submit the signed installer to Microsoft for analysis at <https://www.microsoft.com/wdsi/filesubmission>
  (choose "Software developer").

## Keep it safe

* Never commit certificates, `.pfx` files, passwords or `metadata.json` secrets to the repository.
* Use cloud signing or the hardware token only on your own build PC.
* If the key is ever exposed, ask the CA to revoke the certificate, then release a new version signed with a new certificate.
