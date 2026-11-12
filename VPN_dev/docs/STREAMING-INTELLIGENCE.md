# Streaming Region Intelligence

*Where to watch* in the **Streaming** tab answers one question: *I want to watch this title. Where is it listed,
on which platforms and offer types, are there documented restrictions, and which of my own VPN servers matches
those catalogues?*

It is a separate feature inside the VPN app (`nobadvpn/streamintel/`, `ui/streamintel.js`). It only **reads** the
engine's state and connects through the existing `/api/connect`. The tunnel engine is unchanged.

## What the user sees

1. **Search** for a movie, series, anime, animated or documentary title. A year (`Dune 2021`) or an IMDb id/URL
   (`tt0245429`) narrows it down. Results come back de-duplicated by TMDB identity, with year, type, original title and
   poster.
2. A **title view** with metadata (original and alternative titles, genres, seasons, status) and five panes:
   * **Best match**: the recommendation, ranked. Every option shows its reasons (✓) and caveats (!) and a
     *Connect* button. It also shows whether the title is listed in your own country (no VPN needed), countries where
     it's listed but you have no server, and servers whose country is unknown.
   * **Countries**: every listing country with its offer types (subscription, free, free with ads, rent, buy) and
     platform logos. You can filter by offer type, platform or country name. Countries where the title is *not
     listed* are shown separately, and countries the source doesn't cover are labelled *unknown*.
   * **Platforms**: every platform that lists the title, with its countries and offer types.
   * **Restrictions**: documented bans, blocks and refusals, kept separate from age ratings and from licensing gaps.
   * **Sources**: where every piece came from, when it was fetched, and whether it is fresh. There is also a
     *Refresh now* button.
3. After connecting from a recommendation, NOBAD **verifies** two things: that the exit IP really is in that country
   (existing exit-IP lookup), and that the platforms it can check (Netflix, Prime Video, Disney+) answer normally
   (existing reachability checks).

## Data sources and why

| Need | Source | Access | Notes |
|---|---|---|---|
| Titles, alternative titles, ids, posters, age ratings | **TMDB** API v3 | the **user's own free key** (v3 API key or v4 Read Access Token) | TMDB's licence is non-transferable, so a shared key can't ship inside an open-source app. |
| Country-by-country streaming availability | **JustWatch data via TMDB** (`/watch/providers`) | same TMDB key | Covers subscription (`flatrate`), `free`, `ads`, `rent` and `buy` per country. Attribution to JustWatch is required and shown. |
| Countries the availability source covers | TMDB `/watch/providers/regions` | same key | Makes it possible to tell *not listed* apart from *unknown*. |
| Documented bans and blocks | **Wikipedia** "List of banned films" and the per-country lists it links | MediaWiki API, no key | A secondary source with citations, CC BY-SA. Parsed from wikitext through the official API, not by scraping HTML. |
| Identity link for restrictions | **Wikidata** (`wbgetentities`, enwiki sitelink) + Wikipedia redirects | no key | TMDB's `wikidata_id` is matched to the exact article, so a title is never matched by guessing. |
| Your VPN servers | the running engine | local | Config names, endpoint geolocation (if *IP lookup* is on), measured latency, and what NOBAD saw services do through each server. |

**Not used:** scraping JustWatch, Netflix or other sites, unofficial APIs, and hard-coded availability lists.
When a source is unavailable, the feature says so. It never fills the gap with made-up data.

Other providers (Watchmode, Streaming Availability API, Reelgood) were considered. They need commercial keys or
paid plans. The code has a clear source boundary (`tmdb.py`, `restrictions.py`), so another source can be added next to
TMDB later without changing the UI.

## Honesty rules (enforced in code and tests)

* **Listed ≠ confirmed.** A listing means "the source reports an offer there as of the fetch time". Catalogues change
  daily, and a listing doesn't guarantee playback.
* **Not listed ≠ unavailable everywhere.** It only applies to countries the source covers. Uncovered countries are *unknown*.
* **Licensing gap ≠ restriction.** A title missing from a catalogue is never shown as a ban.
* **Restrictions are labelled by source quality.** Each record says *documented, secondary source with N citations*
  (or *without a citation*). It includes the date, the notes, the citations and a link to the exact Wikipedia section.
  Tags like *later lifted*, *cuts or edited release*, *certification refused* or *temporary* are labelled "from the notes"
  (keyword evidence), never presented as an official decision.
* **No identity, no restriction match.** A title without a Wikidata link or an English Wikipedia article gets
  *no matchable records*, which is not shown as *no restrictions*. When Wikipedia is down, the status is *unavailable*.
* **A country is only recommended when** it lists the title, the user has a server whose country is known there, and no
  documented (unlifted) restriction exists for the title there.
* **Server load** isn't in WireGuard configs, so it is shown as *not reported* instead of being guessed.
* **No bypass promises.** The UI says that services may detect VPNs, and that a VPN doesn't change which local laws apply.

## How a recommendation is scored (0–100)

| Factor | Effect |
|---|---|
| Best offer type in that country | subscription 45, free 43, free with ads 41, rent 25, buy 20 |
| "Services you have" (optional) | +12 if one of them carries it there, −15 if none does |
| Latency of your best server there | +20 (<60 ms) … +2 (≥300 ms), +6 when not measured yet, −30 if it didn't answer |
| Server country evidence | +6 when located by IP, −8 when only estimated from the config name |
| What NOBAD saw the platform do through that server | +5 answered normally, −12 recently blocked or VPN-detected |
| Availability data older than 12 h | −10 |
| Documented restriction for this title there | −40, and the option can't be connected from the view |

## Freshness and caching

SQLite cache in `ProgramData\NobadVPN\streamintel\cache.sqlite`, plus posters and logos in `streamintel\img\`.

| Data | Fresh for |
|---|---|
| Availability (title report) | 12 h |
| Search results | 1 day |
| Covered regions, provider lists | 7 days |
| Country list | 30 days |
| Wikipedia restriction index, Wikidata links | 7 days |

When a source fails, a cached answer is used only if one exists, and it is marked **stale** with its fetch time.
TMDB's terms forbid keeping TMDB content longer than **six months**: `purge()` enforces that on every start, and
images are re-fetched after six months. *Settings (⚙) → Clear cache* empties everything.

## Getting a TMDB key (about two minutes)

1. Create a free TMDB account at <https://www.themoviedb.org/signup> and confirm your e-mail.
2. Open <https://www.themoviedb.org/settings/api> (Settings → API).
3. Request an API key for **personal, non-commercial use** and accept TMDB's terms. For the app details you can
   enter: name *NOBAD VPN (personal)*, URL *https://github.com/AryanGupta-234/Nobad*, summary *Personal use of
   Where to watch in NOBAD VPN*.
4. Back on <https://www.themoviedb.org/settings/api>, copy the **API Read Access Token** (the long one starting with
   `eyJ`, recommended) or the shorter **API Key**.
5. In NOBAD: **Streaming → Where to watch → Add key** (or the ⚙ button), paste it and press **Save & check**.
   NOBAD verifies it with TMDB and stores it encrypted on this PC.

Keep the key to yourself: don't share it or put it into NOBAD's source code. A personal key covers your own use
of a free app; if NOBAD were ever sold or ad-supported, TMDB requires a commercial agreement.

## Configuration

* **TMDB key.** Use the ⚙ button on the *Where to watch* card, or the setup prompt. Get a free key at
  themoviedb.org → Settings → API. NOBAD checks the key with TMDB before saving it. It is stored **DPAPI-encrypted** in
  `ProgramData\NobadVPN\streamintel\tmdb.credential`. It's never stored in `settings.json`, because settings are
  pushed to the UI and included in diagnostics. `NOBAD_TMDB_TOKEN` overrides it for development and CI.
* **Services you have** (optional): pick them per country. They're stored as TMDB provider ids in `si_my_services`.
* **IP lookup** (Settings → Privacy) lets NOBAD locate servers by their endpoint IP. Without it, servers are only
  matched when their config name names a country (`usa`, `japan`, `de-fra`), and they are labelled *estimated*.

## Architecture

```
ui/streamintel.js  ── /api/si_* ──>  streamintel/api_handlers.py   (input validation, worker threads, events)
                                       └── service.py               (orchestration, cache, stale fallback)
                                            ├── tmdb.py             (TMDB client, search ranking, normalisation)
                                            ├── availability.py     (listed / not listed / unknown, offer types)
                                            ├── restrictions.py     (Wikipedia lists -> records, Wikidata identity)
                                            ├── countries.py        (ISO codes, names from TMDB + aliases)
                                            ├── servers.py          (read-only view of the engine's servers)
                                            ├── recommend.py        (scoring with reasons and caveats)
                                            ├── store.py            (SQLite cache, 6-month purge, DPAPI credential)
                                            └── net.py              (HTTPS client, retry/backoff, typed errors)
server.py  GET /si/img/<size>/<file>   validating, caching poster proxy (the UI's CSP stays img-src 'self')
```

* **Events:** `si_title` (metadata, availability and recommendation) comes first. `si_restrictions` follows once the
  restriction lookup finishes; the first index build reads about a dozen Wikipedia pages and takes roughly 10–15 s,
  then it is cached for a week. `si_verify` reports the post-connect check.
* **Security:** the TMDB key never reaches the UI (only a masked hint). Poster and logo file names are validated
  against a strict pattern, and the bytes must really be an image. Links from the data open through `si_open`, which only
  allows http(s) without credentials and asks before opening hosts outside a short allowlist.

## Attribution (required, shown in the UI)

* "This product uses the TMDB API but is not endorsed or certified by TMDB."
* "Streaming availability data provided by JustWatch (via TMDB)."
* Wikipedia content is CC BY-SA 4.0; every restriction record links to its source section.

TMDB treats some uses as commercial: for example, charging for an app that uses TMDB data, or using it to drive
traffic or ad revenue. Those need a separate agreement with TMDB. NOBAD VPN is free and open source; if that ever
changes, review TMDB's terms first.

## Networks that filter TMDB

Some ISPs (seen on Indian networks) reset TLS connections whose server name is `themoviedb.org`, while TMDB's
alternative API name `api.tmdb.org`, on the same servers, works. On the development PC, 11 of 20 connections to
`api.themoviedb.org` were reset, against 0 of 20 to `api.tmdb.org`. NOBAD therefore calls `api.tmdb.org` first,
falls back to `api.themoviedb.org` on a network error (never on an auth or rate-limit error), and remembers the name
that worked. Every request also gets up to two retries with backoff.

## Limits

* Availability depends on TMDB and JustWatch coverage. Some regional services or countries may be missing; those show
  as *unknown*, never as *unavailable*.
* Wikipedia's lists mostly cover films, so TV restrictions are rarely documented there. The lists also include some
  "virtual bans" by non-government groups; the notes and citations say which is which.
* Server load isn't available from WireGuard configs.
* Playback can still fail: services detect VPNs, and catalogues change between fetches.
