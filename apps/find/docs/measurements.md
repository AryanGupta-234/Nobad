# NOBAD Find: measurements

Numbers decide (ROADMAP §3). Every performance claim points at a row here. Newest first. Working set = RAM in use
now; private = committed memory only this process can use (`Get-Process` `WorkingSet64` / `PrivateMemorySize64`,
summed over the process tree).

## 2026-11-19 (0.8.0 engine): text models, English and Hindi search quality, whole-PC search speed

- **Branch:** `find-0.8-engine` (PR #80). **PC:** the reference PC (i5-12500H, 16 threads, 15.7 GB, Windows 11).
- **Models:** every candidate was fetched once through the engine's own `embed._fetch_verified` (pinned revision,
  exact size, SHA-256) into a throwaway data folder, never the real index. Licences were checked on each model's
  card; only MIT and Apache-2.0 are used. OpenAI CLIP isn't one of them.
- **Search quality:** `python tools/eval_text.py --models-dir <throwaway> --set english|hindi`. The test sets are
  `tools/evalset/*.json`, all content made up:
  - **English:** 112 personal files (letters, bills, a lease, payslips, insurance, recipes, READMEs, travel plans;
    8 long ones with the answer deep inside) and 68 questions: 31 paraphrases with no shared word, 21 keyword and
    16 mixed.
  - **Hindi:** 40 files (Devanagari, Hinglish, mixed) and 43 questions: 15 Hindi, 14 Hinglish, 14 cross-language.

  The files are indexed by the engine's own code (extract, chunks, name and chunk vectors) and each question goes
  through the real `search.search()`. **Model alone** = the best vector per file, with no keywords, filters or
  floors. **Search** = what a user gets. RAM is one process holding the model (the main process for questions;
  the meaning worker holds its own copy while indexing). Passages/s are while indexing, on 8 threads.
- **Not kept:**
  - LaBSE: its ONNX build lacks the final pooling layer, and it scores lower;
  - paraphrase-multilingual-MiniLM: lower everywhere;
  - l3cube Hindi / Indic SBERT (CC-BY-4.0): no ONNX build, and converting needs PyTorch;
  - arctic-embed s / m, nomic-embed v1.5, gte-base, bge-small: no better than GTE small and slower;
  - bge-m3: about as good as multilingual-e5-small on Hindi, but 17x slower to index and 821 MB;
  - SigLIP 2 large: about 880 MB, too big for a question encoder in the main process.

  Their numbers are below. The ONNX OCR (PaddleOCR / RapidOCR, Apache-2.0) is available, but its text detector needs
  OpenCV-style contour work that isn't in the locked dependencies; it's left for later (see Still open).

#### Text models

#### English set

| Model | MB | RAM MB (1 process) | Passages/s | Model alone R@5 / MRR / nDCG | 0.7.0 search nDCG | 0.8.0 search R@5 / MRR@10 / nDCG@10 | Search p50 / p90 ms |
|---|---|---|---|---|---|---|---|
| keywords only (no model) | - | - | - | - | 0.309 | 0.382 / 0.382 / 0.382 | 0.9 / 1.1 |
| minilm-l6-v2 | 23 | 38 | 32.9 | 0.941 / 0.871 / 0.883 | 0.756 | 0.897 / 0.836 / 0.847 | 6.2 / 9.7 |
| gte-small | 33 | 56 | 54.3 | 0.941 / 0.880 / 0.903 | 0.801 | 0.897 / 0.864 / 0.873 | 6.7 / 8.3 |
| bge-small-en-v1.5 | 33 | 54 | 26.5 | 0.934 / 0.876 / 0.891 | 0.771 | 0.882 / 0.842 / 0.851 | 12.5 / 23.0 |
| arctic-embed-s | 33 | 54 | 23.4 | 0.875 / 0.801 / 0.832 | 0.732 | not run | 12.0 / 24.0 |
| gte-base | 106 | 128 | 12.9 | 0.941 / 0.898 / 0.908 | 0.785 | 0.897 / 0.859 / 0.864 | 15.2 / 18.8 |
| bge-base-en-v1.5 | 106 | 125 | 16.3 | 0.949 / 0.909 / 0.917 | 0.778 | 0.882 / 0.859 / 0.864 | 24.9 / 36.7 |
| arctic-embed-m-v1.5 | 106 | 127 | 11.8 | 0.926 / 0.849 / 0.872 | 0.738 | 0.875 / 0.811 / 0.822 | 24.1 / 33.3 |
| nomic-embed-text-v1.5 | 131 | 152 | 8.5 | 0.941 / 0.854 / 0.876 | 0.756 | 0.868 / 0.810 / 0.821 | 27.8 / 33.6 |
| multilingual-e5-small | 129 | 385 | 30.2 | 0.868 / 0.824 / 0.846 | 0.732 | 0.801 / 0.766 / 0.785 | 11.1 / 18.0 |
| multilingual-e5-base | 282 | 544 | 8.3 | 0.897 / 0.856 / 0.882 | 0.780 | 0.868 / 0.815 / 0.824 | 19.0 / 27.9 |
| paraphrase-multilingual-minilm | 122 | 386 | 14.0 | 0.904 / 0.828 / 0.855 | 0.724 | 0.846 / 0.801 / 0.817 | 8.3 / 19.9 |
| labse | 463 | 560 | 5.7 | 0.775 / 0.683 / 0.706 | 0.613 | not run | 28.1 / 66.0 |
| bge-m3 | 560 | 821 | 3.1 | 0.985 / 0.887 / 0.912 | 0.759 | 0.838 / 0.797 / 0.800 | 25.8 / 32.0 |

By kind of question (0.8.0 search nDCG@10): keyword, mixed, paraphrase

| Model | keyword | mixed | paraphrase |
|---|---|---|---|
| keywords only (no model) | 0.952 | 0.375 | 0.000 |
| minilm-l6-v2 | 0.995 | 0.995 | 0.671 |
| gte-small | 0.995 | 0.989 | 0.731 |
| bge-small-en-v1.5 | 0.995 | 0.976 | 0.690 |
| gte-base | 0.997 | 0.989 | 0.709 |
| bge-base-en-v1.5 | 0.996 | 0.987 | 0.712 |
| arctic-embed-m-v1.5 | 0.995 | 0.976 | 0.627 |
| nomic-embed-text-v1.5 | 0.996 | 0.976 | 0.623 |
| multilingual-e5-small | 1.000 | 0.989 | 0.535 |
| multilingual-e5-base | 0.996 | 0.953 | 0.642 |
| paraphrase-multilingual-minilm | 0.987 | 0.935 | 0.640 |
| bge-m3 | 0.998 | 0.953 | 0.586 |

#### Hindi set

| Model | MB | RAM MB (1 process) | Passages/s | Model alone R@5 / MRR / nDCG | 0.7.0 search nDCG | 0.8.0 search R@5 / MRR@10 / nDCG@10 | Search p50 / p90 ms |
|---|---|---|---|---|---|---|---|
| keywords only (no model) | - | - | - | - | 0.209 | 0.233 / 0.233 / 0.233 | 0.5 / 0.7 |
| minilm-l6-v2 | 23 | 38 | 84.4 | 0.663 / 0.542 / 0.570 | 0.420 | 0.535 / 0.473 / 0.497 | 4.3 / 5.3 |
| gte-small | 33 | 56 | 36.8 | 0.674 / 0.514 / 0.562 | 0.454 | 0.593 / 0.525 / 0.546 | 9.2 / 15.5 |
| bge-small-en-v1.5 | 33 | 54 | 31.7 | 0.698 / 0.525 / 0.580 | 0.469 | 0.640 / 0.544 / 0.572 | 10.5 / 12.9 |
| arctic-embed-s | 33 | 54 | 41.8 | 0.547 / 0.482 / 0.537 | 0.456 | not run | 11.2 / 14.6 |
| gte-base | 106 | 128 | 13.1 | 0.674 / 0.517 / 0.569 | 0.446 | 0.570 / 0.477 / 0.520 | 12.7 / 15.9 |
| bge-base-en-v1.5 | 106 | 125 | 8.7 | 0.698 / 0.589 / 0.635 | 0.479 | 0.593 / 0.537 / 0.567 | 28.2 / 48.7 |
| arctic-embed-m-v1.5 | 106 | 127 | 13.0 | 0.698 / 0.604 / 0.640 | 0.477 | 0.628 / 0.546 / 0.571 | 29.2 / 41.1 |
| nomic-embed-text-v1.5 | 131 | 152 | 16.1 | 0.663 / 0.522 / 0.563 | 0.458 | 0.581 / 0.503 / 0.525 | 15.3 / 22.4 |
| multilingual-e5-small | 129 | 385 | 56.3 | 0.965 / 0.923 / 0.932 | 0.726 | 0.860 / 0.810 / 0.823 | 6.6 / 9.2 |
| multilingual-e5-base | 282 | 544 | 8.7 | 0.953 / 0.834 / 0.861 | 0.719 | 0.837 / 0.798 / 0.808 | 18.4 / 30.2 |
| paraphrase-multilingual-minilm | 122 | 386 | 36.2 | 0.919 / 0.704 / 0.757 | 0.569 | 0.791 / 0.640 / 0.691 | 7.1 / 10.8 |
| labse | 463 | 560 | 23.4 | 0.895 / 0.727 / 0.771 | 0.626 | not run | 10.9 / 17.6 |
| bge-m3 | 560 | 821 | 3.3 | 0.977 / 0.905 / 0.921 | 0.720 | 0.837 / 0.791 / 0.802 | 36.3 / 53.5 |

By kind of question (0.8.0 search nDCG@10): cross, hindi, hinglish

| Model | cross | hindi | hinglish |
|---|---|---|---|
| keywords only (no model) | 0.071 | 0.267 | 0.357 |
| minilm-l6-v2 | 0.128 | 0.498 | 0.865 |
| gte-small | 0.214 | 0.548 | 0.876 |
| bge-small-en-v1.5 | 0.197 | 0.638 | 0.876 |
| gte-base | 0.147 | 0.557 | 0.853 |
| bge-base-en-v1.5 | 0.153 | 0.661 | 0.879 |
| arctic-embed-m-v1.5 | 0.206 | 0.625 | 0.879 |
| nomic-embed-text-v1.5 | 0.071 | 0.619 | 0.879 |
| multilingual-e5-small | 0.733 | 0.875 | 0.857 |
| multilingual-e5-base | 0.688 | 0.875 | 0.857 |
| paraphrase-multilingual-minilm | 0.549 | 0.702 | 0.822 |
| bge-m3 | 0.674 | 0.871 | 0.857 |

#### The search changes, one at a time (English, search nDCG@10)

| Variant | none | minilm-l6-v2 | gte-small | bge-base-en-v1.5 |
|---|---|---|---|---|
| base | 0.309 | 0.756 | 0.802 | 0.777 |
| nofloor | 0.309 | 0.771 | 0.801 | 0.779 |
| noweak | 0.309 | 0.756 | 0.801 | 0.777 |
| fts_or | 0.459 | 0.534 | 0.539 | 0.535 |
| synonyms | 0.309 | 0.757 | 0.801 | 0.771 |
| rrf_equal | 0.309 | 0.756 | 0.801 | 0.777 |
| meaning_up | 0.309 | 0.756 | 0.802 | 0.778 |
| floors + soft time + no folder meaning (0.8.0) | 0.382 | 0.847 | 0.873 | 0.864 |
| floors only (soft time and folder rule off) | 0.309 | 0.771 | 0.793 | 0.774 |


**What the 0.8.0 search changes did:** the 0.7.0 search lost 0.08-0.14 nDCG against the model alone. The causes,
found query by query:
1. A time word became a filter on when the file changed ("electricity bill march" found nothing, because the March
   bill changed in April). Now, when such a filter matches no file, the time is read as words and a note says so.
2. Folders had name vectors and filled the meaning results ("Documents/Home" for "where I live"). They now count
   only when folders are asked for.
3. Each model scores on its own scale, so one set of floors for every model was wrong. The floors are now measured
   per model (5th percentile of right answers, 95th percentile of their distance to the best match) and live in the
   catalog.

Keeping only what won: OR-ed keywords, synonyms, equal or higher fusion weights and dropping the floors alone each
changed nDCG by under 0.02 or made it worse (OR: -0.22), so they stay off and remain as switches in
`search.VARIANTS` to measure again. Not tried yet: a cross-encoder reranker and longer-document chunking.

**What was picked** (`nobadfind/models.py`):

| Tier | English first | Many languages | Hindi |
|---|---|---|---|
| Light | GTE small (33 MB, 56 MB RAM, 0.873) | all-MiniLM-L6-v2 | all-MiniLM-L6-v2 |
| Balanced | GTE small | multilingual-e5-small (129 MB, 385 MB RAM; Hindi 0.823) | multilingual-e5-small |
| Best | GTE small (BGE base is offered; no better here, 3x slower) | multilingual-e5-base | multilingual-e5-small |

The focus is recommended from Windows' display and keyboard languages: a Hindi language means Hindi, another
non-English one means many languages, else English first. The user can change it (`model_language`). On a Light PC
(< 8 GB or ≤ 4 cores) a Hindi or many-languages user still gets all-MiniLM, because e5 small holds 385 MB in each
process that loads it.

**Where e5's memory goes:** 256 MB of its 385 MB is the tokenizer (`tokenizers` with XLM-R's 250,000-piece
vocabulary) and 130 MB the ONNX session; for all-MiniLM those are 7 and 32 MB. The graph optimisation level changes
nothing (383-385 MB at every level).

#### Photo models

| Model | Download | Question encoder RAM (main) | Photo worker RAM (vision) | A question | 16 pictures, English: right one first / mean rank | Hindi questions: mean rank (8.5 = chance) |
|---|---|---|---|---|---|---|
| SigLIP base | 211 MB | 156 MB | 144 MB | 56-65 ms | 16/16, 1.0 | 8.5 |
| SigLIP 2 base | 393 MB | 370 MB | 139 MB | 63 ms | 16/16, 1.0 | **3.6** |

The pictures are made-up coloured shapes (4 colours x 4 shapes), with questions like "a red circle" / "लाल गोला".
SigLIP 2 base is the Best tier's photo model: same speed, and it understands Hindi questions somewhat. It costs
another 214 MB in the main process while photo meaning is in use.

#### Search speed at whole-PC scale (`python tools/bench_search.py --rows 1000000`)

A synthetic index of 998,212 file entries (realistic names, folders and kinds, no text or vectors). 16 questions
are typed one letter at a time through `search.search()`; the cache is warm.

| Per keystroke | 0.8.0 before the fix: p50 / p90 / max | After: p50 / p90 / max |
|---|---|---|
| 1-2 letters (30) | 467 / 539 / 641 ms | **6.8 / 12.6 / 13.7 ms** |
| Names, 3+ letters (44) | 169 / 238 / 357 ms | **16.9 / 22.5 / 24.0 ms** |
| Several words (16) | 88 / 295 / 317 ms | **20.4 / 39.8 / 46.7 ms** |

- One or two letters used `name LIKE '%ta%'`, a scan of every row. They now use `names_w`: the words of every name
  in an FTS5 table with a prefix index, matching names with a word that starts with them. It's filled once in the
  background (6.5 s at a million entries), then kept up by triggers.
- "photos" alone (every photo, newest first) sorted them all: a `files(kind, mtime)` index fixed it (318-485 ms →
  under 25 ms).
- At most 2,000 name matches are looked at per question.
- A newer keystroke from the same pipe client cancels the search still running (SQLite progress handler). Its answer
  would be thrown away anyway.
- #79 measured p90 2.5 s / max 13 s on a real 940k-entry index with text, where the same scans were the cause. This
  bench has no text chunks, so a run on #79's index is the check still to do after both are merged.

#### Still open
- ONNX OCR for Devanagari: Windows OCR has no Hindi at all (Windows.Media.Ocr doesn't support hi-IN; this PC has
  en-GB, en-US and pt-BR). The PaddleOCR / RapidOCR models (Apache-2.0) exist, but need a text detector with
  contour post-processing; not built.
- A cross-encoder reranker (Best tier) and chunking tuned for long documents: not tried.
- e5's 256 MB tokenizer in each process: a smaller tokenizer (or one shared process for the question encoders) would
  bring the many-languages tiers down a lot.
- #79's "closed engine at about one core" from its backlog wasn't reproduced here (this branch doesn't have #79).
## 2026-11-19 (evening): a whole PC by name (the new default scope), and the turbo helper's own parts

- **Why:** the new defaults (maintainer decision 2026-11-19) index Windows, Program Files, ProgramData and AppData too
  (`include_system`, `include_caches` on), which 0.7.0's walk skipped, so the budgets were checked on the real fixed
  drives of the reference PC (16 threads, 15.7 GB, SSD). 0.7.0's own count on this PC wasn't measured. The walk is
  read-only, and the index went to a throwaway folder in %TEMP%, never the real one.
- **How:** `python tools/measure.py --whole-pc --files 20 --levels full ...` (new option: names only, real Whole PC
  scope, level fixed at Full, engine from source). Other agents were using the PC at the same time, so times vary
  run to run (436-534 s for the same scan).
- **The turbo index was not run:** it needs an elevated process (a UAC prompt for the maintainer). These are the
  walker's numbers to compare it with, plus the turbo helper's pure-Python parts on synthetic buffers of the same size.

### Walker only, no store (the walk itself, one process)

| | Entries | Folders | Time | CPU | Peak private |
|---|---|---|---|---|---|
| `Walker`, 32 threads, Whole PC rules, C: only, nothing written | 853 845 | 182 670 | 63 s | 124 CPU-s (2.0 cores) | 37 MB |
| same, writing into the encrypted store | 854 297 | 182 845 | 266 s | 292 CPU-s (1.1 cores) | 314 MB |

The store is the bottleneck, not the walk: about 3 200 rows/s into SQLCipher with the FTS5 trigram index on names.
The index is 953 MB for 854k names. **Turbo can only take away the 63 s walk part**; the inserts stay.

### The engine, a whole PC by name (`--whole-pc`, level Full)

| Commit | Entries | Name scan | Private MB while indexing (mean / max) | CPU while indexing | Idle, window open: CPU, reads | Window closed: CPU, reads | Search keystroke p50 / p90 / max |
|---|---|---|---|---|---|---|---|
| `a02d96f` (scope, before the two fixes below) | 941 697 | 436 s | 292 / 373 | 1.5 cores | 108 %, 145 MB/s | 219 %, 274 MB/s | 10.7 ms / 3 783 ms / 7 843 ms |
| `2e65ac1` (own data folder out, watching loop counts every 30 s) | 941 080 | 534 s | 313 / 375 | 1.4 cores | 99 %, 109 MB/s | 103 %, 112 MB/s | (not recorded) |
| `ece6784` (status counts cached by their cost) | 822 000 | 435 s | 289 / 353 | 1.0 core | **46 %, 48 MB/s** | 100 %, 129 MB/s | 13.4 ms / 2 505 ms / 13 011 ms |

CPU in % of one core. Idle with no UI: 0.4 % and 49 MB private in every run. The entry count changes between runs
because other programs (and agents) created and deleted files on the PC meanwhile.

Against the ROADMAP budgets:
- **Indexing ≤ 600 MB private: met** (max 353-375 MB for a whole PC by name, one process).
- **Window open, idle, engine ≤ 120 MB: at the edge** (119 MB mean, 132 MB max).
- **Search ≤ 80 ms for names: missed on a whole PC.** The median is fine (13 ms), but a question of one or two letters
  (each keystroke of "i", "in") is a `name LIKE '%i%'` over every row sorted by name length: 2.5 s at the 90th
  percentile, up to 13 s. Those searches queue on the pipe's 4 threads, which is most likely also the ~1 core and
  ~130 MB/s still seen "closed" (the closed scenario starts right after the typing). Open item for `search.py`
  (not changed here): skip or bound one- and two-letter name scans, and drop a search the next keystroke replaced.
- **Closed ≤ 60 MB: missed** (135 MB private; see the search backlog above, re-measure after the search fix).

### The turbo helper's Python work, synthetic (183 000 folders, 671 000 files, paths ~120 characters)

| Step | Time | Note |
|---|---|---|
| Parse the `FSCTL_ENUM_USN_DATA` buffers (854k `USN_RECORD_V2`) | 3.7 s per pass | two passes: folders first, then everything |
| Folder pass (the tree) | 4.5 s | |
| Filter and paths for every entry (scope rules, other profiles, metafiles) | 16.5 s | per folder once, per file a dict look-up |
| Parse one MFT record (fixups, `$STANDARD_INFORMATION`, `$DATA`) | 8.7 µs | 7.5 s for 854k; the `FSCTL_GET_NTFS_FILE_RECORD` calls themselves are on top and need the elevated run |
| Memory for the tree, the filter and the paths | +81 MB | in the helper process, not the engine |

About 35 s of one core in Python before the ioctls, against the walker's 63 s on two cores. The real comparison
(enumeration time, ioctl cost per file for both size/time options, change-journal latency) is what
`python -m nobadfind --turbo selftest` prints from an elevated terminal: to be added after the maintainer's run.

### Two fixes this found

- **Indexing its own database:** with AppData included and the index in %TEMP% (`NOBAD_FIND_DATA_DIR`), the engine
  indexed its own database writes, a feedback loop. NOBAD Find's data folder is now always out (`scope.Rules.own`);
  the real one was already out through the `nobad` name.
- **Counting a million rows on every poll:** after the scan, the engine still used ~1 core and read ~100 MB/s while
  idle (first two runs above). `Api.status` ran `Store.stats` (six `COUNT`s over every row) on every 2 s poll of the
  Indexing page, and the watching loop ran it every round. Now counts are reused for 10 s or 20x as long as they took
  (`api.STATS_TTL`, `COUNT_SHARE`; `indexer.STATS_EVERY`).

## 2026-11-19 (later): with both models, every process, and ONNX Runtime tuning

- **Commits:** before = `afd5581` (the review fixes for #78 + the harness's model scenarios, no tuning); after = the
  tuning commit on `find-measure`.
- **Same PC.** Engine started through `packaging/launch.py` (`--entry launch`, how the exe starts workers) with a
  venv built from `requirements-lock.txt` (`--python`), not the global Python.
- **Models:** all-MiniLM-L6-v2 (meaning) and SigLIP base (photos), fetched once through the engine's own
  `embed._fetch_verified` (pinned, SHA-256 checked) into a throwaway data folder, then linked into each run's fresh
  temp index. Never the real index or settings. Meaning, photo meaning and OCR on.
- **Corpus:** `--files 1000 --photos 150 --text-images 60`: the 1,000 generated documents (as before, 120 PDFs),
  150 camera-style JPEGs (gradient skies, sun, hills, shapes, grain; 640x480 to 1024x768), 60 screenshots with
  words for OCR. 2,107 index entries, 1,140 with text, 2,874 chunks, 270 images for the photo model.
- **Scenarios** (Gentle runs them all; Full and Light only index): indexing; warm searches (4 meaning questions and
  4 photo questions typed one letter at a time); models loaded and idle; waiting for `embed.Lazy` to release them
  (163 s here); released and idle; a cold search; window closed; reopen and type at once.
- Process roles come from the engine's own `status_full` (a second pipe connection, every 2 s). "Not yet named" =
  a worker the 2-second poll hadn't seen named yet. The venv launcher and the console host are left out of totals.

### What ONNX Runtime does with the models (isolated runs, real models, one fresh process per variant)

| Meaning worker (512 chunks, 8 threads) | Private after | Peak | Chunks/s |
|---|---|---|---|
| batch 64, arena on, mem pattern on (before) | **1,119 MB** | 1,145 MB | 30 |
| batch 64, arena off | 51 MB | 612 MB | 17 |
| batch 64, arena and mem pattern off | 51 MB | 508 MB | 23 |
| batch 64, mem pattern off | 1,119 MB | 1,144 MB | 31 |
| batch 64, `arena_extend_strategy` = kSameAsRequested | 1,362 MB | 1,388 MB | 32 |
| batch 16, arena on | 318 MB | 323 MB | 40 |
| batch 8, arena on | 185 MB | 187 MB | 40 |
| **batch 4, arena on (after)** | **113-115 MB** | 116 MB | **39-40** |
| batch 2 / 1, arena on | 78 / 59 MB | | 43 / 39 |
| batch 4 at 4 / 2 / 1 threads | | | 25-48 / 15-33 / 19 |

Batch 64 sequences of up to 256 tokens make the attention tensors big, and ONNX Runtime's arena keeps the peak.
Turning the arena off frees it but runs 25-45 % slower. Smaller batches fix both. Memory pattern made no difference,
and kSameAsRequested was worse. Threads: 8 beat 4 on repeat runs (one outlier aside), so the thread rule stays.

**Search quality.** All-MiniLM is dynamically quantized, so padding in a batch shifts the numbers a little: every
batch size is about the same distance from unpadded (batch 1) vectors, cosine mean 0.992 (min 0.98). Nearest-neighbour
lists agree as well with batch 4 as with batch 64: 77.7 % vs 76.8 % of top-10 neighbours shared with the unpadded
vectors. Arena and memory-pattern settings give bit-identical vectors.

| Other sessions (isolated) | Before | After |
|---|---|---|
| Photo model, vision (photo worker), photos/s at 2 / 4 / 8 threads | fixed 2 threads: 2.4 | threads by level: 4.7 / 7.1-7.5 at 4 / 8 |
| Photo question (SigLIP text, main process), ms per question at 2 / 4 threads | 45 ms (2 threads) | **28 ms** (4 threads) |
| Meaning question (MiniLM, main process) | 1.3 ms | unchanged |
| Arena on/off for these three | ≤ 30 MB difference, arena on faster | left on |

Vectors are already float16 in memory and in the index (`embed.to_blob`, `VectorIndex._mat`). That's 768 bytes per
text vector and 1.5 KB per photo vector: about 5 MB for this index, so there's nothing cheap left there.

### Changes kept

1. `embed.BATCH` 64 → 4: the meaning worker keeps 115 MB instead of 1.1 GB and runs faster.
2. The photo worker's threads follow the level, like the meaning worker (`min(cores / 2, readers for the level)`):
   8 at Full and Gentle on this PC, 1 at Light. Before: always 2.
3. The photo question encoder in the main process uses 4 threads instead of 2.

### Before → after, indexing (1,000 files + 150 photos + 60 screenshots)

| Level | Wall time | Find's private MB, mean / max | Meaning worker MB | Meaning chunks/s | Photos/s |
|---|---|---|---|---|---|
| Full | 132 s → **84 s** | 734 / 1,230 → **246 / 663** | 1,149 → **154** | 43 → **75** | 4.7 → **7.2** |
| Gentle | 190 s → **131 s** | 803 / 1,246 → **233 / 338** | 1,152 → **152** | 26 → **44** | 3.8 → **4.4** |
| Light | 615 s → **576 s** | 935 / 1,242 → **225 / 313** | 1,143 → **149** | 6.5 → **9.4** | 1.8 → 1.1 |

Text 150-250 files/s and OCR'd images 27-135/s were the same in both runs. At Light, photos got slower because the
photo worker now has 1 thread instead of 2 (Light means a game or a busy PC). The whole run is still faster.

### Before → after, the window and search (Gentle run)

| | Before | After |
|---|---|---|
| Meaning search while typing, p50 / p90 / max | 105 / 163 / 180 ms | **42 / 118 / 187 ms** |
| Photo search while typing, p50 / p90 / max | 108 / 123 / 146 ms | **42 / 50 / 53 ms** |
| First search with the models out of memory (both load) | 848 ms | 810 ms |
| Window reopened, typing at once | 957 ms | 627 ms |
| Main process, models loaded, idle | 303 MB private / 291 MB working set | 304 / 292 (unchanged) |
| Main process, models released (163 s idle) | 129 / 119 MB | 125 / 116 MB |
| Window closed (models released, working set handed back) | 134 MB private, 40 MB working set | 143 / 42 MB |

Every keystroke runs both question encoders, so the 28 ms photo encoder sets the floor; the meaning budget
(≤ 250 ms) is met. The first search after a release pays about 0.6-0.8 s for loading both models.

### Every process, after (per process: private and working set, mean / max; handles mean)

| Level | Scenario | Process | At once (pids seen) | Private MB | Working set MB | Handles |
|---|---|---|---|---|---|---|
| Gentle | idle, no UI | Main | 1 | 48 | 66 | 354 |
| Gentle | indexing | Main | 1 | 65 / 72 | 83 / 90 | 394 |
| Gentle | indexing | Text reader | 8 (16) | 31 / 43 | 45 / 56 | 224 |
| Gentle | indexing | Meaning worker | 1 | 152 / 157 | 171 / 177 | 224 |
| Gentle | indexing | Photo worker | 1 | 186 / 240 | 193 / 243 | 293 |
| Gentle | warm searches | Main | 1 | 300 / 305 | 288 / 291 | 380 |
| Gentle | models loaded, idle | Main | 1 | 304 | 292 | 380 |
| Gentle | models released, idle | Main | 1 | 125 / 130 | 116 / 120 | 368 |
| Gentle | window closed | Main | 1 | 143 / 309 | 42 / 296 | 364 |
| Full | indexing | Main | 1 | 65 / 72 | 84 / 90 | 397 |
| Full | indexing | Text reader | 15 (15) | 31 / 54 | 42 / 62 | 177 |
| Full | indexing | Meaning worker | 1 | 154 / 158 | 172 / 178 | 224 |
| Full | indexing | Photo worker | 1 | 186 / 243 | 195 / 218 | 291 |
| Light | indexing | Main | 1 | 66 / 72 | 85 / 90 | 391 |
| Light | indexing | Text reader | **1** (3) | 39 / 55 | 50 / 60 | 241 |
| Light | indexing | Meaning worker | 1 | 149 / 153 | 155 / 170 | 213 |
| Light | indexing | Photo worker | 1 | 181 / 241 | 183 / 216 | 282 |

Before, the meaning worker was 1,143-1,152 MB private at every level, and everything else was within a few MB of
the after numbers. The phases run one after another (text, images, meaning, photos), so the readers, the meaning
worker and the photo worker are never all alive at once. Light now really runs one reader (the recycling fix).

### The worker memory limit with the models

The limit is a quarter of RAM, 1-4 GB. The most the workers committed at once is now 663 MB (Full, 15 readers),
and 338 MB at Gentle. On a 4 GB PC the limit is 1 GB, and the workers stay well under it: readers for 4 threads plus
a 160 MB meaning worker or a 240 MB photo worker. Before the batch change, the meaning worker alone (1.15-1.18 GB)
would have been over a 4 GB PC's limit: it would have failed to load, and kept failing (it now backs off). DirectML
(the graphics-card build of ONNX Runtime) isn't shipped or installed here, so its memory isn't measured.

### Still open
- **The main process keeps about 75 MB after the models are released.** It's 125 MB vs 48 MB before loading, so the
  window-closed state is 143 MB private (42 MB working set) with models in use: over the 60 MB budget. In isolation a
  load-and-release gives it back (225 → 44 MB, three rounds, no growth). Suspects: per-thread ONNX Runtime buffers on
  the pipe's 4 worker threads, which run the questions, and SQLite's cache. Next step: encode questions on one
  dedicated thread and measure.
- Meaning search p90 118 ms and max 187 ms while typing: the ranking, plus both encoders on every keystroke.

## 2026-11-19: engine baseline with `tools/measure.py`, and the Phase 1 engine diet

- **Commits:** baseline `b945911` (= `find-flutter-prototype` `1e8a1e2` + the harness); after = the Phase 1 commit on
  branch `find-measure`.
- **PC:** the maintainer's (i5-12500H, 16 threads, 15.7 GB, Iris Xe, Windows 11 26300). Nothing else heavy running.
- **How:** `python tools/measure.py --files 3000 [--entry launch]` (dev only, see its docstring). 3,000 generated files
  (750 txt, 390 png, 360 pdf, 300 docx, 300 py, 240 md, 240 csv, 150 html, 150 json, 120 eml; 7.5 MB) → 5,161 index
  entries, 2,790 with text, 8,314 chunks. Each level runs on a fresh temp index with the level fixed
  (`NOBAD_FIND_MEASURE_LEVEL`) and its own pipe (`NOBAD_FIND_MEASURE_PIPE`), so it can run next to another engine.
  The harness samples every process in the engine's tree once a second. No models: the meaning and photo models
  aren't downloaded on this PC, so ONNX Runtime isn't in these numbers. Only processes the harness started were
  stopped, by PID.
- **`--entry launch`** starts the engine through `packaging/launch.py`, the script `NobadFind.exe` runs. That matters:
  a pool worker runs the parent's entry *script* again, but multiprocessing never re-runs a package's `__main__`, so
  `python -m nobadfind` workers looked fine while the shipped exe's didn't.
- Private = committed memory (`PagefileUsage`), working set = RAM in use, both summed over the tree. CPU % is of one
  core. Means over the scenario's samples, then the max.

### The ~4 GB commit, found

| | Private while indexing, Gentle (mean / max) | Full | Per text reader | Engine alone, idle |
|---|---|---|---|---|
| Baseline, `--entry launch` (like the exe) | **4,460 / 4,866 MB** | **8,002 / 8,474 MB** | 544 MB | 518 MB |
| After | **390 / 608 MB** | 549 / 689 MB | ≤ 60 MB | 34 MB |

Both causes come from numpy's OpenBLAS. As it loads, it commits about 32 MB per CPU thread: 515 MB on 16 threads
(measured: 1 thread 19 MB, 2 threads 53 MB, 4 threads 120 MB, 8 threads 255 MB, 16 threads 525 MB).
1. `packaging/launch.py` imported `nobadfind.app` at the top, so every worker of the exe loaded the whole app, numpy
   included (`-X importtime`: 0.78 s, 0.68 s of it numpy). Now the import comes after `freeze_support()`. A reader
   imports only `extract`: 35 ms, down from 219 ms, now that mail parsing loads only for .eml/.mbox files.
2. The main process paid the same cost. `nobadfind/__init__.py` now loads numpy with `OPENBLAS_NUM_THREADS=1`, then
   puts the variable back so programs Find opens don't inherit it (a value the user set wins). One thread is as fast
   or faster for Find's numpy work: scoring a 65,536 x 384 block takes 47.8 ms on 1 thread vs 47.4 ms on 16; the PCA
   fit (SVD of 8,000 x 384) takes 0.47 s on 1 thread vs **4.1 s** on 16.

### Indexing got 3-6x faster: background mode was thrashing the readers

Windows background mode (`PROCESS_MODE_BACKGROUND_BEGIN`) is what every worker used. Entered as a process starts, it
pins the working set near 32 MB, and a reader parsing PDFs then page-faults constantly. 30 PDFs in a real pool worker
took **6.2 s with 3.0 million page faults** (4.6 s of it kernel time), against **0.31 s and 7 thousand** at normal
priority. Workers now set the three priorities themselves (`winapi.worker_priority`): idle CPU class, low memory
priority (2) and very low I/O priority (0). Measured per process: memory 2, I/O 0 (before: 1 and 0, through
background mode).

| Indexing 3,000 files | Baseline `-m` | Baseline `--entry launch` | After (both entries) |
|---|---|---|---|
| Gentle (8 readers, 35 % CPU cap) | 17.1 s, 394 % CPU | 51.1 s, 547 % CPU | **15.0 s**, 180 % CPU |
| Full (15 readers, no cap) | 16.4 s | 58.3 s | **10.0 s**, 390 % CPU |
| Light (meant to be 1 reader, 15 % cap; EcoQoS on) | 50.1 s | | **31.0 s** (with up to 8 readers: see the correction below) |

For the same files, the workers' CPU time fell from 56 core-seconds (baseline `-m`) to about 25. The working set
while indexing is higher (Gentle 308 → 515 MB mean) because the readers are no longer squeezed into 32 MB each. Low
memory priority puts those pages first in line when Windows needs memory back.

### Every scenario, after (`--entry launch`, Gentle; baseline in brackets)

| Scenario | Procs | Working set MB (mean / max) | Private MB (mean / max) | CPU % mean | Handles | Threads |
|---|---|---|---|---|---|---|
| Cold start (5 s) | 2 | 50 / 54 (53 / 56) | **32 / 34** (515 / 519) | 7.1 (12.7) | 365 | 12 (27) |
| Idle, no UI | 2 | 54 (56) | **34** (519) | 0.0 | 365 | 12 |
| Indexing, Gentle | 17 (10)¹ | 515 / 783 (332 / 344) | **390 / 608** (4,460 / 4,866) | 182 (547) | 3,393 | 78 (215) |
| Idle, UI connected | 2 | 88 (90) | **62** (545) | 0.0 | 448 | 16 |
| Search typing | 2 | 96 (98) | **70** (554) | 13.5 | 449 | 13 |
| Window closed (`ui_hidden`) | 2 | **17** / 97 (91 / 99) | **64** / 71 (546 / 554) | 0.1 | 450 | 14 |

The 2 processes are the engine and its console host (it was started from a console). The engine is ready in 0.39 s
and gives its first pipe answer at 0.66 s. Search typing over the pipe (114 keystrokes, 10 questions): round trip
median 2.6 ms, 90th percentile 78 ms, max 94 ms, with 9 keystrokes over 80 ms (baseline: 2.9 / 69 / 105 ms, 5 over).
The pipe adds well under 1 ms. The slow keystrokes are short words that hit text inside files (as in the prototype
run below); that's ranking work, still open.

### Each change, and what it bought

| Change | Before → after | Kept because |
|---|---|---|
| `launch.py` imports the app after `freeze_support()` | 544 → ≤ 60 MB private per reader (exe) | it was the 4 GB commit |
| numpy with one OpenBLAS thread | engine 518 → 34 MB private idle; PCA fit 4.1 → 0.47 s | win |
| Mail parsing imported only for .eml/.mbox | reader import 219 → 35 ms | win (readers restart, see below) |
| `worker_priority` instead of background mode | Gentle 51 → 15 s, Full 58 → 10 s; 3.0 M → 7 k faults per 30 PDFs | win |
| `EmptyWorkingSet` when indexing goes idle (window closed) | closed: 91 → 17 MB working set (engine 10 MB) | win |
| Text readers end after 200 files (`max_tasks_per_child`, replaced, see the correction below) | no growth to give back on this corpus (readers ≤ 60 MB); a restart costs ~35 ms of imports | backstop for pdf/zip heap fragmentation |
| Worker job memory limit (`JOB_OBJECT_LIMIT_JOB_MEMORY`, ¼ of RAM, 1-4 GB) | 4 GB on this PC; normal indexing commits ≤ 0.7 GB | backstop above the watchdog: a worker over it gets a `MemoryError` (already handled) instead of the PC paging. The baseline exe (8 GB at Full) would have hit it, so the import fix had to come first |
| EcoQoS for workers at Light and Paused only | Light 31 s with it; in a test run with EcoQoS at Gentle too, a thrashing reader was 1.6x slower again | Light and Paused mean a game, a call or a busy PC, where staying out of the way matters most; Gentle and Full keep full clocks. The power saving can't be measured here |
| ONNX Runtime arenas | not measured: no model on this PC (and no download) | open |

**Correction (review of #78, 2026-11-19).** ¹ `max_tasks_per_child` on Python 3.11 grows the pool to
`max_workers` (the Full count, 15) each time it replaces a reader, so these runs had up to 15 readers at Gentle
and 8 at Light instead of 8 and 1. The Light time above is therefore with more readers than Light allows. Readers
are now recycled by starting a fresh pool every 200 files per reader, with a test on the process count. The
model runs in the next section use the fixed code.

### Against the ROADMAP budgets

| Budget | Target | Now |
|---|---|---|
| Indexing, Gentle, 16-thread PC | ≤ 600 MB private total | **390 MB mean, 608 MB max** (no models). Met on average. The max came from 15 readers alive at once (the correction below) |
| Window closed (idle process) | ≤ 60 MB, CPU ≈ 0 % | **17 MB working set** (engine alone 10 MB), **64 MB private**, 0.1 % CPU. Private is 4 MB over: Python, SQLCipher, the pipe server and their threads |
| Engine with the window open, idle, models released | ≤ 120 MB | 88 MB working set, 62 MB private |
| Cold start to usable engine | ≤ 1.5 s (window) | engine 0.39 s, first pipe answer 0.66 s |
| Search keystroke | ≤ 80 ms names | median 2.6 ms; 9 of 114 over 80 ms (short words matching text inside files) |
## 2026-11-19: frosted glass redesign, maximized (Phase 3)

- **How:** release build, fake engine (`NOBAD_FIND_FAKE_ENGINE=1`), the window maximized on the 1920 x 1200 (125 %)
  screen, 10 s to settle, then 15 s idle. RAM from `Get-Process`; GPU from the `GPU Process Memory` and
  `GPU Engine` counters for the UI's PID; frames from `NOBAD_FIND_UI_FRAMES` (frames drawn per 5 s).

| Maximized, Home, idle | Working set | Private | GPU memory | GPU busy | CPU | Frames per 5 s |
|---|---|---|---|---|---|---|
| Before (the first full UI) | 152 MB | 156 MB | 76 MB | 0.7 % | 0.05 % | 10 (caret) |
| Redesign, with Flutter blur on the palette (sigma 28) | 296 MB | 300 MB | 117 MB | 2.8 % | 0.16 % | 10 (caret) |
| Redesign, palette blur sigma 12 | 201 MB | 210 MB | 79 MB | 1.5 % | 0.05 % | 10 (caret) |
| **Redesign as shipped** (blur only in dialogs) | **163 MB** | **167 MB** | **72 MB** | 1.2 % | 0.1 % | 10 (caret) |
| Redesign as shipped, window not focused | 160 MB | 163 MB | 73 MB | 0 % | 0.03 % | **0** |

The redesign costs about 11 MB more than the first full UI, mostly the variable font file registered for the thin
display weights (1.8 MB on disk) and the larger glass layers. Flutter's `BackdropFilter` over the palette cost
40-135 MB with only the still backdrop behind it, so it is used for dialogs only; the frost is Windows' Mica (and
Acrylic for the bar), composited by Windows outside this process. Idle and focused, the only frames are the text
caret blinking in the search box (about 2 a second); not focused, nothing is drawn.

## 2026-11-19: full Flutter UI (Phase 3)

- **Branch:** `find-flutter-ui` (draft PR #77), Flutter 3.50, release build, Skia, the same PC as below.
- **How:** the UI process only (`Get-Process` on its PID), sampled once a second. Engine: `python -m nobadfind --engine`
  from source on a throwaway data folder (`NOBAD_FIND_DATA_DIR`) with a 362-file made-up corpus. The UI typed its own
  searches (`NOBAD_FIND_UI_DEMO=1`) or went through every screen (`NOBAD_FIND_UI_DEMO=tour`).

| UI process | Working set | Private | Notes |
|---|---|---|---|
| Main window, Home, just started | 128 MB | 128 MB | real engine |
| Main window after 5 searches | 140 MB | 139 MB | real engine |
| Main window after every screen, dark and light, then 10 s idle | 150-168 MB | 150-162 MB | real engine and fake engine runs |
| Quick find bar, shown with 8 rows | ~140 MB | ~130 MB | |
| Quick find bar, hidden (Esc) | 2-10 MB | 109 MB | hiding empties Skia's cache and the working set |

Skia's GPU resource cache, after the full tour (fake engine): 8 MB cap → 145 MB, 12 MB → 150 MB, 24 MB → 163 MB,
64 MB → 212 MB, 256 MB (Flutter's default) → 207 MB and still growing. The UI caps it at 12 MB
(`NOBAD_FIND_SKIA_CACHE_MB`) and empties it while hidden. The ≤ 100 MB window budget is still missed, as for the
prototype: about 100 MB of each number is the Intel D3D11 driver loaded in-process.

## 2026-11-18: Flutter prototype vs the 0.7.0 WebView2 window (ROADMAP Phase 3 step 1)

- **Commit:** `610921b` (branch `find-flutter-prototype`), Flutter 3.50 stable (Dart 3.14), release build, Skia renderer.
- **PC:** the maintainer's: Intel Core i5-12500H (16 threads), 15.7 GB RAM, Intel Iris Xe, Windows 11 Home 26300.
- **Corpus:** 3,000 generated files (text, Markdown, CSV, JSON, code, small PNGs; 9.9 MB), 2,702 index entries,
  in a temp data folder (`NOBAD_FIND_DATA_DIR`). Same corpus and data folder for every row.
- **How:** a dev-only PowerShell harness (not committed) starts the engine (`python -m nobadfind --engine`, from
  source) and the UI, lets the UI type five fixed searches into its own box (`NOBAD_FIND_UI_DEMO`, one letter
  every 120 ms), then samples memory. The WebView2 row is the 0.7.0 app (`python -m nobadfind`, from source) on
  the same data folder, with its window open about 20 s. Only processes the harness started were stopped, by PID.
- The PC was locked for the first runs, so there are no screen captures from them; the UI saved pictures of itself.

### The window (what the move to Flutter changes)

| Window | Processes | Working set | Private | Notes |
|---|---|---|---|---|
| 0.7.0 WebView2 window, idle, same corpus | 7 | **465 MB** | 238 MB | today's UI (ROADMAP §2 measured 425 / 212 MB on the full index) |
| Flutter main window, just started | 1 | 114 MB | 114 MB | home screen, connected |
| Flutter main window, after 5 searches (up to 500 results, previews) | 1 | **132 MB** | **132 MB** | 20 s later: 132 / 132 MB |
| Flutter quick find bar, shown, 8 results | 1 | 132 MB | 121 MB | |
| Flutter quick find bar, hidden (Esc) | 1 | **8.6 MB** | 110 MB | hiding hands the working set back to Windows |
| Flutter main window with Impeller (Flutter's default) | 1 | 183 MB | 187 MB | after searches; not used, see below |
| Flutter, no engine, home screen only (floor) | 1 | 118 MB (Skia) / 172 MB (Impeller) | 117 / 176 MB | |

Where the Flutter window's memory goes (floor, Skia, `VirtualQueryEx`): 104 MB private, 205 MB image (DLLs, mostly
shared), 54 MB mapped. Most of the private part is the GPU driver: Intel's D3D11 driver and its shader compiler
(`igc64.dll`, an 83 MB image) load in-process because Flutter draws with ANGLE on Direct3D 11. Flutter itself is
`flutter_windows.dll` (20.5 MB) + the app's AOT code (5 MB). The WebView2 window pays the same driver cost in its
GPU process, on top of the browser.

**Result: the window drops from 465 MB in 7 processes to about 130 MB in one (−72 %).** That's still over the
ROADMAP target of ≤ 100 MB for the window. The rest is mostly the Intel driver; see "What would get it under 100 MB".

### Start and search

| What | 0.7.0 WebView2 | Flutter prototype | Target |
|---|---|---|---|
| UI process start to first frame | n/a (the window shows 1.8 s after the app starts, engine included) | **0.20 s** main, **0.13 s** bar (Impeller: 0.84-0.99 s) | ≤ 1.5 s cold start |
| Pipe + JSON round trip on top of the search | n/a (pywebview bridge) | **≤ 1 ms** (UI time − engine time; 4 ms for 500 results) | |
| Search keystroke to answer, engine side, 2,702 files (last 40 searches in the log) | not measured | median **2.8 ms**, 90th percentile 98 ms, max 122 ms; 6 of 40 over 80 ms, all short words that also match text inside files | ≤ 80 ms names, ≤ 250 ms meaning |

The engine log (`rpc search … ms (ranking … ms)`) and the UI timing file agree: the pipe adds under a millisecond;
the time is the ranking in `search.py`. Short words that hit text inside files (e.g. "tax": 95-121 ms) are over
the 80 ms names budget: that's Phase 1 engine work, not the UI.

### The engine (unchanged by the prototype, for reference)

| Engine | Processes | Working set | Private |
|---|---|---|---|
| `--engine`, idle after indexing, UI connected | 3 (venv launcher, console host, engine) | 132 MB | 567 MB |
| 0.7.0 app's engine process (same corpus) | 1 (+7 WebView2) | 147 MB | 583 MB |

The engine commits about 560 MB with nothing loaded: the Phase 1 "commit" problem (ROADMAP §2 cause 2), seen here
on a small index too. Running it headless doesn't change it.

### Impeller vs Skia (why the prototype uses Skia)

Same build, same runs, `NOBAD_FIND_RENDERER` switch: Impeller (Flutter 3.50's default on Windows) took 0.84-0.99 s
to the first frame and 183-188 MB; Skia 0.20 s and 132 MB. On this PC Impeller compiles more shaders at start through
the Intel compiler. Skia is still supported on Windows in 3.50, but Flutter is moving to Impeller: re-measure each
Flutter upgrade, and re-check on a PC with another GPU (AMD/NVIDIA) before the full move.

### What would get the window under 100 MB (not done in the prototype)
- Release GPU memory when the window is hidden or idle (Skia resource cache limits; `EmptyWorkingSet` already gives
  back the working set when the bar hides).
- Close the UI process when the window closes (planned: the engine starts it on the hotkey). Then "window closed"
  costs nothing for the UI, which matters more than the open-window number.
- One process for the main window and the bar (two engines and two driver copies today if both are open).
- Try Flutter's software renderer fallback for the bar only, and Impeller again on future Flutter versions.
