"""Smart search evaluation (dev only, not shipped): natural-language questions over a generated corpus.

    cd apps/find
    python tools/eval_search.py [--models-dir DIR] [--check] [--json]

Builds a throwaway index (temp folder, never the user's Find data) over a generated corpus: documents in English,
Hindi, Spanish, French and German, look-alike names (invoice_march / invoice_may / invoices 2023 ...), files placed
in Downloads / Desktop / Documents / Pictures / Videos / Music-like folders (the engine's known folders point at
them for the run) and in named project folders, with varied dates and sizes, and simple drawn pictures for photo
meaning. Then every question in QUERIES goes through the engine's real search.search() and is scored: recall@1,
recall@5, MRR@10, the best guess's precision (how often the guess was a right answer) and coverage, and the
understood parts (chips) each question must show.

--models-dir: a data folder that already has model/ (MiniLM) and/or photo-model/ (SigLIP base) downloaded. The
models are COPIED into the temp data folder; nothing is ever downloaded. Without them, meaning and photo questions
are skipped and the report says so. --check: exit 1 when a score is under THRESHOLDS.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import statistics
import sys
import tempfile
import time

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP not in sys.path:
    sys.path.insert(0, APP)

DAY = 86400
# Each doc: id, folder (under the home folder), name, body (text; None = binary filler), age in days, size
# (bytes, only for binary filler). Dates are relative to now, so "last week" and "yesterday" stay true.
FOLDERS = {"downloads": "Downloads", "desktop": "Desktop", "documents": "Documents", "pictures": "Pictures",
           "videos": "Videos", "music": "Music"}


def _march_age(now):
    """Days back to the middle of March this year (query.parse reads "in march" as the most recent March)."""
    return max(1, (now - dt.datetime(now.year, 3, 15)).days)


def docs(now):
    m = _march_age(now)
    return [
        # look-alike invoices
        dict(id="inv_mar", folder="Downloads", name="invoice_march.pdf", body="Invoice for March. Web hosting, "
             "amount due 120 EUR. Thank you for your business.", age=m),
        dict(id="inv_may", folder="Downloads", name="invoice_may.pdf", body="Invoice for May. Web hosting, amount "
             "due 120 EUR.", age=m - 60 if m > 70 else 40),
        dict(id="inv_2023", folder="Documents", name="invoices 2023.xlsx", body=None, age=500, size=30_000),
        dict(id="inv_tpl", folder="Documents\\Templates", name="invoice-template.docx", body=None, age=900,
             size=18_000),
        # rent and flat
        dict(id="rent", folder="Documents", name="rental agreement flat.txt", body="This tenancy agreement for the "
             "flat at 12 Park Road starts on 1 April. Monthly rent 950 GBP, deposit five weeks.", age=200),
        dict(id="rent_receipt", folder="Downloads", name="rent receipt october.txt", body="Received rent for "
             "October from the tenant. Paid by bank transfer.", age=35),
        # tax papers folder (an indexed folder named in questions)
        dict(id="tax_return", folder="Documents\\Tax Papers", name="tax return 2024.pdf", body="Self assessment tax "
             "return for 2024. Income from employment and savings interest.", age=300),
        dict(id="tax_letter", folder="Documents\\Tax Papers", name="letter from hmrc.txt", body="We have "
             "reviewed your tax return. You owe nothing for this year.", age=250),
        # projects folder
        dict(id="proj_notes", folder="Documents\\Projects", name="garden shed plan.md", body="Plan for the garden "
             "shed: timber frame, felt roof, 2 by 3 metres. Buy screws and hinges.", age=12),
        dict(id="proj_budget", folder="Documents\\Projects", name="budget.xlsx", body=None, age=20, size=22_000),
        dict(id="proj_code", folder="Documents\\Projects", name="budget_calc.py", body="def total(items):\n    "
             "return sum(i.price for i in items)  # budget calculator\n", age=5),
        dict(id="budget_old", folder="Documents\\Old", name="budget 2019 draft.txt", body="Old household budget "
             "draft.", age=2000),
        # desktop
        dict(id="todo", folder="Desktop", name="todo.txt", body="Call the dentist. Renew car insurance. Book flight "
             "to Lisbon.", age=1),
        dict(id="meeting", folder="Desktop", name="meeting notes.md", body="Meeting with Priya about the product "
             "launch. Next steps: pricing page, beta invite list.", age=0),
        dict(id="shot", folder="Desktop", name="Screenshot 2025-03-02 101500.png", body=None, age=6, size=40_000),
        # other languages
        dict(id="es_recipe", folder="Documents\\Recipes", name="receta paella.txt", body="Receta de paella "
             "valenciana: arroz, azafrán, pollo, conejo y judías verdes. Cocinar a fuego lento.", age=90),
        dict(id="fr_letter", folder="Documents", name="lettre de motivation.txt", body="Madame, Monsieur, je vous "
             "écris pour le poste de développeur. Je suis motivé et disponible.", age=150),
        dict(id="de_contract", folder="Documents", name="mietvertrag wohnung.txt", body="Mietvertrag für die "
             "Wohnung in Berlin. Die Kaltmiete beträgt 800 Euro im Monat.", age=400),
        dict(id="hi_bill", folder="Downloads", name="बिजली बिल.txt", body="बिजली का बिल अक्टूबर महीने का। कुल राशि "
             "1200 रुपये।", age=3),
        dict(id="hi_notes", folder="Documents", name="yatra yojana.txt", body="हमारी गोवा यात्रा की योजना: होटल, "
             "ट्रेन टिकट और समुद्र तट।", age=70),
        # media (binary filler: the kind comes from the extension)
        dict(id="vid_big", folder="Videos", name="holiday 2024.mp4", body=None, age=330, size=150 << 20),
        dict(id="vid_small", folder="Videos", name="cat clip.mp4", body=None, age=10, size=900_000),
        dict(id="song", folder="Music", name="summer song.mp3", body=None, age=400, size=4_000_000),
        dict(id="song2", folder="Downloads", name="podcast episode 12.mp3", body=None, age=2, size=30_000_000),
        dict(id="slides", folder="Documents", name="quarterly review.pptx", body=None, age=45, size=2_500_000),
        dict(id="cv", folder="Documents", name="cv aarav sharma.pdf", body="Curriculum vitae. Aarav Sharma, "
             "software engineer. Python, Flutter, SQL.", age=60),
        dict(id="manual", folder="Downloads", name="washing machine manual.pdf", body="User manual. Select the "
             "programme, press start. Clean the filter monthly.", age=25),
        dict(id="ticket", folder="Downloads", name="boarding pass lisbon.pdf", body="Boarding pass. Flight TP1337 "
             "to Lisbon, gate 22, seat 14C.", age=8),
        dict(id="old_pdf", folder="Downloads", name="brochure.pdf", body="Holiday brochure with hotels.", age=800),
        # noise: look-alike names elsewhere
        dict(id="noise1", folder="Documents\\Projects\\archive", name="budget backup.txt", body="backup", age=700),
        dict(id="noise2", folder="Pictures\\Wallpapers", name="mountains.jpg", body=None, age=600, size=50_000),
    ]


# Pictures drawn for photo meaning (file names say nothing about what's in them)
PICTURES = [
    dict(id="img_two", folder="Downloads", name="IMG_0412.jpg", draw="two_people", age=4),
    dict(id="img_one", folder="Downloads", name="IMG_0413.jpg", draw="one_person", age=4),
    dict(id="img_sunset", folder="Pictures", name="IMG_2201.jpg", draw="sunset", age=50),
    dict(id="img_circle", folder="Pictures", name="IMG_2202.jpg", draw="red_circle", age=50),
    dict(id="img_check", folder="Desktop", name="DSC_0001.jpg", draw="chessboard", age=2),
    dict(id="img_text", folder="Downloads", name="DSC_0002.jpg", draw="birthday_card", age=15),
    dict(id="img_tree", folder="Pictures", name="DSC_0003.jpg", draw="tree", age=100),
]

# Questions: q, expected doc ids (any of them right), what kind of question, parts (chip labels) it must show.
# needs: "" keywords only, "meaning" the text model, "photo" the photo model.
QUERIES = [
    # places + kinds
    dict(q="invoice pdf in downloads", rel=["inv_mar", "inv_may"], type="place", parts=["Downloads", "PDFs"]),
    dict(q="pdfs on the desktop", rel=[], type="place", parts=["Desktop", "PDFs"], expect_empty=True),
    dict(q="notes on desktop", rel=["meeting", "todo"], type="place", parts=["Desktop"]),
    dict(q="screenshot on desktop", rel=["shot", "img_check"], type="place", parts=["Desktop", "Images"]),
    dict(q="songs in downloads", rel=["song2"], type="place", parts=["Downloads", "Music and audio"]),
    dict(q="videos", rel=["vid_big", "vid_small"], type="kind", parts=["Videos"]),
    dict(q="presentation", rel=["slides"], type="kind", parts=["Slides"]),
    dict(q="code in projects", rel=["proj_code"], type="folder", parts=["Projects", "Code"]),
    dict(q="budget in projects", rel=["proj_budget", "proj_code"], type="folder", parts=["Projects"]),
    dict(q="letters in tax papers", rel=["tax_letter", "tax_return"], type="folder", parts=["Tax Papers"]),
    dict(q="everything in the tax papers folder", rel=["tax_return", "tax_letter"], type="folder",
         parts=["Tax Papers"]),
    # times
    dict(q="invoice from march", rel=["inv_mar"], type="time", parts=["March"]),
    dict(q="files from yesterday on desktop", rel=["todo"], type="time", parts=["Desktop", "Yesterday"]),
    dict(q="what did i save today", rel=["meeting"], type="time", parts=["Today"]),
    dict(q="pdf from last week in downloads", rel=["ticket"], type="time", parts=["Downloads", "PDFs", "Last week"]),
    dict(q="videos from 2024", rel=["vid_big"], type="time", parts=["Videos"]),
    # sizes
    dict(q="big videos", rel=["vid_big"], type="size", parts=["Videos", "Over 100 MB"]),
    dict(q="small videos", rel=["vid_small"], type="size", parts=["Videos", "Under 1 MB"]),
    dict(q="files over 100 mb", rel=["vid_big"], type="size", parts=["Over 100 MB"]),
    # names and look-alikes
    dict(q="budget.xlsx", rel=["proj_budget"], type="name", guess=True),
    dict(q="invoice may", rel=["inv_may"], type="name"),
    dict(q="invoices 2023", rel=["inv_2023"], type="name"),
    dict(q="invoice template", rel=["inv_tpl"], type="name", guess=True),
    dict(q="garden shed", rel=["proj_notes"], type="name", guess=True),
    dict(q="boarding pass", rel=["ticket"], type="name", guess=True),
    dict(q="washing mach", rel=["manual"], type="prefix", guess=True),
    dict(q="quarterly rev", rel=["slides"], type="prefix", guess=True),
    # text inside
    dict(q="pdf containing gate 22", rel=["ticket"], type="text"),
    dict(q="file mentioning deposit", rel=["rent"], type="text"),
    dict(q="dentist", rel=["todo"], type="text"),
    dict(q="python flutter sql", rel=["cv"], type="text"),
    # other languages
    dict(q="paella", rel=["es_recipe"], type="language"),
    dict(q="receta arroz azafrán", rel=["es_recipe"], type="language"),
    dict(q="lettre motivation", rel=["fr_letter"], type="language"),
    dict(q="kaltmiete berlin", rel=["de_contract"], type="language"),
    dict(q="बिजली बिल", rel=["hi_bill"], type="language"),
    dict(q="गोवा यात्रा", rel=["hi_notes"], type="language"),
    dict(q="downloads में बिजली", rel=["hi_bill"], type="language", parts=["Downloads"]),
    dict(q="pichle hafte ki pdf", rel=["ticket"], type="language", parts=["PDFs", "Last week"]),
    # meaning (text model)
    dict(q="apartment lease", rel=["rent"], type="meaning", needs="meaning"),
    dict(q="job application letter", rel=["fr_letter", "cv"], type="meaning", needs="meaning"),
    dict(q="plane ticket", rel=["ticket"], type="meaning", needs="meaning"),
    dict(q="flutter developer cv", rel=["cv"], type="meaning", needs="meaning"),
    dict(q="household spending plan", rel=["proj_budget", "budget_old", "proj_code"], type="meaning",
         needs="meaning"),
    # photo meaning (drawn pictures)
    dict(q="2 boys in an image in downloads", rel=["img_two"], type="photo", needs="photo",
         parts=["Downloads", "Images", "2 boys"]),
    dict(q="photo of two people", rel=["img_two"], type="photo", needs="photo"),
    dict(q="sunset over the sea photo", rel=["img_sunset"], type="photo", needs="photo"),
    dict(q="picture of a red circle", rel=["img_circle"], type="photo", needs="photo"),
    dict(q="chessboard image on desktop", rel=["img_check"], type="photo", needs="photo",
         parts=["Desktop", "Images"]),
    dict(q="birthday card photo", rel=["img_text"], type="photo", needs="photo"),
    dict(q="image of a tree", rel=["img_tree"], type="photo", needs="photo"),
]

THRESHOLDS = {"recall1": 0.90, "recall5": 0.95, "mrr10": 0.90, "parts": 1.0, "guess_precision": 0.95}
PHOTO_THRESHOLDS = {"recall1": 0.70, "recall5": 0.85}
MEANING_RECALL5 = 0.5         # measured 0.6 with 400 look-alike files (docs/measurements.md)


# ---------- the corpus ----------
def _pdf(text):
    """A one-page PDF with the text (Helvetica), enough for pypdf to read back."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    lines, line = [], ""
    for w in safe.split():
        if len(line) + len(w) > 70:
            lines.append(line)
            line = ""
        line += (" " if line else "") + w
    lines.append(line)
    stream = "BT /F1 12 Tf 50 780 Td 14 TL " + " ".join(f"({x}) Tj T*" for x in lines) + " ET"
    data = stream.encode("latin-1", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def draw(kind, path):
    """Simple drawn pictures (PIL). Returns False when PIL isn't there."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    import random
    rnd = random.Random(kind)
    im = Image.new("RGB", (448, 336), (235, 235, 230))
    d = ImageDraw.Draw(im)

    def person(x, color, h=1.0):
        d.ellipse([x - 22 * h, 70, x + 22 * h, 114], fill=(240, 200, 160), outline=(60, 40, 30), width=3)
        d.rectangle([x - 30 * h, 116, x + 30 * h, 210], fill=color)
        d.line([x - 30 * h, 130, x - 60 * h, 190], fill=color, width=12)
        d.line([x + 30 * h, 130, x + 60 * h, 190], fill=color, width=12)
        d.line([x - 15 * h, 210, x - 25 * h, 300], fill=(40, 40, 90), width=14)
        d.line([x + 15 * h, 210, x + 25 * h, 300], fill=(40, 40, 90), width=14)
    if kind == "two_people":
        d.rectangle([0, 250, 448, 336], fill=(90, 160, 70))
        person(150, (200, 40, 40))
        person(300, (40, 90, 200))
    elif kind == "one_person":
        d.rectangle([0, 250, 448, 336], fill=(90, 160, 70))
        person(224, (230, 150, 30))
    elif kind == "sunset":
        for y in range(200):
            d.line([0, y, 448, y], fill=(250, 120 + y // 3, 60 + y // 4))
        d.ellipse([170, 120, 280, 230], fill=(255, 210, 60))
        d.rectangle([0, 200, 448, 336], fill=(30, 70, 140))
        for y in range(210, 336, 12):
            d.line([rnd.randint(0, 200), y, rnd.randint(250, 448), y], fill=(240, 160, 90), width=2)
    elif kind == "red_circle":
        im.paste((255, 255, 255), [0, 0, 448, 336])
        d.ellipse([124, 68, 324, 268], fill=(220, 20, 30))
    elif kind == "chessboard":
        for i in range(8):
            for j in range(8):
                if (i + j) % 2:
                    d.rectangle([64 + i * 40, 8 + j * 40, 104 + i * 40, 48 + j * 40], fill=(20, 20, 20))
                else:
                    d.rectangle([64 + i * 40, 8 + j * 40, 104 + i * 40, 48 + j * 40], fill=(245, 245, 245))
    elif kind == "birthday_card":
        from PIL import ImageFont
        im.paste((255, 230, 240), [0, 0, 448, 336])
        try:
            font = ImageFont.truetype("arialbd.ttf", 56)
        except OSError:
            font = ImageFont.load_default()
        d.text((40, 90), "HAPPY", fill=(200, 30, 120), font=font)
        d.text((40, 170), "BIRTHDAY!", fill=(200, 30, 120), font=font)
        for _ in range(30):
            x, y = rnd.randint(0, 440), rnd.randint(0, 330)
            d.ellipse([x, y, x + 8, y + 8], fill=(rnd.randint(100, 255), rnd.randint(50, 200), 50))
    elif kind == "tree":
        d.rectangle([0, 260, 448, 336], fill=(100, 170, 80))
        d.rectangle([205, 160, 245, 280], fill=(110, 70, 30))
        d.ellipse([130, 30, 320, 200], fill=(40, 140, 50))
    # a little noise so it's a photo-sized JPEG and not a flat icon
    px = im.load()
    for _ in range(4000):
        x, y = rnd.randrange(448), rnd.randrange(336)
        r, g, b = px[x, y]
        n = rnd.randint(-12, 12)
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    im.save(path, quality=92)
    return True


NOISE_WORDS = ("invoice budget report notes backup draft copy final letter receipt plan garden summary minutes "
               "statement order delivery travel hotel recipe manual setup config export scan photo image data "
               "lecture homework project review meeting tax rent car insurance school").split()
NOISE_EXT = (".txt", ".log", ".json", ".pdf", ".docx", ".xlsx", ".png", ".zip", ".csv", ".md")
NOISE_DIRS = ("Documents\\Archive", "Documents\\Archive\\2019", "Documents\\Work\\Clients", "Downloads\\old",
              "AppData\\Local\\SomeApp\\cache", "AppData\\Roaming\\Editor\\backups", "Pictures\\Exports",
              "Music\\Samples", "Code\\scratch")


def noise_docs(n, seed=85):
    """Look-alike filler: names made of the same words as the real answers, older, in other folders."""
    import random
    rnd = random.Random(seed)
    out, seen = [], set()
    while len(out) < n:
        words = rnd.sample(NOISE_WORDS, rnd.choice((1, 2, 2, 3)))
        ext = rnd.choice(NOISE_EXT)
        sep = rnd.choice((" ", "_", "-"))
        name = sep.join(words) + (f"{sep}{rnd.randint(1, 99)}" if rnd.random() < 0.6 else "") + ext
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        body = (" ".join(rnd.choice(NOISE_WORDS) for _ in range(rnd.randint(5, 40)))
                if ext in (".txt", ".md", ".csv", ".log", ".json", ".pdf") else None)
        out.append(dict(id=f"noise_{len(out)}", folder=rnd.choice(NOISE_DIRS), name=name, body=body,
                        age=rnd.randint(30, 3000), size=rnd.randint(2_000, 3_000_000)))
    return out


def make_corpus(home, now=None, pictures=True, noise=400):
    """Write the corpus under home. Returns ({normcased path: doc id}, {doc id: path}, pictures written)."""
    now = now or dt.datetime.now()
    by_path, paths, drawn = {}, {}, 0
    for f in FOLDERS.values():
        os.makedirs(os.path.join(home, f), exist_ok=True)
    items = docs(now) + (PICTURES if pictures else []) + noise_docs(noise)
    for d in items:
        folder = os.path.join(home, d["folder"])
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, d["name"])
        if "draw" in d:
            if not draw(d["draw"], p):
                continue
            drawn += 1
        elif d.get("body") is not None:
            if p.endswith(".pdf"):
                with open(p, "wb") as fh:
                    fh.write(_pdf(d["body"]))
            else:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(d["body"])
        else:
            with open(p, "wb") as fh:
                fh.write(b"\x00NOBAD-EVAL\x00")
                fh.truncate(d.get("size", 1000))
        t = (now - dt.timedelta(days=d["age"], hours=1 if d["age"] == 0 else 0)).timestamp()
        if d["age"] == 0:
            t = max(t, dt.datetime.combine(now.date(), dt.time.min).timestamp() + 60)
        os.utime(p, (t, t))
        set_created(p, t)
        by_path[os.path.normcase(p)] = d["id"]
        paths[d["id"]] = p
    return by_path, paths, drawn


def set_created(path, t):
    """The creation time too (search matches modified OR created): a file made by this run would be "today"."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                wintypes.DWORD, wintypes.HANDLE]
    k32.SetFileTime.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k32.CreateFileW(path, 0x100, 7, None, 3, 0x02000000, None)      # FILE_WRITE_ATTRIBUTES, backup semantics
    if not h or h == wintypes.HANDLE(-1).value:
        return
    ft = ctypes.c_ulonglong(int((t + 11644473600) * 10_000_000))
    k32.SetFileTime(h, ctypes.byref(ft), None, None)
    k32.CloseHandle(h)


def known_folders(home):
    return {k: os.path.join(home, v) for k, v in FOLDERS.items()}


def build_index(root, home, data_dir=None, photos=True):
    """The engine's own walk, text reading and (when the models are there) name, chunk and photo vectors."""
    from nobadfind import embed, extract, models, photo
    from nobadfind.store import Store
    from nobadfind.walker import Walker
    store = Store(os.path.join(root, "i.db"), encrypt=False)
    Walker([home], gen=1, on_batch=store.upsert_files).run()
    store.upgrade_name_index()
    for fid, p, ext, mtime in store.q("SELECT id, path, ext, mtime FROM files WHERE kind != 'folder'"):
        _fid, _mt, chunks, err = extract.work((fid, p, ext, mtime, 25 << 20))
        store.set_text(fid, mtime, chunks, err)
    ctx = {"store": store, "embedder": None, "vindex": None, "photo_text": None, "pindex": None, "ran": []}
    if data_dir and models.ready("minilm-l6-v2", data_dir):
        import importlib.util
        spec_ = importlib.util.spec_from_file_location("eval_text", os.path.join(APP, "tools", "eval_text.py"))
        et = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(et)
        spec = models.get("minilm-l6-v2")
        d = models.model_dir("minilm-l6-v2", data_dir)
        emb = embed.Embedder(d, threads=4, gpu=False, spec=spec)
        q_emb = embed.Embedder(d, threads=4, gpu=False, spec=spec, query=True)
        vindex = embed.VectorIndex(spec["dim"])
        vindex.model = "minilm-l6-v2"
        et.index_vectors(store, emb, vindex)
        ctx.update(embedder=q_emb, vindex=vindex)
        ctx["ran"].append("meaning")
    pdir = os.path.join(data_dir or "", "photo-model")
    if photos and data_dir and photo.model_ready(pdir):
        pindex = embed.VectorIndex(photo.PHOTO_DIM, ("SELECT file_id, v FROM pvecs WHERE length(v) > 0",))
        rows = store.q("SELECT id, path, mtime FROM files WHERE kind = 'image'")
        for fid, p, mtime in rows:
            _f, _m, blob, err = photo.embed_photo((fid, p, mtime, pdir))
            store.set_photo_vector(fid, mtime, blob, err)
        pindex.reset(photo.PHOTO_DIM, "siglip-base")
        pindex.load(store)
        ctx.update(photo_text=photo.TextEncoder(pdir, threads=4), pindex=pindex)
        ctx["ran"].append("photo")
    return ctx


def score(ranked, rel):
    if not rel:
        return (1.0 if not ranked else 0.0,) * 3
    top1 = 1.0 if ranked[:1] and ranked[0] in rel else 0.0
    top5 = 1.0 if set(ranked[:5]) & set(rel) else 0.0
    rr = next((1 / (i + 1) for i, d in enumerate(ranked[:10]) if d in rel), 0.0)
    return top1, top5, rr


def run(models_dir=None, verbose=True, pictures=True):
    """Build the corpus and index in a temp folder, ask every question, return the report (a dict)."""
    from nobadfind import search, winapi
    root = tempfile.mkdtemp(prefix="nobadfind-evalsearch-")
    data_dir = os.path.join(root, "data")
    os.makedirs(data_dir)
    copied = []
    if models_dir:
        for sub in ("model", "photo-model"):
            src = os.path.join(models_dir, sub)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(data_dir, sub))
                copied.append(sub)
    home = os.path.join(root, "home")
    now = dt.datetime.now()
    kf = known_folders(home)
    old_known = winapi.known_folder
    winapi.known_folder = lambda name: kf.get(name, "")
    store = None
    try:
        by_path, _paths, drawn = make_corpus(home, now, pictures=pictures)
        t0 = time.perf_counter()
        ctx = build_index(root, home, data_dir if copied else None, photos=pictures and drawn > 0)
        build_s = time.perf_counter() - t0
        store = ctx["store"]
        rows, skipped, lat = [], [], []
        for item in QUERIES:
            need = item.get("needs", "")
            if need and need not in ctx["ran"]:
                skipped.append((item["q"], need))
                continue
            t = time.perf_counter()
            r = search.search(store, item["q"], embedder=ctx["embedder"], vindex=ctx["vindex"], limit=20,
                              roots=[home], photo_text=ctx["photo_text"], pindex=ctx["pindex"])
            lat.append((time.perf_counter() - t) * 1000)
            ranked = [by_path.get(os.path.normcase(x["path"])) for x in r["results"]]
            ranked = [x for x in ranked if x]
            s1, s5, rr = score(ranked, item["rel"])
            labels = [p["label"] for p in r.get("parts", [])]
            parts_ok = all(any(lab.lower().startswith(w.lower()) for lab in labels) for w in item.get("parts", []))
            best = r.get("best")
            best_doc = by_path.get(os.path.normcase(next((x["path"] for x in r["results"] if best and
                                                          x["id"] == best["id"]), "")))
            rows.append(dict(q=item["q"], type=item["type"], needs=need, r1=s1, r5=s5, rr=rr, parts_ok=parts_ok,
                             parts=labels, top=ranked[:3], best=best_doc, best_reason=(best or {}).get("reason"),
                             best_ok=(best_doc in item["rel"]) if best else None, guess_wanted=item.get("guess")))
        rep = {"models": ctx["ran"], "copied": copied, "pictures": drawn, "build_s": round(build_s, 1),
               "skipped": skipped, "rows": rows}

        def agg(rs):
            if not rs:
                return {}
            guesses = [x for x in rs if x["best"] is not None]
            wanted = [x for x in rs if x["guess_wanted"]]
            return {"n": len(rs), "recall1": round(statistics.fmean(x["r1"] for x in rs), 3),
                    "recall5": round(statistics.fmean(x["r5"] for x in rs), 3),
                    "mrr10": round(statistics.fmean(x["rr"] for x in rs), 3),
                    "parts": round(statistics.fmean(1.0 if x["parts_ok"] else 0.0 for x in rs), 3),
                    "guesses": len(guesses),
                    "guess_precision": round(statistics.fmean(1.0 if x["best_ok"] else 0.0 for x in guesses), 3)
                    if guesses else 1.0,
                    "guess_coverage_wanted": round(statistics.fmean(1.0 if x["best_ok"] else 0.0 for x in wanted), 3)
                    if wanted else 1.0}
        rep["keywords"] = agg([x for x in rows if not x["needs"]])
        rep["meaning"] = agg([x for x in rows if x["needs"] == "meaning"])
        rep["photo"] = agg([x for x in rows if x["needs"] == "photo"])
        rep["all"] = agg(rows)
        rep["by_type"] = {t: agg([x for x in rows if x["type"] == t]) for t in sorted({x["type"] for x in rows})}
        rep["lat_p50"] = round(statistics.median(lat), 1) if lat else 0
        rep["lat_p90"] = round(sorted(lat)[int(0.9 * (len(lat) - 1))], 1) if lat else 0
        rep["lat_max"] = round(max(lat), 1) if lat else 0
        rep["suggest"] = _suggest_latency(store, home)
        if verbose:
            _print(rep)
        return rep
    finally:
        winapi.known_folder = old_known
        if store is not None:
            store.close()
        shutil.rmtree(root, ignore_errors=True)


def _suggest_latency(store, home):
    """Suggestions while typing each question letter by letter (with some history kept)."""
    from nobadfind import history, suggest
    from nobadfind.understand import place_bases
    for q in ("invoice pdf in downloads", "budget in projects", "2 boys in an image"):
        history.add(store, q)
    bases = place_bases([home], [])
    lat = []
    for item in QUERIES[:20]:
        for i in range(1, len(item["q"]) + 1):
            t = time.perf_counter()
            suggest.suggest(store, item["q"][:i], bases=bases)
            lat.append((time.perf_counter() - t) * 1000)
    lat.sort()
    return {"n": len(lat), "p50": round(statistics.median(lat), 2), "p90": round(lat[int(0.9 * (len(lat) - 1))], 2),
            "max": round(lat[-1], 2)}


def _print(rep):
    print(f"models: {', '.join(rep['models']) or 'none (keywords only)'}; pictures drawn: {rep['pictures']}; "
          f"index built in {rep['build_s']} s")
    for q, need in rep["skipped"]:
        print(f"  skipped (needs the {need} model): {q}")
    print(f"{'question':48} {'type':9} r@1 r@5  RR  parts  guess")
    for x in rep["rows"]:
        g = "-" if x["best"] is None else ("ok " if x["best_ok"] else "WRONG ") + str(x["best_reason"])
        flag = "" if x["r1"] and x["parts_ok"] else "   <-- top: " + ", ".join(map(str, x["top"]))
        if not x["parts_ok"]:
            flag += f" parts {x['parts']}"
        print(f"{x['q'][:48]:48} {x['type']:9} {x['r1']:.0f}   {x['r5']:.0f}  {x['rr']:.2f} "
              f"{'ok' if x['parts_ok'] else 'NO':5}  {g}{flag}")
    for k in ("keywords", "meaning", "photo", "all"):
        if rep[k]:
            print(f"{k:9} {json.dumps(rep[k])}")
    print(f"search latency ms p50 {rep['lat_p50']} p90 {rep['lat_p90']} max {rep['lat_max']}; "
          f"suggest per keystroke {json.dumps(rep['suggest'])}")


def failures(rep):
    out = []
    for k, v in THRESHOLDS.items():
        if rep["keywords"] and rep["keywords"].get(k, 1.0) < v:
            out.append(f"keywords {k} {rep['keywords'][k]} < {v}")
    for k, v in PHOTO_THRESHOLDS.items():
        if rep["photo"] and rep["photo"].get(k, 1.0) < v:
            out.append(f"photo {k} {rep['photo'][k]} < {v}")
    if rep["meaning"] and rep["meaning"].get("recall5", 1.0) < MEANING_RECALL5:
        out.append(f"meaning recall5 {rep['meaning']['recall5']} < {MEANING_RECALL5}")
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--models-dir", default="", help="a data folder with model/ and/or photo-model/ (copied)")
    ap.add_argument("--check", action="store_true", help="exit 1 when a score is under the thresholds")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    rep = run(args.models_dir or None, verbose=not args.json)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False))
    bad = failures(rep)
    for b in bad:
        print("FAIL:", b)
    return 1 if (args.check and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
