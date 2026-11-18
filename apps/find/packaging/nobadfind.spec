# PyInstaller spec for NOBAD Find - onedir, windowed (the installer wraps the folder). build.ps1 runs it from apps/find:
#   python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\nobadfind.spec
# No uac_admin: NOBAD Find runs as the normal user and refuses to start elevated. The one elevated step (the Windows
# Search switch) asks for it itself, through `NobadFind.exe --wsearch <word>`.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

HERE = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821 (provided by PyInstaller)
ROOT = os.path.dirname(HERE)
ICON = os.path.join(HERE, "nobadfind.ico")
VERSION = os.path.join(HERE, "version_info.txt")

# Windows only needs pywebview's WinForms + Edge WebView2 (EdgeChromium) backend; the other backends (and the GUI
# toolkits they would drag in if installed on the build machine) are left out.
hidden = collect_submodules("webview", filter=lambda m: not any(
    x in m for x in (".gtk", ".qt", ".cocoa", ".android", ".cef", ".mshtml")))
hidden += ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr", "clr_loader", "pythonnet"]
datas = [(os.path.join(ROOT, "nobadfind", "ui"), "nobadfind/ui")]
binaries = []

# Imported lazily inside functions (store / extract / embed); listed so a missing one fails the build, not the app.
hidden += ["sqlcipher3", "sqlcipher3.dbapi2", "pypdf", "numpy", "onnxruntime", "tokenizers"]
hidden += collect_submodules("pypdf")
binaries += collect_dynamic_libs("sqlcipher3") + collect_dynamic_libs("onnxruntime")
datas += collect_data_files("webview")      # pywebview's injected JS and the WebView2 loader DLLs
datas += collect_data_files("pypdf")

# Windows built-in OCR through the winrt projection (winrt-runtime + winrt-Windows.* packages). `winrt` is a
# namespace package split over many wheels, so collect whatever is installed; a build without it still works (the
# app then has no OCR).
try:
    import winrt  # noqa: F401
except ImportError:
    print("nobadfind.spec: winrt not installed - building without Windows OCR")
else:
    # Each projected namespace reads the _table.pywinrt data file beside it at import time, so the data files are
    # needed too (winrt-runtime also ships its own PyInstaller hook that does the same; collecting twice is harmless).
    hidden += collect_submodules("winrt")
    binaries += collect_dynamic_libs("winrt")
    datas += collect_data_files("winrt", excludes=["**/*.pyi"])

EXCLUDES = ["tkinter", "pytest", "_pytest", "pyflakes", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi",
            "webview.platforms.gtk", "webview.platforms.qt", "webview.platforms.cocoa",
            "webview.platforms.android", "webview.platforms.cef", "webview.platforms.mshtml"]

a = Analysis([os.path.join(HERE, "launch.py")], pathex=[ROOT], binaries=binaries, datas=datas,
             hiddenimports=hidden, excludes=EXCLUDES, noarchive=False)
# winrt-runtime ships its own, older C++ runtime (winrt\msvcp140.dll, 14.29). Once winrt has loaded it, onnxruntime
# (needs 14.40+) fails with "DLL initialization routine failed". Leave that copy out: winrt then uses the current
# msvcp140.dll bundled at the top of _internal, like everything else.
_OLD_CRT = {os.path.normcase(os.path.join("winrt", n)) for n in ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
                                                                 "vcruntime140.dll", "vcruntime140_1.dll")}
a.binaries = [b for b in a.binaries if os.path.normcase(b[0]) not in _OLD_CRT]
a.datas = [d for d in a.datas if os.path.normcase(d[0]) not in _OLD_CRT]
pyz = PYZ(a.pure)
# The start-up picture shown while the exe unpacks; app.py closes it with pyi_splash when the window is up.
splash = Splash(os.path.join(ROOT, "nobadfind", "ui", "brand", "splash.png"), binaries=a.binaries, datas=a.datas,
                text_pos=None, always_on_top=False)
exe = EXE(pyz, a.scripts, splash, [], exclude_binaries=True, name="NobadFind", console=False, disable_windowed_traceback=False,
          icon=ICON, version=VERSION if os.path.exists(VERSION) else None)
coll = COLLECT(exe, splash.binaries, a.binaries, a.datas, strip=False, upx=False, name="NobadFind")
