"""Documented country restrictions (bans, refusals, blocked releases) from Wikipedia's banned-film lists.

Why this source: it is the most complete public, citable archive, licensed CC BY-SA, reachable through the
official MediaWiki API (no scraping of HTML). It is a SECONDARY source: every record carries the citations the
article gives, a link to the exact section, and a verification label. NOBAD never upgrades a record to "government
decision" on its own; the notes and citations say what kind of restriction it was.

Matching is by identity, not by title: a TMDB title -> its Wikidata item -> its English Wikipedia article (plus
every redirect to it) -> rows whose film link points at that article. Titles that can't be linked this way get
no restriction records, rather than risk pinning someone else's ban on them.

Licensing gaps (a title missing from a catalogue) are never restrictions; they live in availability.py."""
import re
import time

from . import net

WIKI_API = "https://en.wikipedia.org/w/api.php"
WD_API = "https://www.wikidata.org/w/api.php"
ROOT_PAGE = "List of banned films"
LICENSE = "Wikipedia text is available under CC BY-SA 4.0; records link back to their source section."
MAX_PAGES = 60
_LIFT = re.compile(r"\b(lifted|unbanned|overturned|later (?:released|allowed|passed|cleared)|ban was (?:revoked|removed)|"
                   r"eventually (?:released|allowed|passed))\b", re.I)
_TEMPORARY = re.compile(r"\b(temporar\w*|for (?:\w+ ){0,2}(?:days|weeks|months|years)|held up|delayed|suspended)\b", re.I)
_CUTS = re.compile(r"\b(cuts?|edited|censored version|scenes? (?:were )?(?:removed|cut))\b", re.I)
_REFUSED = re.compile(r"\b(refused (?:a )?(?:certificat|classificat|rating)|denied (?:a )?(?:certificat|classificat|rating)|"
                      r"refused classification)\w*", re.I)


def norm_title(t):
    t = (t or "").split("#")[0].replace("_", " ")
    t = " ".join(t.split())
    return t[:1].upper() + t[1:] if t else ""


# ---- wikitext helpers ----------------------------------------------------------------------------------------
def _strip_templates(s):
    out, depth, i = [], 0, 0
    while i < len(s):
        if s.startswith("{{", i):
            depth += 1
            i += 2
        elif s.startswith("}}", i) and depth:
            depth -= 1
            i += 2
        else:
            if not depth:
                out.append(s[i])
            i += 1
    return "".join(out)


def plain(s):
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = _strip_templates(s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("'''", "").replace("''", "").replace("&nbsp;", " ")
    return " ".join(s.split()).strip(" |")


def _cite(body):
    def field(name):
        m = re.search(r"\|\s*" + name + r"\s*=\s*([^|}]*)", body)
        return m.group(1).strip() if m else None
    url = field("url")
    if not url:
        m = re.search(r"https?://[^\s|\]}<]+", body)
        url = m.group(0) if m else None
    title = plain(field("title") or "") or None
    pub = plain(field("publisher") or field("website") or field("work") or field("newspaper") or "") or None
    date = field("date") or field("year")
    text = None if (url or title) else (plain(body)[:200] or None)
    return {"url": url, "title": title, "publisher": pub, "date": date, "text": text}


def named_refs(wikitext):
    return {m.group(1).strip(): m.group(2) for m in
            re.finditer(r"<ref\s+name\s*=\s*\"?([^\">/]+)\"?\s*>(.*?)</ref>", wikitext, flags=re.S)}


def refs_in(s, named):
    out = []
    for m in re.finditer(r"<ref(?:\s+name\s*=\s*\"?([^\">/]+)\"?)?\s*(/>|>(.*?)</ref>)", s, flags=re.S):
        body = m.group(3) if m.group(3) is not None else named.get((m.group(1) or "").strip(), "")
        if body:
            c = _cite(body)
            if c not in out:
                out.append(c)
    return out


def _split_attr(cell):
    """'style="x" | content' -> 'content' (only when the prefix looks like attributes, not like a link/template)."""
    depth, i = 0, 0
    while i < len(cell):
        two = cell[i:i + 2]
        if two in ("[[", "{{"):
            depth += 1
            i += 2
            continue
        if two in ("]]", "}}"):
            depth = max(0, depth - 1)
            i += 2
            continue
        if cell[i] == "|" and not depth:
            prefix = cell[:i]
            if "=" in prefix and not re.search(r"[\[\]{}']", prefix):
                return cell[i + 1:], prefix
            return cell, ""
        i += 1
    return cell, ""


def _cells(line, marker):
    line = line[1:]
    parts = re.split(r"\s*" + re.escape(marker * 2) + r"\s*", line) if marker * 2 in line else [line]
    return [p.strip() for p in parts]


def parse_tables(text):
    """Yield (headers, rows); each row is a list of cell strings. Handles '||' cells, multi-line cells, attribute
    prefixes and rowspan (a spanned cell is repeated in the rows below)."""
    for tm in re.finditer(r"^\{\|.*?^\|\}", text, flags=re.S | re.M):
        headers, rows, cur, span = [], [], None, {}
        for raw in tm.group(0).splitlines()[1:-1]:
            line = raw.rstrip()
            if line.startswith("|-"):
                if cur is not None:
                    rows.append(cur)
                cur = []
                continue
            if line.startswith("|+"):
                continue
            if line.startswith("!"):
                headers += [plain(_split_attr(c)[0]).lower() for c in _cells(line, "!")]
                continue
            if line.startswith("|"):
                if cur is None:
                    cur = []
                for c in _cells(line, "|"):
                    content, attrs = _split_attr(c)
                    col = len(cur)
                    while col in span and span[col][1] > 0:
                        cur.append(span[col][0])
                        span[col] = (span[col][0], span[col][1] - 1)
                        col = len(cur)
                    m = re.search(r"rowspan\s*=\s*\"?(\d+)", attrs)
                    if m and int(m.group(1)) > 1:
                        span[col] = (content, int(m.group(1)) - 1)
                    cur.append(content)
            elif cur:
                cur[-1] += "\n" + line          # continuation of a multi-line cell
        if cur:
            rows.append(cur)
        # fill rowspans that run into rows with fewer cells
        yield headers, rows


def _col(headers, *names):
    for i, h in enumerate(headers):
        if any(n in h for n in names):
            return i
    return None


def film_link(cell):
    m = re.search(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]", cell)
    if m:
        return norm_title(m.group(1)), plain(m.group(2) or m.group(1))
    return None, plain(cell)


def classify(notes):
    """What the notes say, by plain keyword evidence. Always labelled 'from notes' in the UI."""
    tags = []
    if _REFUSED.search(notes):
        tags.append("certification refused")
    if _CUTS.search(notes):
        tags.append("cuts or edited release")
    if _TEMPORARY.search(notes):
        tags.append("temporary or delayed")
    if _LIFT.search(notes):
        tags.append("later lifted")
    return tags


def sections(wikitext):
    """[(level, heading, body)] for '== X ==' style headings; text before the first heading has heading ''."""
    parts = re.split(r"^(={2,6})\s*(.*?)\s*\1\s*$", wikitext, flags=re.M)
    out = [(1, "", parts[0])]
    for i in range(1, len(parts) - 2, 3):
        out.append((len(parts[i]), plain(parts[i + 1]), parts[i + 2]))
    return out


_PAGE_COUNTRY = re.compile(r"^(?:list of (?:films banned|banned films) in|film censorship in|censorship in)\s+(.+)$", re.I)


def page_country(title):
    m = _PAGE_COUNTRY.match(title or "")
    return m.group(1).strip() if m else None


def rows_from_page(title, wikitext, countries, default_country=None):
    named = named_refs(wikitext)
    out, top_country = [], default_country or page_country(title)
    country = top_country
    for level, heading, body in sections(wikitext):
        if not top_country and level == 2:
            country = heading
        elif level == 2 and heading and countries.code(heading):    # sub-lists inside a country page
            country = heading
        for headers, rows in parse_tables(body):
            fi = _col(headers, "film", "title", "name")
            if fi is None:
                continue
            di, ni = _col(headers, "date", "year"), _col(headers, "note", "reason", "detail", "description", "comment")
            for r in rows:
                if fi >= len(r):
                    continue
                target, label = film_link(r[fi])
                if not label:
                    continue
                notes_raw = r[ni] if ni is not None and ni < len(r) else ""
                notes = plain(notes_raw)
                srcs = refs_in(" ".join(r), named)
                out.append({
                    "country": country, "code": countries.code(country) if country else None,
                    "date": plain(r[di]) if di is not None and di < len(r) else None,
                    "film": label, "target": target, "notes": notes[:1200], "tags": classify(notes),
                    "sources": srcs[:8], "page": title, "section": heading or None,
                    "url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_") +
                           ("#" + heading.replace(" ", "_") if heading else ""),
                    "verification": ("documented, secondary source with %d citation%s" % (len(srcs), "" if len(srcs) == 1 else "s"))
                    if srcs else "documented, secondary source without a citation in the list",
                })
    return out


# ---- fetching + index ---------------------------------------------------------------------------------------
class WikiSource:
    def __init__(self, opener=None, sleep=None):
        self.opener, self.sleep = opener, sleep

    def _get(self, url, **params):
        params.setdefault("format", "json")
        params.setdefault("formatversion", 2)
        kw = {"opener": self.opener}
        if self.sleep:
            kw["sleep"] = self.sleep
        return net.get_json(url, params, **kw)

    def wikitext(self, page):
        d = self._get(WIKI_API, action="parse", page=page, prop="wikitext|revid", redirects=1)
        if "error" in d:
            raise net.SourceError("notfound", d["error"].get("info", "page not found"))
        p = d["parse"]
        return p.get("title", page), p.get("wikitext", ""), p.get("revid")

    def build_index(self, countries, clock=time.time):
        """Fetch the root list and every dedicated 'List of ... banned ...' page it links as {{Main}}."""
        title, text, rev = self.wikitext(ROOT_PAGE)
        pages, records, failed = [{"title": title, "revid": rev}], [], []
        records += rows_from_page(title, text, countries)
        mains = []
        for level, heading, body in sections(text):
            for m in re.finditer(r"\{\{\s*(?:main|Main)\s*\|([^}]*)\}\}", body):
                for t in m.group(1).split("|"):
                    t = t.strip()
                    if t and "=" not in t and t.lower().startswith("list of") and "banned" in t.lower():
                        mains.append((t, heading))
        for t, heading in mains[:MAX_PAGES]:
            try:
                pt, ptxt, prev = self.wikitext(t)
            except net.SourceError as e:
                failed.append({"title": t, "error": str(e)})
                continue
            pages.append({"title": pt, "revid": prev})
            records += rows_from_page(pt, ptxt, countries, default_country=page_country(pt) or heading)
        index = {}
        for r in records:
            if r["target"]:
                index.setdefault(r["target"], []).append(r)
        return {"index": index, "pages": pages, "failed": failed, "built": clock(), "rows": len(records),
                "linked_rows": sum(len(v) for v in index.values())}

    def article_for(self, qid):
        """Wikidata QID -> (English Wikipedia article title, [redirect titles]) or (None, [])."""
        if not re.fullmatch(r"Q\d{1,12}", qid or ""):
            return None, []
        d = self._get(WD_API, action="wbgetentities", ids=qid, props="sitelinks", sitefilter="enwiki")
        ent = (d.get("entities") or {}).get(qid) or {}
        link = ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("title")
        if not link:
            return None, []
        q = self._get(WIKI_API, action="query", titles=link, prop="redirects", rdlimit="max", redirects=1)
        pages = (q.get("query") or {}).get("pages") or []
        canon = pages[0].get("title", link) if pages else link
        reds = [r.get("title") for r in (pages[0].get("redirects") or [])] if pages else []
        return norm_title(canon), [norm_title(r) for r in reds if r]


def match(index_doc, article, redirects):
    if not article:
        return []
    idx = index_doc.get("index") or {}
    out, seen = [], set()
    for t in [article] + list(redirects):
        for r in idx.get(norm_title(t), []):
            k = (r["country"], r["date"], r["page"], r["notes"][:60])
            if k not in seen:
                seen.add(k)
                out.append(r)
    return sorted(out, key=lambda r: (r["country"] or "", r["date"] or ""))
