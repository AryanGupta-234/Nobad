# Build NOBAD Find: fresh venv -> hash-pinned dependencies -> tests -> lint -> PyInstaller -> sign -> installer -> sign.
# The deliverable is ONE file: dist-installer\NobadFind-Setup-<version>.exe (per-user, no admin rights needed).
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1                 app + installer
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -InstallTools   also installs Inno Setup via winget
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -AppOnly        just dist\NobadFind (dev/testing)
#
# Signing (unsigned builds trigger SmartScreen). Pick one:
#   A) Certificate in the Windows certificate store (USB token / cloud-HSM "virtual card"; no password here):
#        $env:NOBAD_SIGN_THUMBPRINT = "AB12CD..."
#   B) Microsoft Artifact Signing (cloud signing service):
#        $env:NOBAD_SIGN_DLIB = "C:\...\bin\x64\Azure.CodeSigning.Dlib.dll"
#        $env:NOBAD_SIGN_METADATA = "C:\...\metadata.json"
#   C) A .pfx file (only for older certificates that still allow file-based keys):
#        $env:NOBAD_SIGN_PFX = "C:\path\cert.pfx" ; $env:NOBAD_SIGN_PASS = "..."
#
# This file must stay pure ASCII: Windows PowerShell 5.1 reads BOM-less UTF-8 as ANSI.
param([switch]$InstallTools, [switch]$AppOnly)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$ver = (Select-String -Path nobadfind\const.py -Pattern '^APP_VER = "([0-9A-Za-z.+-]+)"').Matches[0].Groups[1].Value
if (-not $ver) { throw "APP_VER not found in nobadfind\const.py" }
Write-Host "Building NOBAD Find $ver"

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

# ---------------------------------------------------------------- fresh venv (Python 3.11) + pinned dependencies
$py = "python"; $pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
  try { & py -3.11 -c "pass" 2>$null; if (-not $LASTEXITCODE) { $py = "py"; $pyArgs = @("-3.11") } } catch { }
}
if (Test-Path .venv-build) { Remove-Item -Recurse -Force .venv-build }
& $py @pyArgs -m venv .venv-build; if ($LASTEXITCODE) { throw "could not create .venv-build" }
.\.venv-build\Scripts\Activate.ps1
$pyver = (python -c "import sys; print('%d.%d' % sys.version_info[:2])")
if ($pyver -ne "3.11") { throw "NOBAD Find builds with Python 3.11 (found $pyver)" }
python -m pip install -q --require-hashes -r requirements-lock.txt             # the app + test tools, by hash
if ($LASTEXITCODE) { throw "pip install (requirements-lock.txt) failed" }
python -m pip install -q --require-hashes -r packaging\requirements-build.txt  # PyInstaller, by hash
if ($LASTEXITCODE) { throw "pip install (packaging\requirements-build.txt) failed" }

# ---------------------------------------------------------------- tests + lint + app
python -m pytest -q tests; if ($LASTEXITCODE) { throw "tests failed" }
python -m pyflakes nobadfind tests; if ($LASTEXITCODE) { throw "pyflakes failed" }
python packaging\make_version_info.py $ver packaging\version_info.txt; if ($LASTEXITCODE) { throw "version info failed" }
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\nobadfind.spec
if ($LASTEXITCODE) { throw "PyInstaller failed" }

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
Sign "dist\NobadFind\NobadFind.exe"
if ($AppOnly) {
  Write-Host "App built: dist\NobadFind\NobadFind.exe (no installer: -AppOnly)"
  exit 0
}

# ---------------------------------------------------------------- installer
$isccArgs = @("/DMyAppVersion=$ver")
if ($signArgs.Count) {
  # Inno signs the uninstaller with the same tool ($f = file being signed, $q = a quote character).
  $quoted = ($tsArgs + $signArgs | ForEach-Object { if ($_ -match '\s') { '$q' + $_ + '$q' } else { $_ } }) -join " "
  $isccArgs += ('/Snobadsign=$q' + $signtool + '$q sign ' + $quoted + ' $f')
  $isccArgs += "/DSignBuild=1"
}
& $iscc @isccArgs packaging\installer.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }
$setup = "dist-installer\NobadFind-Setup-$ver.exe"
Sign $setup

$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
# One LF-terminated line, so `sha256sum -c` works on Linux/macOS too (Set-Content would write CRLF).
$shaPath = Join-Path (Get-Location) "dist-installer\NobadFind-Setup-$ver.exe.sha256"
[System.IO.File]::WriteAllText($shaPath, "$hash  NobadFind-Setup-$ver.exe`n", [System.Text.Encoding]::ASCII)
if ($signArgs.Count) { Write-Host "Signed as: $((Get-AuthenticodeSignature $setup).SignerCertificate.Subject)" }
Write-Host "Done: $setup"
Write-Host "SHA-256: $hash"
