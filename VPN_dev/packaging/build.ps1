# Build the NOBAD VPN release: tests -> lint -> PyInstaller -> WireGuard MSIs (verified) -> sign -> installer -> sign
# -> update manifest. The deliverable is ONE file: dist-installer\NobadVPN-Setup-<version>.exe
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1                 full release build
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -InstallTools   also installs Inno Setup via winget
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -AppOnly        just dist\NobadVPN (dev/testing)
#
# Signing (needed for a public release - unsigned builds trigger SmartScreen and CANNOT auto-update). Pick one:
#   A) Certificate in the Windows certificate store (USB token / cloud-HSM "virtual card"; no password here):
#        $env:NOBAD_SIGN_THUMBPRINT = "AB12CD..."
#   B) Microsoft Artifact Signing (cloud signing service):
#        $env:NOBAD_SIGN_DLIB = "C:\...\bin\x64\Azure.CodeSigning.Dlib.dll"
#        $env:NOBAD_SIGN_METADATA = "C:\...\metadata.json"
#   C) A .pfx file (only for older certificates that still allow file-based keys):
#        $env:NOBAD_SIGN_PFX = "C:\path\cert.pfx" ; $env:NOBAD_SIGN_PASS = "..."
# Optional: $env:NOBAD_RELEASE_URL = "https://downloads.example.com/vpn/1.0.0"  (where the installer is uploaded)
#
# This file must stay pure ASCII: Windows PowerShell 5.1 reads BOM-less UTF-8 as ANSI.
param([switch]$InstallTools, [switch]$AppOnly)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$ver = (Select-String -Path nobadvpn\const.py -Pattern 'APP_VER = "([^"]+)"').Matches[0].Groups[1].Value
$wgVersion = (Select-String -Path nobadvpn\wginstall.py -Pattern 'WG_VERSION = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Building NOBAD VPN $ver (bundling WireGuard $wgVersion)"

# ---------------------------------------------------------------- tools
function Find-Iscc {
  $c = (Get-Command iscc -ErrorAction SilentlyContinue)
  if ($c) { return $c.Source }
  return @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
           "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
}
function Find-Signtool {
  $c = (Get-Command signtool -ErrorAction SilentlyContinue)
  if ($c) { return $c.Source }
  $k = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
       Sort-Object FullName -Descending | Select-Object -First 1
  if ($k) { return $k.FullName }
  return $null
}
$iscc = $null
if (-not $AppOnly) {
  $iscc = Find-Iscc
  if (-not $iscc -and $InstallTools) {
    winget install --id JRSoftware.InnoSetup -e --silent --accept-source-agreements --accept-package-agreements
    $iscc = Find-Iscc
  }
  if (-not $iscc) {
    throw "Inno Setup 6 is required to build the installer. Install it with:  winget install JRSoftware.InnoSetup   (or re-run with -InstallTools; use -AppOnly to build only the app folder)"
  }
}

# ---------------------------------------------------------------- tests + app
python -m venv .venv-build; .\.venv-build\Scripts\Activate.ps1
python -m pip install -q -r requirements-lock.txt   # pinned: every release build uses the same versions
$testOut = python -m pytest -q tests; $testCode = $LASTEXITCODE
$testOut | ForEach-Object { Write-Host $_ }
$testSummary = (($testOut | Where-Object { "$_" -match "passed|failed|error" } | Select-Object -Last 1) -replace "=", "").Trim()
if ($testCode) { python packaging\journal.py fail $ver "tests" "$testSummary"; throw "tests failed" }
python -m pyflakes nobadvpn tests; if ($LASTEXITCODE) { throw "pyflakes failed" }
python packaging\make_version_info.py $ver packaging\version_info.txt; if ($LASTEXITCODE) { throw "version info failed" }
pyinstaller --noconfirm --clean --distpath dist --workpath build packaging\nobad.spec
if ($LASTEXITCODE) { python packaging\journal.py fail $ver "PyInstaller" "$testSummary"; throw "PyInstaller failed" }

# ---------------------------------------------------------------- signing setup
$signArgs = @()
$tsUrl = "http://timestamp.digicert.com"
if ($env:NOBAD_SIGN_THUMBPRINT) { $signArgs = @("/sha1", $env:NOBAD_SIGN_THUMBPRINT) }
elseif ($env:NOBAD_SIGN_DLIB -and $env:NOBAD_SIGN_METADATA) {
  $signArgs = @("/dlib", $env:NOBAD_SIGN_DLIB, "/dmdf", $env:NOBAD_SIGN_METADATA)
  $tsUrl = "http://timestamp.acs.microsoft.com"
}
elseif ($env:NOBAD_SIGN_PFX) { $signArgs = @("/f", $env:NOBAD_SIGN_PFX, "/p", $env:NOBAD_SIGN_PASS) }
$tsArgs = @("/fd", "SHA256", "/tr", $tsUrl, "/td", "SHA256")
$signtool = $null
if ($signArgs.Count) {
  $signtool = Find-Signtool
  if (-not $signtool) { throw "signtool.exe not found - install the Windows SDK (Signing Tools for Desktop Apps)" }
}

function Sign($file) {
  if ($signArgs.Count) {
    & $signtool sign @tsArgs @signArgs $file
    if ($LASTEXITCODE) { throw "signing failed: $file" }
  } else {
    Write-Warning "NOT signing $file (see the signing options at the top of this script)."
  }
}
Sign "dist\NobadVPN\NobadVPN.exe"
if ($AppOnly) {
  Write-Host "App built: dist\NobadVPN\NobadVPN.exe (no installer: -AppOnly)"
  exit 0
}

# ---------------------------------------------------------------- WireGuard (bundled, verified)
New-Item -ItemType Directory -Force packaging\redist | Out-Null
foreach ($a in @("amd64", "arm64")) {
  $dst = "packaging\redist\wireguard-$a.msi"
  $stamp = "$dst.version"
  if (-not (Test-Path $dst) -or -not (Test-Path $stamp) -or ((Get-Content $stamp) -ne $wgVersion)) {
    $url = "https://download.wireguard.com/windows-client/wireguard-$a-$wgVersion.msi"
    Write-Host "Downloading $url"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $dst
    Set-Content -Encoding ascii -Path $stamp -Value $wgVersion
  }
  $sig = Get-AuthenticodeSignature $dst
  if ($sig.Status -ne "Valid" -or -not $sig.SignerCertificate.Subject.StartsWith("CN=WireGuard LLC,")) {
    Remove-Item $dst, $stamp -Force -ErrorAction SilentlyContinue
    throw "$dst is not validly signed by WireGuard LLC (status: $($sig.Status)) - refusing to bundle it"
  }
}

# ---------------------------------------------------------------- installer
$isccArgs = @("/DMyAppVersion=$ver")
if ($signArgs.Count) {
  # Inno signs the uninstaller with the same tool ($f = file being signed, $q = a quote character).
  $quoted = ($tsArgs + $signArgs | ForEach-Object { if ($_ -match '\s') { '$q' + $_ + '$q' } else { $_ } }) -join " "
  $isccArgs += ('/Snobadsign=$q' + $signtool + '$q sign ' + $quoted + ' $f')
  $isccArgs += "/DSignBuild=1"
}
# private build journal (maintainer only; a no-op when private\BUILD-JOURNAL.md is absent, e.g. in CI)
$buildId = (python packaging\journal.py start $ver "$testSummary" | Select-Object -Last 1).Trim()
& $iscc @isccArgs packaging\installer.iss
if ($LASTEXITCODE) { python packaging\journal.py fail $ver "Inno Setup" "$buildId"; throw "Inno Setup failed" }
$setup = "dist-installer\NobadVPN-Setup-$ver.exe"
Sign $setup
$signedFlag = if ($signArgs.Count) { "1" } else { "0" }
if ($buildId -ne "none") { python packaging\journal.py finish $buildId $setup $signedFlag }
if ($LASTEXITCODE) { throw "journal update failed" }
if ($buildId -ne "none") { Write-Host "Recorded as build $buildId in the private build journal" }

$base = if ($env:NOBAD_RELEASE_URL) { $env:NOBAD_RELEASE_URL.TrimEnd('/') } else { "https://YOUR-HOST/vpn/$ver" }
python packaging\make_manifest.py $setup "$base/NobadVPN-Setup-$ver.exe" "Release notes: https://github.com/AryanGupta-234/Nobad/releases" --out dist-installer\latest.json
if ($LASTEXITCODE) { throw "manifest failed" }
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
python packaging\make_sbom.py $ver "dist-installer\NobadVPN-Setup-$ver.sbom.json"
if ($LASTEXITCODE) { throw "SBOM failed" }
Set-Content -Encoding ascii -Path "dist-installer\NobadVPN-Setup-$ver.exe.sha256" -Value "$hash  NobadVPN-Setup-$ver.exe"
if ($signArgs.Count) {
  $subject = (Get-AuthenticodeSignature $setup).SignerCertificate.Subject
  Write-Host "Signed as: $subject"
  Write-Host "Updates are accepted only from this same publisher name (or pin it in nobadvpn\const.py UPDATE_SIGNER_SUBJECTS)."
}
Write-Host "Done: $setup  (upload it with dist-installer\latest.json; point Settings -> Updates at latest.json)"
