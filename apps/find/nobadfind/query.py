"""Understand a plain-language question: words to look for, file kinds and a time range.

    "rent pdf from last week"            -> text "rent", kind pdf, last week
    "photos from the beach in march"     -> text "beach", kind image, March (most recent)
    "budget.xlsx"                        -> text "budget.xlsx"
    '"exact phrase" notes 3 days ago'    -> phrase "exact phrase", kind text, 3 days ago
"""
import datetime as dt
import ntpath
import re
import unicodedata
from dataclasses import dataclass, field

from .kinds import AMBIGUOUS_APPS, APP_CUES, APPS, WORDS

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
DAYS = {d: i for i, d in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
DAYS.update({d[:3]: i for d, i in list(DAYS.items())})
NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
       "nine": 9, "ten": 10, "couple": 2, "few": 3}
STOP = {"the", "a", "an", "my", "i", "me", "that", "this", "those", "these", "file", "files", "about", "with",
        "from", "in", "on", "at", "of", "for", "to", "it", "was", "is", "some", "where", "which", "find", "show",
        "opened", "saved", "made", "created", "edited", "changed", "wrote", "had", "got", "downloaded", "and",
        "or", "there", "somewhere", "something", "thing", "called", "named", "one", "around", "ago", "during",
        "last", "past", "since", "before", "after", "between", "earlier", "recently", "recent", "any", "all",
        "did", "do", "when", "what", "think", "maybe", "like", "kind", "sort", "have", "has", "may", "might",
        "could", "would", "should", "can", "be", "been", "were", "are", "am", "put", "kept", "remember", "used",
        "use", "look", "looking", "need", "want", "please", "where's", "whats", "im", "i'm", "we", "our", "your",
        "every", "everything"}
# Words that ask for something ("list all pdf"). Dropped when the question has something else to go on; kept
# as words to look for when they're all there is ("list" alone finds list.txt).
ASKING = {"list", "give", "get", "search", "inside", "folder", "folders", "located", "stored", "saved", "lying",
          "save", "store", "keep",                                  # "what did i save today"
          # linking words before what is inside: "pdf in downloads having appreciation"
          "having", "containing", "contains", "contain", "mentioning", "mentions", "mention", "including",
          "includes", "include", "says", "say", "saying", "regarding", "word", "words", "text", "content"}

# Words that hint at a kind without saying it: "letter" may be a .docx or a .txt. When the kind finds nothing,
# search asks again with them as words (search.search, "No file of that kind matched").
SOFT_KINDS = {"letter", "essay", "book", "clip", "deck", "program", "source", "sheet", "script", "scripts"}

# The user's own folders: "in my downloads", "download folder pdf", "on the desktop", "in documents folder"
_FOLDER_WORDS = {"download": "downloads", "downloads": "downloads", "desktop": "desktop", "documents": "documents",
                 "document": "documents", "docs": "documents", "pictures": "pictures", "picture": "pictures",
                 "photos": "pictures", "videos": "videos", "video": "videos", "music": "music"}
_FW = "(" + "|".join(sorted(_FOLDER_WORDS, key=len, reverse=True)) + ")"
FOLDER_PATTERNS = [
    r"\b(?:in|from|on|inside) (?:my |the )?" + _FW + r" folder\b",      # "in my downloads folder"
    r"\b" + _FW + r" folder\b",                                          # "download folder pdf"
    r"\b(?:in|from|inside) (?:my |the )?(downloads?|documents|desktop)\b",   # "in my downloads"
    r"\bon (?:my |the )?(desktop)\b",                                    # "on the desktop"
    # "songs in music", "photos in pictures", "wedding in videos": only at the end of the phrase, since these are
    # also ordinary words ("notes in music theory" is about music theory)
    r"\b(?:in|from|inside) (?:my |the )?(pictures|videos|music)(?=\s*$|\s+(?:from|in|on|at|last|this|with|and|or|"
    r"before|after|since|during|yesterday|today|which|that|over|under|bigger|smaller|newest|oldest|largest)\b)",
]


@dataclass
class Query:
    raw: str
    terms: list = field(default_factory=list)       # words to search for
    phrases: list = field(default_factory=list)     # "exact phrases"
    kinds: set = field(default_factory=set)
    exts: set = field(default_factory=set)
    t0: float = None                                # time range (unix seconds), on modified/created time
    t1: float = None
    when: str = ""                                  # how the time was understood, for the UI
    apps: set = field(default_factory=set)          # "photoshop files" -> {"photoshop"}; their extensions below
    app_exts: set = field(default_factory=set)
    place: str = ""                                 # "removable" | "network" | "fixed" | "E:" | "label:<name>"
    drives: list = field(default_factory=list)      # the drives the place is matched against
    folder: str = ""                                # "downloads" | "desktop" | "documents" | "pictures" | ...
    path: str = ""                                  # a folder typed in the question: C:\Work\Taxes, \\nas\share
    here: bool = False                              # "here", "this folder": the Explorer folder you came from
    min_size: int = None                            # bytes
    max_size: int = None
    size_label: str = ""
    sort: str = ""                                  # "" (best match) | "newest" | "oldest" | "largest" | "name"
    notes: list = field(default_factory=list)       # things worth telling the user ("here" without a folder)
    dropped: list = field(default_factory=list)     # Hinglish linking words left out ("ko", "par"), see search
    romanized: bool = False                         # Hinglish was read (the focus, or it was clearly Hinglish)
    # 0.8.5 smart search (understand.py): what each filter was read from, folders named in the question, and the
    # words that describe what's wanted, in their order ("2 boys" of "2 boys in an image in downloads")
    cuts: list = field(default_factory=list)        # [(part, phrase as read)], part: path|here|size|sort|time|...
    dirs: list = field(default_factory=list)        # indexed folders named in the question ("in projects")
    dir_label: str = ""                             # that folder's name as the index has it ("Projects")
    meaning: str = ""                               # the description left over, for photo meaning
    soft: list = field(default_factory=list)        # SOFT_KINDS words read as a kind (search may read them again)

    @property
    def text(self):
        return " ".join(self.phrases + self.terms)

    def all_exts(self):
        return self.exts | self.app_exts

    def place_label(self):
        p = self.place
        if p.startswith("label:"):
            return "on " + p[6:].upper()
        return {"removable": "on USB and external drives", "network": "on network drives",
                "fixed": "on this PC's own drives"}.get(p, f"on {p}" if p else "")

    def understood(self):
        out = []
        if self.kinds:
            out.append(", ".join(sorted(self.kinds)))
        if self.apps:
            out.append(", ".join(f"{a} files" for a in sorted(self.apps)))
        if self.exts:
            out.append(", ".join(sorted(self.exts)))
        if self.when:
            out.append(self.when)
        if self.place:
            out.append(self.place_label())
        if self.folder:
            out.append(f"in {self.folder.capitalize()}")
        if self.path:
            out.append("in " + self.path)
        if self.dirs:
            out.append("in " + self.dir_label)
        if self.size_label:
            out.append(self.size_label)
        if self.sort:
            out.append({"newest": "newest first", "oldest": "oldest first", "largest": "largest first",
                        "name": "by name"}[self.sort])
        return out

    def has_filters(self):
        return bool(self.kinds or self.all_exts() or self.t0 is not None or self.place or self.folder or self.path
                    or self.dirs or self.min_size is not None or self.max_size is not None or bool(self.sort))


# Where a file is: "on my usb stick", "on the network drive", "on d:", "on drive e", "on SANDISK".
_ON = r"\b(?:on|from|in|off) (?:my |the |a |an |this |that )?"
# A place must end the phrase ("notes in my computer science class" is not about a drive).
_END = r"(?=\s*$|\s+(?:from|in|on|at|last|this|that|with|about|and|or|before|after|since|during|yesterday|today|"
_END += r"ago|recently|around|which|where|when)\b)"
PLACES = [
    (_ON + r"(?:usb(?: drive| stick| key| disk| flash drive)?|flash ?drive|pen ?drive|thumb ?drive|memory stick|"
     r"sd card|memory card|(?:external|portable|backup) (?:drive|disk|hard ?drive|hdd|ssd))s?" + _END, "removable"),
    (_ON + r"(?:network (?:drive|share|folder)|nas|shared drive|file server)s?" + _END, "network"),
    (r"\b(?:on|from|in) (?:my|this) (?:pc|computer|laptop)" + _END, "fixed"),
]
_DRIVE = re.compile(_ON + r"(?:drive ([b-z])\b|([a-z]):(?:\\)?(?: drive)?(?=\s)|([b-z]) drive\b)")
# Two-word app names, joined before the words are read
APP_PHRASES = {"after effects": "aftereffects", "fusion 360": "fusion360", "fl studio": "flstudio",
               "ms access": "msaccess", "microsoft access": "msaccess", "davinci resolve": "davinci"}


def _day(d):
    return dt.datetime.combine(d, dt.time.min)


def _ts(x):
    return x.timestamp()


def _month_range(year, month):
    start = dt.datetime(year, month, 1)
    end = dt.datetime(year + (month == 12), month % 12 + 1, 1)
    return start, end


def _norm(p):
    """C:/Work -> C:\\Work (the index stores Windows paths); C:\\ stays C:\\; \\\\nas\\share stays UNC."""
    return ntpath.normpath(p)


def _take_path(s, is_dir):
    """Find a folder path in the question; returns (path, rest of the text). Paths may contain spaces: the
    longest run of words that is a real folder wins ("pdf in C:\\My Files\\Tax 2024 from march")."""
    if not is_dir:
        return "", s
    for m in re.finditer(r'"((?:[a-zA-Z]:|\\\\)[^"]*)"', s):              # a quoted path
        p = m.group(1).rstrip("\\/ ")
        if p and is_dir(p + ("\\" if len(p) == 2 else "")):
            return _norm(p + ("\\" if len(p) == 2 else "")), s[:m.start()] + " " + s[m.end():]
    m = re.search(r'(?:(?<=\s)|^)(?:[a-zA-Z]:[\\/]|\\\\[^\\/\s]+[\\/])', s)    # C:\ or \\server\
    if not m:
        return "", s
    words = s[m.start():].split(" ")
    for n in range(min(len(words), 8), 0, -1):             # a folder name of up to 8 words
        cand = " ".join(words[:n]).rstrip("\\/ .,;")
        if len(cand) == 2:
            cand += "\\"
        if cand and is_dir(cand):
            return _norm(cand), s[:m.start()] + " " + " ".join(words[n:])
    return None, s[:m.start()] + " " + " ".join(words[1:])        # looks like a path, but isn't a folder


# ---------- Hindi and Hinglish (Hindi typed in Latin letters) ----------
# The filters are read the same way as in English: each Hindi or Hinglish phrase becomes the English one before the
# question is parsed ("पिछले हफ्ते की पीडीएफ" -> "last week pdf", "pichle hafte ki rent wali pdf" -> "last week rent
# pdf"). Linking words (का, की, वाली, wala, mein...) are left out like "the" and "of". Devanagari letters include
# their vowel signs, so a Hindi word is one word ("बिजली"), not pieces.
WORD = r"[\w\u0900-\u097F.\-+#]+"
_B, _E = r"(?<![\w\u0900-\u097F])", r"(?![\w\u0900-\u097F])"
# Each rule: (Devanagari form, romanized form, English). Devanagari is always read; the romanized forms only when
# the language focus is Hindi or many languages, or when the question is clearly Hinglish (hinglish() below): one
# Hinglish-looking word ("kal ho naa ho", "bare files", "kal.txt") stays an ordinary word.
_PICHLE = (r"(?:पिछले|पिछला|पिछली)", r"(?:pich+h?l[ae]|pic+h?h?l[ae])")
_IS = (r"इस", r"is")
_HAFTA = (r"(?:हफ्ते|हफ़्ते|हफ्ता|हफ़्ता|सप्ताह)", r"(?:haf+t[ae])")
_MAHINA = (r"(?:महीने|महीना|माह)", r"(?:mahin[ae])")
_SAAL = (r"(?:साल|वर्ष)", r"(?:saa?l)")
_PEHLE = (r"पहले", r"(?:pe?h?le|pahle)")
_BADA = (r"(?:बड़ी|बड़े|बड़ा|बडी|बडे|बडा)", r"(?:badi|bade|bada)")
_CHHOTA = (r"(?:छोटी|छोटे|छोटा)", r"(?:chh?oti|chh?ote|chh?ota)")
_SE = (r"से", r"se")
_FILES = (r"(?:फाइलें|फ़ाइलें|फाइल|फ़ाइल)", r"(?:files?)")
_MEIN = (r"(?:में|के अंदर)", r"(?:mein|me|ke andar)")


def _both(*parts):
    """(Devanagari, romanized) for a rule made of parts; a part is a pair or a plain string used in both."""
    dev = "".join(p[0] if isinstance(p, tuple) else p for p in parts)
    rom = "".join(p[1] if isinstance(p, tuple) else p for p in parts)
    return dev, rom


_NUM = r"(\d+)"
_SIZE_N = r"(\d+(?:\.\d+)?) ?(gb|mb|kb) "
HINDI_RULES = [
    # times
    (_both(_PICHLE, " ", _HAFTA), "last week"), (_both(_IS, " ", _HAFTA), "this week"),
    (_both(_PICHLE, " ", _MAHINA), "last month"), (_both(_IS, " ", _MAHINA), "this month"),
    (_both(_PICHLE, " ", _SAAL), "last year"), (_both(_IS, " ", _SAAL), "this year"),
    (_both(_NUM, " ", (r"दिन", r"din"), " ", _PEHLE), r"\1 days ago"),
    (_both(_NUM, " ", _HAFTA, " ", _PEHLE), r"\1 weeks ago"),
    (_both(_NUM, " ", _MAHINA, " ", _PEHLE), r"\1 months ago"),
    ((r"आज", r"aaj"), "today"), ((r"कल", r"kal"), "yesterday"),
    # sizes
    (_both(_SIZE_N, _SE, " ", _BADA), r"bigger than \1 \2"), (_both(_SIZE_N, _SE, " ", _CHHOTA), r"smaller than \1 \2"),
    (_both(_BADA, " ", _FILES), "big files"),
    # the user's folders
    (_both((r"(?:डाउनलोड्स|डाउनलोड)", r"(?:downloads?)"), " ", _MEIN), "in downloads"),
    (_both((r"डेस्कटॉप", r"desktop"), " ", (r"(?:पर|में)", r"(?:par|mein)")), "on desktop"),
    (_both((r"(?:डॉक्यूमेंट्स|डॉक्यूमेंट)", r"(?:documents?)"), " ", _MEIN), "in documents"),
    # the folder in English letters with a Hindi linking word ("downloads में बिजली बिल")
    ((r"(?:downloads?) (?:में|के अंदर)", None), "in downloads"), ((r"desktop (?:पर|में)", None), "on desktop"),
    ((r"(?:documents?) (?:में|के अंदर)", None), "in documents"),
    ((r"(?:डाउनलोड्स|डाउनलोड)", None), "downloads"), ((r"डेस्कटॉप", None), "desktop"),
    ((r"(?:फोल्डर|फ़ोल्डर)", None), "folder"),
    # kinds
    ((r"(?:फोटो|फ़ोटो|फोटोज़|फोटोज|तस्वीरें|तस्वीर|चित्र)", r"(?:tasveer(?:ein|en)?)"), "photos"),
    ((r"(?:पीडीएफ|पी डी एफ)", None), "pdf"), ((r"(?:वीडियो|विडियो)", None), "videos"), ((r"(?:ईमेल|मेल)", None), "email"),
    ((r"(?:दस्तावेज़|दस्तावेज|डॉक्यूमेंट)", None), "document"), ((_FILES[0], None), "files"),
    # "having / containing"
    ((r"(?:जिसमें|जिसमे)", r"(?:jisme|jismein|jis ?mein)"), "containing"),
]


def _compile(p):
    return re.compile(_B + unicodedata.normalize("NFC", p) + _E) if p else None


HINDI_RULES = [(_compile(dev), _compile(rom), english) for (dev, rom), english in HINDI_RULES]
HINDI_STOP_DEV = {"का", "की", "के", "को", "में", "से", "पर", "और", "है", "हैं", "था", "थी", "थे", "वाला", "वाली",
                  "वाले", "एक", "मेरा", "मेरी", "मेरे", "वो", "वह", "यह", "ये", "कहाँ", "कहां", "कौन", "क्या", "भी",
                  "तो", "ही"}
HINDI_STOP_ROMAN = {"wala", "wali", "wale", "vala", "vali", "vale", "ka", "ki", "ke", "ko", "mein", "se", "aur",
                    "hai", "hain", "tha", "thi", "mera", "meri", "mere", "wo", "woh", "yeh", "ye", "kahan", "kaha",
                    "kya", "bhi", "hi", "ek", "par"}
# Words that only Hinglish uses (not English words too: "bare", "par", "is", "hi", "to", "me" are left out)
HINGLISH_MARKERS = {"pichle", "pichhle", "picchle", "pichla", "hafte", "hafta", "mahine", "mahina", "saal", "aaj",
                    "kal", "din", "pehle", "pahle", "wala", "wali", "wale", "vala", "vali", "ki", "ka", "ke", "mein",
                    "jisme", "jismein", "badi", "bada", "chhoti", "choti", "tasveer", "kahan", "kya", "hai", "aur",
                    "mera", "meri"}
_KIND_OR_TIME = {"pdf", "pdfs", "photo", "photos", "file", "files", "video", "videos", "doc", "docs", "document",
                 "bill", "receipt", "today", "yesterday", "week", "month", "year", "downloads", "download",
                 "desktop", "documents"}
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def hinglish(low):
    """Clearly Hinglish: two different marker words, or a marker next to a kind or time word ("kal ka bill",
    "pichle hafte ki pdf", "badi files")."""
    words = re.findall(r"[a-z]+", low)
    marks = {w for w in words if w in HINGLISH_MARKERS}
    if len(marks) >= 2:
        return True
    return any(w in HINGLISH_MARKERS and ((i > 0 and words[i - 1] in _KIND_OR_TIME) or
                                          (i + 1 < len(words) and words[i + 1] in _KIND_OR_TIME))
               for i, w in enumerate(words))


def hindi_to_english(low, romanized=False):
    """Hindi (and, with romanized, Hinglish) filter words -> the English the parser reads; other words stay."""
    low = unicodedata.normalize("NFC", low).translate(_DEVANAGARI_DIGITS)
    for dev, rom, english in HINDI_RULES:
        if dev is not None:
            low = dev.sub(english, low)
        if romanized and rom is not None:
            low = rom.sub(english, low)
    return low


SIZE_UNITS = {"bytes": 1, "kb": 1024, "mb": 1 << 20, "gb": 1 << 30}
_SIZE = r"(\d+(?:\.\d+)?) ?(gb|mb|kb|bytes)\b"            # a real unit: "less than 5 m" is not guessed at
# "big files", "large photos", "small pdfs": what "big" means for each kind, in MB (the rest: 100 MB)
_SIZE_NOUNS = "|".join(sorted({"file", "files", "ones", "folder", "folders"} |
                              {w for w, k in WORDS.items() if k and " " not in w}, key=len, reverse=True))
_BIG_MB = {"image": 10, "pdf": 20, "document": 20, "spreadsheet": 20, "slides": 50, "text": 10, "code": 10,
           "email": 20, "audio": 50, "ebook": 50}


def parse(text, now=None, labels=(), is_dir=None, times=True, romanized=False, find_folder=None, soft_kinds=True):
    """labels: names of drives this PC knows ("SANDISK"), so "on sandisk" means that drive.
    is_dir: checks whether a typed path is a real folder (so "C:\\Work" in a question is understood).
    find_folder: words -> (folder name, [paths]) of indexed folders with that name ("notes in projects"), or None.
    soft_kinds=False: words that only hint at a kind (SOFT_KINDS: "letter", "essay") are words to look for."""
    now = now or dt.datetime.now()
    q = Query(raw=text)
    s = text.strip()

    # a folder path first (it may be quoted, and may contain spaces)
    q.path, s = _take_path(s, is_dir)
    if q.path is None:
        q.path = ""
        q.notes.append("That path isn't a folder on this PC, so it was left out.")
    elif q.path:
        q.cuts.append(("path", q.path))

    # exact phrases
    for m in re.findall(r'"([^"]{1,200})"', s):
        q.phrases.append(m.strip())
    s = re.sub(r'"[^"]*"', " ", s)

    roman = romanized or hinglish(s.lower())     # romanized Hindi: the focus says so, or it's clearly Hinglish
    q.romanized = roman
    low = " " + hindi_to_english(s.lower(), roman) + " "
    # "the word appreciation" says what is inside the file; it doesn't ask for Word documents
    low = re.sub(r" (?:the|a) (?:words?|phrase|term) ", " ", low)

    # "here", "this folder": the folder you were looking at in File Explorer
    # ("here" alone only at the end or after in/from/inside: "here comes the sun" is a song, not a folder)
    m = re.search(r"\b(?:in |from |inside )?(?:this folder|current folder|this directory)\b"
                  r"|\b(?:in |from |inside )(?:right )?here\b|\bhere\s*$", low)
    if m:
        q.here = True
        q.cuts.append(("here", m.group(0).strip()))
        low = low[:m.start()] + " " + low[m.end():]

    # size: "bigger than 100 mb", "under 2mb", "big files"
    m = re.search(r"\b(?:bigger|larger|over|above|more than|greater than|at least)(?: than)? " + _SIZE, low)
    if m:
        q.min_size = int(float(m.group(1)) * SIZE_UNITS[m.group(2)])
        q.size_label = f"over {m.group(1)} {m.group(2).upper()}"
        q.cuts.append(("size", m.group(0).strip()))
        low = low[:m.start()] + " " + low[m.end():]
    m = re.search(r"\b(?:smaller|under|below|less than|at most|up to)(?: than)? " + _SIZE, low)
    if m:
        q.max_size = int(float(m.group(1)) * SIZE_UNITS[m.group(2)])
        q.size_label = (q.size_label + ", " if q.size_label else "") + f"under {m.group(1)} {m.group(2).upper()}"
        q.cuts.append(("size", m.group(0).strip()))
        low = low[:m.start()] + " " + low[m.end():]
    # "big files", "large photos", "small pdfs": the size word goes, the kind word stays for the kinds below.
    # Big depends on the kind (a 10 MB photo is big, a 10 MB video isn't); small is the filter bar's "under 1 MB".
    m = re.search(r"\b(?:big|huge|large|bigger|larger) (" + _SIZE_NOUNS + r")\b", low)
    if m and q.min_size is None:
        mb = _BIG_MB.get(WORDS.get(m.group(1)), 100)
        q.min_size, q.size_label = mb << 20, f"over {mb} MB"
        q.cuts.append(("size", m.group(0).rsplit(' ', 1)[0].strip()))
        low = low[:m.start()] + " " + low[m.end() - len(m.group(0).split()[-1]):]
    m = re.search(r"\b(?:small|tiny|little|smaller) (" + _SIZE_NOUNS + r")\b", low)
    if m and q.max_size is None:
        q.max_size = 1 << 20
        q.size_label = (q.size_label + ", " if q.size_label else "") + "under 1 MB"
        q.cuts.append(("size", m.group(0).rsplit(' ', 1)[0].strip()))
        low = low[:m.start()] + " " + low[m.end() - len(m.group(0).split()[-1]):]

    # order: "newest pdf", "latest", "oldest", "largest"
    for pattern, order in ((r"\b(?:newest|latest|most recent)\b", "newest"), (r"\b(?:oldest|earliest)\b", "oldest"),
                           (r"\b(?:largest|biggest)\b", "largest")):
        m = re.search(pattern, low)
        if m:
            q.sort = order
            q.cuts.append(("sort", m.group(0).strip()))
            low = low[:m.start()] + " " + low[m.end():]
            break

    today = _day(now.date())

    def take(pattern, fn):
        nonlocal low
        m = re.search(pattern, low) if times else None    # times=False: "march" is a word to look for
        if not m or q.t0 is not None:
            return False
        r = fn(m)
        if r is None:
            return False
        (a, b), label = r
        q.t0, q.t1, q.when = _ts(a), _ts(b), label
        q.cuts.append(("time", m.group(0).strip()))
        low = low[:m.start()] + " " + low[m.end():]
        return True

    num = r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple|few)"
    unit = r"(day|week|month|year|hour)s?"

    def n_of(w):
        return int(w) if w.isdigit() else NUM.get(w, 1)

    def delta(n, u):
        return {"hour": dt.timedelta(hours=n), "day": dt.timedelta(days=n), "week": dt.timedelta(weeks=n),
                "month": dt.timedelta(days=30 * n), "year": dt.timedelta(days=365 * n)}[u]

    take(r"\b(?:in the |over the |during the )?(?:last|past) " + num + r" (?:of )?" + unit + r"\b",
         lambda m: ((now - delta(n_of(m.group(1)), m.group(2)), now), f"last {n_of(m.group(1))} {m.group(2)}s"))
    take(r"\b(?:about |around |like )?" + num + r" (?:of )?" + unit + r" ago\b",
         lambda m: _around(now - delta(n_of(m.group(1)), m.group(2)), m.group(2), n_of(m.group(1))))
    take(r"\btoday\b|\bthis morning\b|\bthis afternoon\b|\btonight\b", lambda m: ((today, now), "today"))
    take(r"\byesterday\b", lambda m: ((today - dt.timedelta(days=1), today), "yesterday"))
    take(r"\bthis week\b", lambda m: ((today - dt.timedelta(days=today.weekday()), now), "this week"))
    take(r"\blast week\b", lambda m: ((today - dt.timedelta(days=today.weekday() + 7),
                                       today - dt.timedelta(days=today.weekday())), "last week"))
    take(r"\bthis month\b", lambda m: ((today.replace(day=1), now), "this month"))
    take(r"\blast month\b", lambda m: (_month_range(*_prev_month(today.year, today.month)), "last month"))
    take(r"\bthis year\b", lambda m: ((dt.datetime(today.year, 1, 1), now), "this year"))
    take(r"\blast year\b", lambda m: ((dt.datetime(today.year - 1, 1, 1), dt.datetime(today.year, 1, 1)),
                                      f"in {today.year - 1}"))
    take(r"\brecently\b|\blately\b|\brecent\b", lambda m: ((now - dt.timedelta(days=14), now), "last 2 weeks"))
    # full day names only ("sun" or "wed" are too often ordinary words)
    take(r"\b(?:on |last )?(" + "|".join(d for d in DAYS if len(d) > 3) + r")\b",
         lambda m: _weekday(today, DAYS[m.group(1)]))
    # "may" and "mar" only count as months with "in"/"from"/... or a year: "i may have saved it" is not May
    take(r"\b(in |during |from |since )?(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")(?: (\d{4}))?\b",
         lambda m: None if (m.group(2) in ("may", "mar") and not m.group(1) and not m.group(3))
         else _month(today, MONTHS[m.group(2)], m.group(3)))
    take(r"\b(?:in |from |during )?((?:19|20)\d{2})\b", lambda m: (
        (dt.datetime(int(m.group(1)), 1, 1), dt.datetime(int(m.group(1)) + 1, 1, 1)), f"in {m.group(1)}"))
    take(r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: _date(int(m.group(1)), int(m.group(2)), int(m.group(3))))

    # which of the user's folders
    for pattern in FOLDER_PATTERNS:
        m = re.search(pattern, low)
        if m:
            q.folder = _FOLDER_WORDS[m.group(1)]
            q.cuts.append(("folder", m.group(0).strip()))
            low = low[:m.start()] + " " + low[m.end():]
            break

    # where: a kind of drive, a drive letter or a drive's name
    for pattern, place in PLACES:
        m = re.search(pattern, low)
        if m:
            q.place = place
            q.cuts.append(("place", m.group(0).strip()))
            low = low[:m.start()] + " " + low[m.end():]
            break
    if not q.place:
        m = _DRIVE.search(low)
        if m:
            q.place = (m.group(1) or m.group(2) or m.group(3)).upper() + ":"
            q.cuts.append(("place", m.group(0).strip()))
            low = low[:m.start()] + " " + low[m.end():]
    if not q.place:
        for label in sorted({x.strip().lower() for x in labels if x and len(x.strip()) >= 3}, key=len, reverse=True):
            m = re.search(_ON + re.escape(label) + r"(?: drive| disk| stick| card)?(?=\s)", low)
            if m:
                q.place = "label:" + label
                q.cuts.append(("place", m.group(0).strip()))
                low = low[:m.start()] + " " + low[m.end():]
                break

    # a folder of the index named in the question: "notes in projects", "pdf inside the tax papers folder"
    if find_folder is not None and not q.path:
        low = _take_dir(q, low, find_folder)

    # apps, kinds and extensions
    for phrase, joined in APP_PHRASES.items():
        low = low.replace(" " + phrase + " ", " " + joined + " ")
    words = re.findall(WORD, low)
    asked = []                                      # ASKING words seen (see the end)
    used = set()                                    # positions of words read as a filter (kinds, apps, .ext)
    cue_at = -1                                    # "projects" in "blender projects" is part of the app filter
    for i, w in enumerate(words):
        if i == cue_at:
            used.add(i)
            continue
        cue = i + 1 < len(words) and words[i + 1] in APP_CUES
        if w in APPS and (w not in AMBIGUOUS_APPS or cue):
            q.apps.add(w)
            q.app_exts |= APPS[w]
            q.cuts.append(("app", w + (" " + words[i + 1] if cue else "")))
            used.add(i)
            if cue:
                cue_at = i + 1
            continue
        if w in WORDS and (soft_kinds or w not in SOFT_KINDS):
            k = WORDS[w]
            if k:
                if w in SOFT_KINDS:
                    q.soft.append(w)
                q.kinds.add(k)
                q.cuts.append(("kind:" + k, w))
                used.add(i)
                continue
        if re.fullmatch(r"\.[a-z0-9]{1,6}", w):
            q.exts.add(w)
            q.cuts.append(("ext", w))
            used.add(i)
            continue
        if w in STOP or w in NUM or w in HINDI_STOP_DEV:
            continue
        if roman and w in HINDI_STOP_ROMAN:
            q.dropped.append(w)                     # a linking word; search keeps it if a file is named so
            continue
        if w in ASKING:
            asked.append(w)
            used.add(i)
            continue
        q.terms.append(w)
    if asked and not q.terms and not q.phrases and not q.has_filters() and not q.here and not q.sort:
        q.terms = asked                             # "list" alone: a file called list, not an instruction
    q.meaning = _description(words, used, roman) if q.terms else ""
    return q


# Words trimmed off the ends of a description ("find me a | with a red car" -> "red car")
_EDGE = STOP | HINDI_STOP_DEV | {"files", "file", "folder", "folders", "something", "anything", "which", "that",
                                 "shows", "showing", "show", "having", "containing", "where", "of"}


def _description(words, used, roman):
    """What's left once the filters are out, in the user's order and with its small words: "2 boys" of "2 boys in
    an image", "dog on the beach" of "photos of a dog on the beach". Photo meaning reads it as a caption."""
    edge = _EDGE | (HINDI_STOP_ROMAN if roman else set()) | ASKING
    out, seg = [], []

    def flush():
        while seg and seg[0] in edge and not seg[0].isdigit():
            seg.pop(0)
        while seg and seg[-1] in edge and not seg[-1].isdigit():
            seg.pop()
        if seg:
            out.append(" ".join(seg))
        seg.clear()
    for i, w in enumerate(words):
        if i in used:
            flush()
        else:
            seg.append(w)
    flush()
    return " ".join(out)[:200]


_DIR_LEAD = r"(?<!\S)(?:in|inside|from|under|within) (?:my |the |our |a |an )?"
_DIR_SKIP = STOP | ASKING | set(NUM) | set(MONTHS) | set(DAYS) | {"files", "folder", "folders"}


def _take_dir(q, low, find_folder):
    """ "in <folder name>" when the index has a folder by that name (1 to 3 words; the longest that exists wins).
    Kind and filter words are never folder names here ("in an image" is a kind, not a folder called image)."""
    for m in re.finditer(_DIR_LEAD + r"((?:" + WORD + r" ){0,2}" + WORD + r")", low):
        words = m.group(1).split(" ")
        for n in range(len(words), 0, -1):
            cand = words[:n]
            if cand[0] in _DIR_SKIP or cand[-1] in _DIR_SKIP or cand[0] in WORDS or cand[-1] in WORDS:
                continue
            if all(w.isdigit() for w in cand):
                continue
            found = find_folder(" ".join(cand))
            if not found:
                continue
            label, paths = found
            end = m.start(1) + len(" ".join(cand))
            tail = re.match(r" (?:folder|directory|dir)\b", low[end:])
            if tail:
                end += tail.end()
            q.dirs, q.dir_label = list(paths), label
            q.cuts.append(("dir", low[m.start():end].strip()))
            return low[:m.start()] + " " + low[end:]
    return low


def _around(t, unit, n):
    width = {"hour": dt.timedelta(hours=1), "day": dt.timedelta(days=1), "week": dt.timedelta(days=4),
             "month": dt.timedelta(days=12), "year": dt.timedelta(days=120)}[unit]
    return (t - width, t + width), f"about {n} {unit}{'s' if n != 1 else ''} ago"


def _prev_month(y, m):
    return (y - 1, 12) if m == 1 else (y, m - 1)


def _weekday(today, wd):
    back = (today.weekday() - wd) % 7 or 7
    d = today - dt.timedelta(days=back)
    return (d, d + dt.timedelta(days=1)), d.strftime("%A %d %b").replace(" 0", " ")


def _month(today, month, year):
    y = int(year) if year else (today.year if month <= today.month else today.year - 1)
    a, b = _month_range(y, month)
    return (a, b), a.strftime("%B %Y")


def _date(y, m, d):
    try:
        a = dt.datetime(y, m, d)
    except ValueError:
        return None
    return (a, a + dt.timedelta(days=1)), a.strftime("%d %b %Y").lstrip("0")
