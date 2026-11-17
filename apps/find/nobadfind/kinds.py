"""File kinds, the words people use for them, and which ones have readable text."""
import os

KINDS = {
    "pdf": {".pdf"},
    "document": {".doc", ".docx", ".odt", ".rtf", ".pages", ".wpd"},
    "spreadsheet": {".xls", ".xlsx", ".xlsm", ".ods", ".csv", ".tsv", ".numbers"},
    "slides": {".ppt", ".pptx", ".odp", ".key"},
    "text": {".txt", ".md", ".markdown", ".rst", ".log", ".ini", ".cfg", ".toml", ".yaml", ".yml", ".json",
             ".xml", ".tex", ".org", ".nfo", ".srt", ".vtt"},
    "code": {".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".java", ".kt", ".c", ".h", ".cpp", ".hpp",
             ".cc", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".m", ".scala", ".lua", ".pl", ".r", ".sql",
             ".sh", ".bash", ".ps1", ".psm1", ".bat", ".cmd", ".vb", ".dart", ".html", ".htm", ".css", ".scss",
             ".vue", ".svelte", ".ipynb", ".gradle", ".cmake", ".dockerfile"},
    "email": {".eml", ".mbox", ".msg"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff", ".svg",
              ".raw", ".cr2", ".nef", ".arw", ".dng", ".ico", ".psd"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v", ".flv", ".3gp"},
    "audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".mid"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".cab"},
    "app": {".exe", ".msi", ".msix", ".appx", ".lnk", ".url"},
    "ebook": {".epub", ".mobi", ".azw3", ".djvu"},
}
_EXT = {e: k for k, exts in KINDS.items() for e in exts}

# Words in a question that mean a kind of file.
WORDS = {
    "pdf": "pdf", "pdfs": "pdf",
    "doc": "document", "docs": "document", "document": "document", "documents": "document", "word": "document",
    "letter": "document", "essay": "document", "report": None, "resume": None, "cv": None,
    "excel": "spreadsheet", "spreadsheet": "spreadsheet", "spreadsheets": "spreadsheet", "sheet": "spreadsheet",
    "csv": "spreadsheet", "xlsx": "spreadsheet",
    "slides": "slides", "slide": "slides", "presentation": "slides", "powerpoint": "slides", "ppt": "slides",
    "deck": "slides",
    "note": "text", "notes": "text", "txt": "text", "markdown": "text",
    "code": "code", "script": "code", "scripts": "code", "source": "code", "program": "code",
    "email": "email", "emails": "email", "mail": "email", "message": None,
    "photo": "image", "photos": "image", "picture": "image", "pictures": "image", "image": "image",
    "images": "image", "screenshot": "image", "screenshots": "image", "pic": "image", "pics": "image",
    "video": "video", "videos": "video", "movie": "video", "clip": "video", "recording": None,
    "song": "audio", "songs": "audio", "music": "audio", "audio": "audio", "mp3": "audio", "podcast": "audio",
    "zip": "archive", "archive": "archive", "archives": "archive",
    "installer": "app", "setup": "app", "exe": "app", "program files": "app",
    "ebook": "ebook", "book": "ebook", "epub": "ebook",
}

# Apps people name when they mean "the files I made with it": "photoshop files", "my blender projects".
# (Word, Excel and PowerPoint are kinds above.) Names that are also ordinary words (AMBIGUOUS_APPS) only count
# when a word like "files" or "project" follows: "outlook files" yes, "economic outlook report" no.
APPS = {
    "photoshop": {".psd", ".psb"}, "illustrator": {".ai", ".eps"}, "indesign": {".indd", ".idml"},
    "premiere": {".prproj"}, "lightroom": {".lrcat"}, "gimp": {".xcf"}, "krita": {".kra"},
    "inkscape": {".svg"}, "affinity": {".afphoto", ".afdesign", ".afpub"}, "figma": {".fig"},
    "blender": {".blend"}, "autocad": {".dwg", ".dxf"}, "sketchup": {".skp"}, "solidworks": {".sldprt", ".sldasm"},
    "fusion360": {".f3d"}, "kicad": {".kicad_pcb", ".kicad_sch", ".kicad_pro"}, "audacity": {".aup3", ".aup"},
    "onenote": {".one"}, "msaccess": {".accdb", ".mdb"}, "visio": {".vsdx", ".vsd"}, "outlook": {".msg", ".pst"},
    "acrobat": {".pdf"}, "godot": {".tscn", ".godot"},
    "jupyter": {".ipynb"}, "obsidian": {".md"}, "ableton": {".als"}, "flstudio": {".flp"}, "garageband": {".band"},
    "davinci": {".drp"}, "aftereffects": {".aep"}, "keynote": {".key"},
}

AMBIGUOUS_APPS = {"outlook", "keynote", "affinity", "premiere", "blender", "figma", "obsidian", "acrobat", "krita",
                  "davinci", "godot", "jupyter", "ableton", "audacity", "gimp", "inkscape"}
APP_CUES = {"file", "files", "project", "projects", "document", "documents", "doc", "docs", "design", "designs",
            "drawing", "drawings", "model", "models", "scene", "scenes", "notebook", "notebooks", "vault",
            "session", "sessions", "export", "exports", "work", "stuff", "mail", "mails", "emails", "message",
            "messages", "presentation", "presentations", "deck", "decks", "catalog", "track", "tracks"}

READABLE = {"pdf", "document", "spreadsheet", "slides", "text", "code", "email", "ebook"}
READABLE_EXT = {".docx", ".odt", ".rtf", ".xlsx", ".xlsm", ".ods", ".csv", ".tsv", ".pptx", ".odp", ".pdf", ".eml",
                ".mbox", ".epub"} | KINDS["text"] | KINDS["code"]


def kind_of(name, is_dir=False):
    if is_dir:
        return "folder"
    return _EXT.get(os.path.splitext(name)[1].lower(), "other")


def readable(ext):
    return ext.lower() in READABLE_EXT
