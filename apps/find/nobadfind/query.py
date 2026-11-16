"""Understand a plain-language question: words to look for, file kinds and a time range.

    "rent pdf from last week"            -> text "rent", kind pdf, last week
    "photos from the beach in march"     -> text "beach", kind image, March (most recent)
    "budget.xlsx"                        -> text "budget.xlsx"
    '"exact phrase" notes 3 days ago'    -> phrase "exact phrase", kind text, 3 days ago
"""
import datetime as dt
import re
from dataclasses import dataclass, field

from .kinds import WORDS

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
        "use", "look", "looking", "need", "want", "please", "where's", "whats", "im", "i'm", "we", "our", "your"}


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

    @property
    def text(self):
        return " ".join(self.phrases + self.terms)

    def understood(self):
        out = []
        if self.kinds:
            out.append(", ".join(sorted(self.kinds)))
        if self.exts:
            out.append(", ".join(sorted(self.exts)))
        if self.when:
            out.append(self.when)
        return out


def _day(d):
    return dt.datetime.combine(d, dt.time.min)


def _ts(x):
    return x.timestamp()


def _month_range(year, month):
    start = dt.datetime(year, month, 1)
    end = dt.datetime(year + (month == 12), month % 12 + 1, 1)
    return start, end


def parse(text, now=None):
    now = now or dt.datetime.now()
    q = Query(raw=text)
    s = text.strip()

    # exact phrases first
    for m in re.findall(r'"([^"]{1,200})"', s):
        q.phrases.append(m.strip())
    s = re.sub(r'"[^"]*"', " ", s)

    low = " " + s.lower() + " "
    today = _day(now.date())

    def take(pattern, fn):
        nonlocal low
        m = re.search(pattern, low)
        if not m or q.t0 is not None:
            return False
        r = fn(m)
        if r is None:
            return False
        (a, b), label = r
        q.t0, q.t1, q.when = _ts(a), _ts(b), label
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

    # kinds and extensions
    words = re.findall(r"[\w.\-+#]+", low)
    for i, w in enumerate(words):
        if w in WORDS:
            k = WORDS[w]
            if k:
                q.kinds.add(k)
                continue
        if re.fullmatch(r"\.[a-z0-9]{1,6}", w):
            q.exts.add(w)
            continue
        if w in STOP or w in NUM:
            continue
        q.terms.append(w)
    return q


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
