"""Hindi and Hinglish questions: the same filters as English (kinds, times, sizes, folders, linking words)."""
import datetime as dt

from nobadfind.query import parse

NOW = dt.datetime(2026, 11, 19, 15, 0)


def p(text):
    return parse(text, now=NOW)


def test_devanagari_words_stay_whole():
    q = p("बिजली का बिल")
    assert q.terms == ["बिजली", "बिल"]                  # का is a linking word


def test_kinds_in_hindi_and_hinglish():
    assert p("शिमला यात्रा की फोटो").kinds == {"image"} and p("शिमला यात्रा की फोटो").terms == ["शिमला", "यात्रा"]
    assert p("तस्वीरें goa").kinds == {"image"}
    assert p("पीडीएफ वाला salary slip").kinds == {"pdf"} and p("पीडीएफ वाला salary slip").terms == ["salary", "slip"]
    assert p("रिपोर्ट वीडियो").kinds == {"video"}


def test_times_in_hindi_and_hinglish():
    assert p("आज की फाइलें").when == "today"
    assert p("कल का बिल").when == "yesterday"
    assert p("पिछले हफ्ते की रसीद").when == "last week"
    assert p("pichle hafte ki rent wali pdf").when == "last week"
    q = p("pichle hafte ki rent wali pdf")
    assert q.kinds == {"pdf"} and q.terms == ["rent"]
    assert p("पिछले महीने का बिजली बिल").when == "last month"
    assert p("pichle mahine ka bill").when == "last month"
    assert p("is mahine ki salary slip").when == "this month"
    assert p("पिछले साल की टैक्स फाइल").when == "in 2025"
    assert p("३ दिन पहले").when == "about 3 days ago"
    assert p("2 din pehle wali photo").when == "about 2 days ago"


def test_sizes_in_hindi():
    assert p("100 MB से बड़ी फाइलें").min_size == 100 << 20
    assert p("5 mb se chhoti pdf").max_size == 5 << 20
    assert p("बड़ी फाइलें").min_size == 100 << 20


def test_folders_in_hindi():
    assert p("डाउनलोड में पीडीएफ").folder == "downloads"
    assert p("downloads mein resume").folder == "downloads"
    assert p("डेस्कटॉप पर नोट्स").folder == "desktop"


def test_linking_words():
    q = p("पीडीएफ जिसमें किराया लिखा है")
    assert q.kinds == {"pdf"} and q.terms == ["किराया", "लिखा"]
    assert p("rent wali file jisme deposit hai").terms == ["rent", "deposit"]


def test_english_is_unchanged():
    q = p("rent pdf from last week")
    assert q.kinds == {"pdf"} and q.when == "last week" and q.terms == ["rent"]
    assert p("kal").when == "yesterday" and p("kale salad").terms == ["kale", "salad"]


# ---------- the text index keeps Hindi words whole ----------
def test_hindi_words_are_whole_in_the_text_index(tmp_path):
    from nobadfind.store import Store
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([("C:/p/a.txt", "a.txt", "C:/p", ".txt", "text", 10, 1.0, 1.0, 1)])
    s.set_text(1, 1.0, ["इस महीने का बिजली बिल 1450 रुपये है"], None)
    s.upgrade_text_index()
    hit = lambda w: s.one("SELECT count(*) FROM text WHERE text MATCH ?", (w,))     # noqa: E731
    assert hit("बिजली") == 1 and hit("महीने") == 1 and hit("bill OR बिल") == 1
    assert hit("मह") == 0 and hit("बजल") == 0                  # pieces of words don't match any more
    s.upgrade_text_index()                                     # once is enough: a second call changes nothing
    assert s.meta("text_index") == "2"


def test_an_old_text_index_is_rebuilt_with_whole_hindi_words(tmp_path):
    from nobadfind.store import Store
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([("C:/p/a.txt", "a.txt", "C:/p", ".txt", "text", 10, 1.0, 1.0, 1)])
    s.set_text(1, 1.0, ["पिछले हफ्ते की रसीद"], None)
    s.set_meta("text_index", "")
    s.upgrade_text_index()
    assert s.one("SELECT count(*) FROM text WHERE text MATCH ?", ("रसीद",)) == 1
