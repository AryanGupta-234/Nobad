"""Constants and default settings for NOBAD Find."""
import os

APP_NAME = "NOBAD Find"
APP_VER = "0.6.2"

# NOBAD Find runs as the normal user, so its data lives in the user's own profile (not readable by other users).
DATA_DIR = os.environ.get("NOBAD_FIND_DATA_DIR") or os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "NOBAD", "Find")
DB_PATH = os.path.join(DATA_DIR, "index.db")
KEY_PATH = os.path.join(DATA_DIR, "index.key")          # the database key, protected with Windows DPAPI
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
LOG_PATH = os.path.join(DATA_DIR, "find.log")
MODEL_DIR = os.path.join(DATA_DIR, "model")

# Meaning search model: all-MiniLM-L6-v2 (Apache-2.0), ONNX export, pinned to one revision and verified by SHA-256.
MODEL_REV = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL_FILES = {   # local name: (path in the repository, size in bytes, SHA-256)
    "model.onnx": ("onnx/model_quint8_avx2.onnx", 23046789,
                   "b941bf19f1f1283680f449fa6a7336bb5600bdcd5f84d10ddc5cd72218a0fd21"),
    "tokenizer.json": ("tokenizer.json", 466247,
                       "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037"),
}
MODEL_URL = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/{rev}/{path}"
MODEL_DIM = 384

# Paths that are never indexed, whatever the settings say: secrets, other people's data and system noise.
ALWAYS_EXCLUDE_NAMES = {
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", "$recycle.bin", "system volume information",
    "windowsapps", "winsxs", "node_modules", "__pycache__", ".git", ".svn", ".hg", ".venv", "venv",
    ".cache", "cache", "cache2", "code cache", "gpucache", "temp", "tmp", "$windows.~bt", "$windows.~ws",
    "1password", "bitwarden", "keepass", "keepassxc", "lastpass", "dashlane", "nobad",
}
ALWAYS_EXCLUDE_EXT = {".kdbx", ".kdb", ".pem", ".key", ".pfx", ".p12", ".ppk", ".gpg", ".asc", ".ovpn", ".conf"}

DEFAULTS = {
    "roots": [],                    # empty = the user's profile folders plus every other fixed drive
    "exclude": [],                  # extra folders never to index
    "content": True,                # read text inside documents
    "content_max_mb": 25,           # skip reading files bigger than this
    "semantic": False,              # meaning search (needs the model download, below)
    "photo_meaning": False,         # find photos by what's in them (needs the photo model download)
    "allow_photo_model_download": False,   # Hugging Face, once, about 211 MB, when you ask for it
    "allow_model_download": False,  # the only outbound connection: Hugging Face, once, when you ask for it
    "src_mail": True,               # .eml / .mbox files found while indexing
    "ocr": True,                    # words in photos, screenshots and scanned PDFs (Windows' own OCR)
    "index_removable": False,       # USB sticks, SD cards and external drives while they're plugged in
    "index_network": False,         # mapped network drives (your own network; slow on big shares)
    "pause_on_battery": True,
    "pause_fullscreen": True,       # old: replaced by games_mode, kept so a downgrade still reads it
    "games_mode": "smart",          # smart | always | off: what to do while a game is running
    "keep_background": False,
    "bar": True,
    "bar_hotkey": "ctrl+alt+space",
    "pause_on_call": True,          # while the microphone or camera is in use
    "workers": 0,                   # 0 = pick from the CPU
    "hotkey": "win+shift+space",
    "autostart": False,
    "hide_after_open": False,       # Enter opens the file and keeps the window up (on: hide it, like a launcher)
    "wsearch_prev": "",             # Windows Search start type saved before NOBAD Find turned it off
    "theme": "dark",
    "glass": True,                  # see-through acrylic window on Windows 11 (follows Windows' transparency switch)
}
