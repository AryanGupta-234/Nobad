"""Read the text inside files. Runs in worker processes (see indexer.py) with hard size limits.

Every file is untrusted: Office/ODF/EPUB files are zips (checked for zip bombs), XML is parsed with the standard
library's expat (no external entities), and nothing here ever executes or opens a file in another program.
"""
import email
import email.policy
import html.parser
import io
import mailbox
import os
import re
import xml.etree.ElementTree as ET
import zipfile

MAX_CHARS = 2_000_000          # text kept per file
MAX_ZIP_MEMBER = 64 * 1024 * 1024
MAX_ZIP_TOTAL = 256 * 1024 * 1024
MAX_ZIP_RATIO = 200            # uncompressed / compressed
CHUNK = 900
OVERLAP = 120


class SkipFile(Exception):
    """The file can't or shouldn't be read (too big, encrypted, not really text...)."""


# ---------- plain text ----------
def decode_bytes(b):
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", "replace")
    if b.startswith((b"\xff\xfe", b"\xfe\xff")):
        return b.decode("utf-16", "replace")
    sample = b[:8192]
    if sample.count(b"\x00") > len(sample) // 10:
        # UTF-16 without a BOM looks like every other byte is zero; anything else with NULs is binary
        if len(sample) > 1 and sample[1::2].count(0) > len(sample) // 3:
            return b.decode("utf-16-le", "replace")
        raise SkipFile("binary")
    ctrl = sum(1 for c in sample if c < 32 and c not in (9, 10, 12, 13))
    if sample and ctrl > len(sample) // 20:
        raise SkipFile("binary")
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1252", "replace")


def read_text(path, limit):
    with open(path, "rb") as f:
        return decode_bytes(f.read(limit))


class _HTML(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "title"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def html_text(s):
    p = _HTML()
    try:
        p.feed(s)
        p.close()
    except Exception:
        pass
    return "".join(p.out)


_RTF_CTRL = re.compile(r"\\[a-z]+-?\d* ?|\\'[0-9a-f]{2}|[{}]", re.I)


def rtf_text(s):
    s = re.sub(r"\{\\\*[^{}]*\}", "", s)
    return _RTF_CTRL.sub("", s.replace("\\par", "\n"))


# ---------- zip-based formats ----------
def _safe_zip(path):
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise SkipFile(f"bad zip: {e}")
    total = 0
    for i in z.infolist():
        if i.flag_bits & 0x1:
            raise SkipFile("password protected")
        total += i.file_size
        if i.file_size > MAX_ZIP_MEMBER or total > MAX_ZIP_TOTAL:
            raise SkipFile("too big inside")
        if i.compress_size and i.file_size / i.compress_size > MAX_ZIP_RATIO:
            raise SkipFile("suspicious compression")
    return z


def _xml_text(data, para_tags=()):
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return ""
    out = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in para_tags:
            out.append("\n")
        if el.text and tag in ("t", "p", "span", "h", "a", "s", "v", "is", "si") or (el.text and not para_tags):
            out.append(el.text)
        if tag == "tab":
            out.append("\t")
    return "".join(out)


def _ordered(names, prefix, suffix=".xml"):
    def num(n):
        m = re.search(r"(\d+)" + re.escape(suffix) + "$", n)
        return int(m.group(1)) if m else 0
    return sorted((n for n in names if n.startswith(prefix) and n.endswith(suffix)), key=num)


def office_text(path, ext):
    with _safe_zip(path) as z:
        names = z.namelist()
        parts = []
        if ext == ".docx":
            for n in ["word/document.xml"] + _ordered(names, "word/footnotes") + _ordered(names, "word/header") \
                    + _ordered(names, "word/footer"):
                if n in names:
                    parts.append(_xml_text(z.read(n), ("p", "br")))
        elif ext == ".pptx":
            for n in _ordered(names, "ppt/slides/slide") + _ordered(names, "ppt/notesSlides/notesSlide"):
                parts.append(_xml_text(z.read(n), ("p",)))
        elif ext in (".xlsx", ".xlsm"):
            if "xl/sharedStrings.xml" in names:
                parts.append(_xml_text(z.read("xl/sharedStrings.xml"), ("si",)))
            for n in _ordered(names, "xl/worksheets/sheet"):
                root = _try_xml(z.read(n))
                if root is None:
                    continue
                for el in root.iter():
                    if el.tag.endswith("}t") and el.text:           # inline strings
                        parts.append(el.text + " ")
                    elif el.tag.endswith("}v") and el.text and re.match(r"^-?\d[\d.,E+-]*$", el.text) is None:
                        parts.append(el.text + " ")
        elif ext in (".odt", ".ods", ".odp"):
            if "content.xml" in names:
                parts.append(_xml_text(z.read("content.xml"), ("p", "h", "table-row")))
        elif ext == ".epub":
            for n in sorted(names):
                if n.lower().endswith((".xhtml", ".html", ".htm")):
                    parts.append(html_text(z.read(n).decode("utf-8", "replace")))
        meta = "docProps/core.xml" if "docProps/core.xml" in names else ("meta.xml" if "meta.xml" in names else None)
        if meta:
            parts.insert(0, _xml_text(z.read(meta)) + "\n")
        return "\n".join(parts)


def _try_xml(data):
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


# ---------- PDF ----------
def pdf_text(path, max_pages=400):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SkipFile("PDF reader not installed")
    try:
        r = PdfReader(path, strict=False)
        if r.is_encrypted:
            try:
                if not r.decrypt(""):
                    raise SkipFile("password protected")
            except Exception:
                raise SkipFile("password protected")
        out = []
        meta = r.metadata or {}
        for k in ("/Title", "/Subject", "/Author", "/Keywords"):
            v = meta.get(k)
            if isinstance(v, str):
                out.append(v)
        for i, page in enumerate(r.pages):
            if i >= max_pages or sum(map(len, out)) > MAX_CHARS:
                break
            try:
                out.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(out)
    except SkipFile:
        raise
    except Exception as e:
        raise SkipFile(f"unreadable PDF: {type(e).__name__}")


# ---------- e-mail ----------
def _message_text(msg):
    head = []
    for h in ("subject", "from", "to", "cc", "date"):
        v = msg.get(h)
        if v:
            head.append(f"{h.capitalize()}: {v}")
    body = []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        if part.get_content_disposition() == "attachment":
            fn = part.get_filename()
            if fn:
                body.append(f"[attachment: {fn}]")
            continue
        if ctype in ("text/plain", "text/html"):
            try:
                payload = part.get_payload(decode=True) or b""
                cs = part.get_content_charset() or "utf-8"
                txt = payload.decode(cs, "replace")
            except (LookupError, AssertionError):
                txt = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
            body.append(html_text(txt) if ctype == "text/html" else txt)
    return "\n".join(head) + "\n\n" + "\n".join(body)


def eml_text(path, limit):
    with open(path, "rb") as f:
        msg = email.message_from_bytes(f.read(limit), policy=email.policy.compat32)
    return _message_text(msg)


def mbox_text(path, limit):
    out, size = [], 0
    box = mailbox.mbox(path, create=False)
    try:
        for msg in box:
            t = _message_text(msg)
            out.append(t)
            size += len(t)
            if size > MAX_CHARS or size > limit:
                break
    finally:
        box.close()
    return "\n\n---\n\n".join(out)


# ---------- notebooks ----------
def ipynb_text(path, limit):
    import json
    try:
        nb = json.loads(read_text(path, limit))
    except ValueError:
        raise SkipFile("bad notebook")
    out = []
    for cell in nb.get("cells", []) if isinstance(nb, dict) else []:
        src = cell.get("source", "") if isinstance(cell, dict) else ""
        out.append("".join(src) if isinstance(src, list) else str(src))
    return "\n\n".join(out)


# ---------- entry point ----------
def extract(path, ext, max_bytes):
    """Return the text of one file (may be empty). Raises SkipFile for files that can't be read."""
    ext = ext.lower()
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise SkipFile(f"gone: {e.strerror}")
    if size > max_bytes:
        raise SkipFile("too big")
    if ext in (".docx", ".pptx", ".xlsx", ".xlsm", ".odt", ".ods", ".odp", ".epub"):
        text = office_text(path, ext)
    elif ext == ".pdf":
        text = pdf_text(path)
    elif ext == ".eml":
        text = eml_text(path, max_bytes)
    elif ext == ".mbox":
        text = mbox_text(path, max_bytes)
    elif ext == ".ipynb":
        text = ipynb_text(path, max_bytes)
    elif ext in (".html", ".htm"):
        text = html_text(read_text(path, max_bytes))
    elif ext == ".rtf":
        text = rtf_text(read_text(path, max_bytes))
    else:
        text = read_text(path, max_bytes)
    return clean(text)[:MAX_CHARS]


_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n\s*\n+")


def clean(text):
    text = text.replace("\x00", "")
    return _NL.sub("\n\n", _WS.sub(" ", text)).strip()


def chunks(text, size=CHUNK, overlap=OVERLAP):
    """Split text into overlapping pieces, preferring to cut at a paragraph or sentence end."""
    if not text:
        return []
    out, i, n = [], 0, len(text)
    while i < n:
        end = min(n, i + size)
        if end < n:
            cut = max(text.rfind("\n", i + size // 2, end), text.rfind(". ", i + size // 2, end))
            if cut > i:
                end = cut + 1
        piece = text[i:end].strip()
        if piece:
            out.append(piece)
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return out


def work(job):
    """Worker-process entry: (file_id, path, ext, mtime, max_bytes) -> (file_id, mtime, chunks, error)."""
    file_id, path, ext, mtime, max_bytes = job
    try:
        return file_id, mtime, chunks(extract(path, ext, max_bytes)), None
    except SkipFile as e:
        return file_id, mtime, [], str(e)[:200]
    except MemoryError:
        return file_id, mtime, [], "too big"
    except Exception as e:          # one bad file must never stop the indexer
        return file_id, mtime, [], f"error: {type(e).__name__}"


def init_worker():
    from . import winapi
    winapi.background_mode()


__all__ = ["extract", "chunks", "work", "init_worker", "SkipFile", "decode_bytes", "io"]
