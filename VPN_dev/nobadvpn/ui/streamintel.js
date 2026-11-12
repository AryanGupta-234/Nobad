/* Streaming Region Intelligence (Streaming tab #t1). Self-contained: talks to /api/si_* and listens to si_* events.
   Everything shown comes from TMDB/JustWatch, Wikipedia/Wikidata or the engine's own measurements; when a source
   is missing or stale the UI says so instead of filling the gap. Connecting uses the existing /api/connect. */
(function () {
  "use strict";
  const tr = s => (window.NX && NX.t ? NX.t(s) : s);
  const E = s => esc(s == null ? "" : String(s));
  const img = (size, f) => f ? `/si/img/${size}/${encodeURIComponent(f)}` : "";
  const ago = ts => { if (!ts) return "—"; const s = Math.max(0, Math.round(Date.now() / 1000 - ts)); return s < 90 ? tr("just now") : s < 5400 ? Math.round(s / 60) + " min" : s < 172800 ? Math.round(s / 3600) + " h" : Math.round(s / 86400) + " d"; };
  const OFFERS = ["subscription", "free", "free with ads", "rent", "buy"];
  const SI = { status: null, results: [], q: "", busy: false, rep: null, restr: null, rec: null, pane: "match",
               filter: "all", provider: null, csearch: "", pending: null, verify: null, modal: null, err: null };

  /* ------------------------------------------------------------------ card in the Streaming tab */
  function buildCard() {
    const tab = $("#t1"); if (!tab || $("#siCard")) return;
    const c = document.createElement("div"); c.className = "card si-card"; c.id = "siCard";
    c.innerHTML = `<div class="si-head"><div><div class="h">${E(tr("Where to watch"))}</div>
        <div class="note">${E(tr("Find which countries list a movie, series or anime, on which platforms, and which of your servers match."))}</div></div>
        <button class="sm si-gear" data-si="setup" title="${E(tr("Data sources"))}" aria-label="${E(tr("Data sources"))}">⚙</button></div>
      <div class="ni-inline si-search"><input class="nx-in" id="siQ" type="search" placeholder="${E(tr("Movie, series or anime…"))}" autocomplete="off" spellcheck="false" aria-label="${E(tr("Search titles"))}">
        <button class="pri" data-si="search">${E(tr("Search"))}</button></div>
      <div id="siRes" aria-live="polite"></div>
      <div class="si-attr" id="siAttr"></div>`;
    tab.insertBefore(c, tab.firstChild);
    c.addEventListener("click", onClick);
    $("#siQ").addEventListener("keydown", e => { if (e.key === "Enter") search(); });
    renderCard();
  }
  const TMDB_SIGNUP = "https://www.themoviedb.org/signup", TMDB_API = "https://www.themoviedb.org/settings/api";
  function keyGuide() {
    const u = (url, label) => `<button class="linkish" data-si="link" data-url="${E(url)}">${E(label || url)}</button>`;
    return `<ol class="si-steps">
      <li>${E(tr("Create a free TMDB account"))}: ${u(TMDB_SIGNUP)} ${E(tr("(skip if you have one), then confirm your e-mail."))}</li>
      <li>${E(tr("Open the API page"))}: ${u(TMDB_API)} ${E(tr("(Settings → API)."))}</li>
      <li>${E(tr("Request an API key for personal, non-commercial use and accept TMDB's terms. For the app details you can enter: name 'NOBAD VPN (personal)', URL https://github.com/AryanGupta-234/Nobad, summary 'Personal use of Where to watch in NOBAD VPN'."))}</li>
      <li>${E(tr("Back on"))} ${u(TMDB_API)}, ${E(tr("copy the API Read Access Token (the long one starting with eyJ, recommended) or the shorter API Key."))}</li>
      <li>${E(tr("Paste it here and press Save & check. NOBAD verifies it with TMDB and stores it encrypted on this PC. Don't share it or put it in NOBAD's source code."))}</li></ol>`;
  }
  function attribution() {
    const st = SI.status || {};
    return `<span>${E(st.notice || "This product uses the TMDB API but is not endorsed or certified by TMDB.")}</span>
      <span>${E(st.watch_attribution || "Streaming availability data provided by JustWatch (via TMDB).")}</span>`;
  }
  function renderCard() {
    const box = $("#siRes"); if (!box) return;
    $("#siAttr").innerHTML = attribution();
    const st = SI.status;
    if (st && !st.configured) {
      box.innerHTML = `<div class="si-setup-cta"><b>${E(tr("One-time setup: add a free TMDB key"))}</b>
        <p>${E(tr("NOBAD reads titles and streaming catalogues from TMDB (availability data by JustWatch). TMDB's licence is personal, so each user adds their own free key. It takes about two minutes:"))}</p>
        ${keyGuide()}
        <button class="pri" data-si="setup">${E(tr("Add key"))}</button></div>`;
      return;
    }
    if (SI.busy) { box.innerHTML = `<div class="ni-busy" role="status"><i></i>${E(tr("Searching…"))}</div>`; return; }
    if (SI.err) { box.innerHTML = `<div class="net-issue warn"><b>${E(SI.err)}</b></div>`; return; }
    if (!SI.results.length) { box.innerHTML = SI.q ? `<div class="empty-state">${E(tr("No matching titles."))}</div>` : ""; return; }
    box.innerHTML = `<div class="si-results">` + SI.results.map(r => `<button class="si-hit" data-si="open" data-key="${E(r.key)}">
        ${r.poster ? `<img src="${img("w92", r.poster)}" alt="" loading="lazy">` : `<span class="si-noimg">${E((r.title || "?")[0])}</span>`}
        <span class="si-hit-t"><b>${E(r.title)}</b>${r.year ? ` <span class="si-y">${E(r.year)}</span>` : ""}
        <small>${E(tr(r.type.label))}${r.type.inferred ? "*" : ""}${r.original_title ? " · " + E(r.original_title) : ""}</small></span></button>`).join("") + `</div>
      ${SI.results.some(r => r.type.inferred) ? `<div class="note">* ${E(tr("Anime is inferred from Japanese-language animation."))}</div>` : ""}`;
  }
  function search() {
    const q = ($("#siQ") || {}).value || ""; SI.q = q.trim(); SI.err = null;
    if (SI.q.length < 2) return;
    SI.busy = true; renderCard();
    api("si_search", { q: SI.q }).then(r => {
      SI.busy = false;
      if (!r.ok) { SI.err = r.error; if (r.code === "no-key") loadStatus(); SI.results = []; }
      else SI.results = r.results || [];
      renderCard();
    });
  }

  /* ------------------------------------------------------------------ title modal */
  function openTitle(key, force) {
    SI.rep = null; SI.restr = null; SI.rec = null; SI.verify = null; SI.pane = SI.pane || "match"; SI.filter = "all"; SI.provider = null; SI.csearch = "";
    const hit = SI.results.find(r => r.key === key) || {};
    if (!SI.modal) {
      SI.modal = NX.modal({ wide: true, title: hit.title || tr("Title"), html: `<div id="siM"></div>`,
        actions: [{ label: tr("Close"), fn: m => m.close() }], onClose: () => { SI.modal = null; } });
      SI.modal.box.classList.add("si-modal");
      SI.modal.body.addEventListener("click", onClick);
      SI.modal.body.addEventListener("input", e => { if (e.target.id === "siCq") { SI.csearch = e.target.value; renderPane(true); } });
    }
    SI.loading = key;
    $("#siM").innerHTML = `<div class="ni-busy" role="status"><i></i>${E(tr("Reading catalogues and your servers…"))}</div>`;
    api("si_title", { key, force: !!force }).then(r => { if (!r.ok) $("#siM").innerHTML = `<div class="net-issue warn"><b>${E(r.error)}</b></div>`; });
  }
  const PANES = [["match", "Best match"], ["countries", "Countries"], ["platforms", "Platforms"], ["restrictions", "Restrictions"], ["sources", "Sources"]];
  function renderModal() {
    const R = SI.rep; if (!R || !SI.modal) return;
    const t = R.title;
    SI.modal.box.querySelector("h2").textContent = t.title + (t.year ? ` (${t.year})` : "");
    const meta = [tr(t.type.label) + (t.type.inferred ? "*" : ""), t.genres.slice(0, 3).join(", "),
                  t.seasons ? `${t.seasons} ${tr(t.seasons === 1 ? "season" : "seasons")}` : (t.runtime ? `${t.runtime} min` : ""), t.status].filter(Boolean);
    $("#siM").innerHTML = `<div class="si-top">${t.poster ? `<img class="si-poster" src="${img("w185", t.poster)}" alt="">` : ""}
        <div class="si-top-t">${t.original_title ? `<div class="note">${E(tr("Original title"))}: ${E(t.original_title)}</div>` : ""}
        <div class="si-chips">${meta.map(m => `<span class="ni-tag">${E(m)}</span>`).join("")}</div>
        <p class="si-ov">${E(t.overview || tr("No description on TMDB."))}</p>
        ${t.alternative_titles.length ? `<details class="si-alt"><summary>${E(tr("Also known as"))} (${t.alternative_titles.length})</summary>${t.alternative_titles.slice(0, 30).map(a => `<span class="ni-tag" title="${E(a.country || "")}">${E(a.title)}${a.country ? ` · ${E(a.country)}` : ""}</span>`).join(" ")}</details>` : ""}
        <div class="si-links"><button class="sm" data-si="link" data-url="${E(t.tmdb_url)}">TMDB</button>${t.ids.imdb ? `<button class="sm" data-si="link" data-url="https://www.imdb.com/title/${E(t.ids.imdb)}/">IMDb</button>` : ""}</div></div></div>
      <div class="ni-seg si-seg" role="tablist">${PANES.map(([k, n]) => `<button role="tab" data-si="pane" data-p="${k}" class="${k === SI.pane ? "a" : ""}" aria-selected="${k === SI.pane}">${E(tr(n))}${k === "restrictions" ? restrBadge() : ""}</button>`).join("")}</div>
      <div id="siPane"></div>`;
    renderPane();
  }
  function restrBadge() {
    const d = SI.restr; if (!d) return ` <span class="si-dot si-dot-wait" title="${E(tr("Loading"))}"></span>`;
    return d.status === "ok" && d.records.length ? ` <span class="si-count">${d.records.length}</span>` : "";
  }
  function renderPane(keepFocus) {
    const p = $("#siPane"); if (!p) return;
    const fn = { match: paneMatch, countries: paneCountries, platforms: panePlatforms, restrictions: paneRestrictions, sources: paneSources }[SI.pane];
    const focus = keepFocus && document.activeElement && document.activeElement.id;
    p.innerHTML = fn();
    if (focus) { const el = document.getElementById(focus); if (el) { el.focus(); const v = el.value; el.value = ""; el.value = v; } }
  }
  const offerChip = t => `<span class="si-offer si-o-${E(t.replace(/\s+/g, "-"))}">${E(tr(t))}</span>`;
  const prov = id => (SI.rep.availability.providers.find(p => p.id === id) || { name: "#" + id });
  const logo = (p, size) => p.logo ? `<img class="si-logo" src="${img(size || "w92", p.logo)}" alt="" title="${E(p.name)}" loading="lazy">` : `<span class="si-logo si-logo-x" title="${E(p.name)}">${E((p.name || "?")[0])}</span>`;

  function paneMatch() {
    const R = SI.rep, rec = SI.rec || R.recommendation, av = R.availability;
    let h = "";
    if (rec.home) h += rec.home.listed
      ? `<div class="net-issue good"><b>${E(tr("Listed where you are"))} (${E(rec.home.code)}) · ${E(tr(rec.home.best))}</b><p>${E(tr("You may not need a VPN for this one. See Countries for the platforms."))}</p></div>`
      : `<div class="net-issue info"><b>${E(tr("Not listed in your country"))} (${E(rec.home.code)})</b><p>${E(tr("Based on the availability source; catalogues change often."))}</p></div>`;
    if (rec.verdict === "not-listed-anywhere") h += `<div class="net-issue warn"><b>${E(tr("No streaming listing found in any covered country"))}</b><p>${E(tr("It may be in cinemas, unreleased, or simply not in the source's data yet. That isn't the same as unavailable everywhere."))}</p></div>`;
    else if (rec.verdict === "no-matching-server") h += `<div class="net-issue warn"><b>${E(tr("Listed in"))} ${av.listed.length} ${E(tr("countries, but none of your servers are in them"))}</b><p>${E(tr("Add a config for one of the countries below, or check servers whose country is unknown."))}</p></div>`;
    if (!SI.restr) h += `<div class="note si-wait"><span class="si-dot si-dot-wait"></span>${E(tr("Checking documented restrictions…"))}</div>`;
    h += (rec.options || []).map((o, i) => `<div class="si-opt${i === 0 && !o.restricted ? " si-best" : ""}${o.restricted ? " si-restricted" : ""}">
        <div class="si-opt-h"><span class="si-cc">${E(o.code)}</span><div><b>${E(o.name)}</b><small>${E(tr("via"))} ${E(o.server)}${o.other_servers.length ? ` +${o.other_servers.length}` : ""}</small></div>
          ${offerChip(o.offer)}<span class="si-score" title="${E(tr("Match score"))}"><i style="width:${o.score}%"></i><em>${o.score}</em></span></div>
        <ul class="si-why">${o.reasons.map(x => `<li class="si-ok">${E(x)}</li>`).join("")}${o.caveats.map(x => `<li class="si-warn">${E(x)}</li>`).join("")}</ul>
        <div class="si-opt-a">${o.restricted ? "" : `<button class="${i === 0 ? "pri" : "sm"}" data-si="connect" data-server="${E(o.server)}" data-cc="${E(o.code)}" data-svc="${E(o.verify_services.join(","))}">${E(tr("Connect to"))} ${E(o.server)}</button>`}</div>
        ${verifyBox(o)}</div>`).join("");
    if ((rec.listed_without_server || []).length) h += `<div class="ni-sub">${E(tr("Also listed where you have no server"))}</div><div class="si-ccs">${rec.listed_without_server.slice(0, 60).map(c => `<span class="si-cc" title="${E(c.name)} · ${E(tr(c.best))}">${E(c.code)}</span>`).join("")}</div>`;
    if ((rec.servers_unknown || []).length) h += `<div class="note">${E(tr("Servers with an unknown country (not matched)"))}: ${E(rec.servers_unknown.join(", "))}. ${E(tr("Turn on IP lookup in Settings → Privacy to locate them."))}</div>`;
    return h + `<div class="note si-disc">${E(tr(rec.disclaimer))}</div>`;
  }
  function verifyBox(o) {
    const v = SI.verify;
    if (SI.pending && SI.pending.server === o.server) return `<div class="ni-busy" role="status"><i></i>${E(tr(SI.pending.stage === "verify" ? "Checking the exit and platforms…" : "Connecting…"))}</div>`;
    if (!v || v.server !== o.server) return "";
    const cm = v.country_match === true ? `<li class="si-ok">${E(tr("Exit address is in"))} ${E(v.exit_country)}</li>`
      : v.country_match === false ? `<li class="si-warn">${E(tr("Exit address is in"))} ${E(v.exit_country)}, ${E(tr("not"))} ${E(v.country)}</li>`
      : `<li class="si-warn">${E(v.exit_lookup === "disabled" ? tr("Exit country not checked: IP lookup is off") : tr("Exit country couldn't be checked"))}</li>`;
    const sv = (v.services || []).map(s => `<li class="${s.level === "ok" ? "si-ok" : "si-warn"}">${E(s.name)}: ${E(tr(s.note))}</li>`).join("");
    return `<ul class="si-why si-verify">${cm}${sv}</ul><div class="note">${E(tr("Reachable means the site answered from this exit. It doesn't guarantee a particular title will play."))}</div>`;
  }
  function paneCountries() {
    const av = SI.rep.availability, mine = new Set((SI.rep.servers || []).filter(s => s.country).map(s => s.country));
    const q = SI.csearch.trim().toLowerCase();
    const rows = av.listed.filter(c => (SI.filter === "all" || c.offers[SI.filter]) && (!SI.provider || Object.values(c.offers).some(l => l.includes(SI.provider))) &&
      (!q || (c.name || "").toLowerCase().includes(q) || c.code.toLowerCase() === q));
    const counts = Object.fromEntries(OFFERS.map(t => [t, av.listed.filter(c => c.offers[t]).length]));
    let h = `<div class="si-filters"><div class="si-fchips">${["all"].concat(OFFERS.filter(t => counts[t])).map(t => `<button class="si-f${SI.filter === t ? " a" : ""}" data-si="filter" data-f="${E(t)}">${E(tr(t === "all" ? "All" : t))}${t === "all" ? ` ${av.listed.length}` : ` ${counts[t]}`}</button>`).join("")}</div>
      <input class="nx-in" id="siCq" type="search" placeholder="${E(tr("Find a country"))}" value="${E(SI.csearch)}" aria-label="${E(tr("Find a country"))}"></div>
      ${SI.provider ? `<div class="note">${E(tr("Only"))} <b>${E(prov(SI.provider).name)}</b> · <button class="linkish" data-si="provider" data-id="">${E(tr("show all platforms"))}</button></div>` : ""}`;
    h += rows.length ? `<div class="si-table">` + rows.map(c => `<div class="si-row"><span class="si-cc">${E(c.code)}</span><div class="si-row-n"><b>${E(c.name)}</b>${mine.has(c.code) ? `<span class="si-yours">${E(tr("your server"))}</span>` : ""}</div>
        <div class="si-row-o">${OFFERS.filter(t => c.offers[t]).map(t => `<div class="si-ot">${offerChip(t)}<span class="si-logos">${c.offers[t].map(id => logo(prov(id))).join("")}</span></div>`).join("")}</div>
        ${c.link ? `<button class="sm" data-si="link" data-url="${E(c.link)}" title="${E(tr("Watch options on TMDB (JustWatch data)"))}">↗</button>` : "<span></span>"}</div>`).join("") + `</div>`
      : `<div class="empty-state">${E(tr("No listed countries match."))}</div>`;
    if (av.not_listed.length) h += `<details class="si-nl"><summary>${E(tr("Not listed in"))} ${av.not_listed.length} ${E(tr("covered countries"))}</summary><div class="si-ccs">${av.not_listed.map(c => `<span class="si-cc si-cc-off" title="${E(c.name)}">${E(c.code)}</span>`).join("")}</div></details>`;
    return h + `<div class="note">${E(tr(av.coverage_known ? av.unknown_note : "The list of countries the source covers couldn't be loaded, so unlisted countries are shown as unknown."))} ${E(tr("Coverage"))}: ${av.coverage} ${E(tr("countries"))}.</div>`;
  }
  function panePlatforms() {
    const av = SI.rep.availability;
    if (!av.providers.length) return `<div class="empty-state">${E(tr("No platforms list this title in any covered country."))}</div>`;
    return `<div class="si-plats">` + av.providers.map(p => {
      const types = [...new Set(Object.values(p.countries).flat())];
      return `<button class="si-plat" data-si="provider" data-id="${p.id}">${logo(p, "w92")}<span><b>${E(p.name)}</b><small>${Object.keys(p.countries).length} ${E(tr("countries"))} · ${types.map(t => E(tr(t))).join(", ")}</small></span></button>`;
    }).join("") + `</div><div class="note">${E(tr("Select a platform to see its countries."))}</div>`;
  }
  function paneRestrictions() {
    const d = SI.restr, certs = SI.rep.certifications || [];
    let h = `<div class="note">${E(tr("Documented legal or censorship restrictions are kept separate from streaming licensing. A title missing from a catalogue is not a ban."))}</div>`;
    if (!d) h += `<div class="ni-busy" role="status"><i></i>${E(tr("Loading restriction records…"))}</div>`;
    else if (d.status !== "ok") h += `<div class="net-issue ${d.status === "unavailable" ? "warn" : "info"}"><b>${E(tr(d.status === "unavailable" ? "Restriction records unavailable" : "No matchable restriction records"))}</b><p>${E(tr(d.note || ""))}</p></div>`;
    else if (!d.records.length) h += `<div class="net-issue good"><b>${E(tr("No documented bans or blocks found"))}</b><p>${E(tr("Checked Wikipedia's banned-film lists for this exact title. Absence from these lists doesn't prove there were no restrictions."))}</p></div>`;
    else h += d.records.map(r => `<div class="si-restr"><div class="si-restr-h"><span class="si-cc">${E(r.code || "—")}</span><b>${E(r.country_name || r.country || tr("Unknown country"))}</b><span class="si-y">${E(r.date || tr("date not given"))}</span></div>
        <p>${E(r.notes || tr("No details in the list."))}</p>
        ${r.tags.length ? `<div class="si-chips">${r.tags.map(x => `<span class="ni-tag">${E(tr(x))}</span>`).join("")}<span class="note">${E(tr("from the notes"))}</span></div>` : ""}
        <div class="si-src"><span class="si-ver">${E(tr(r.verification))}</span>${(r.sources || []).map(s => s.url ? `<button class="linkish" data-si="link" data-url="${E(s.url)}">${E(s.title || s.publisher || hostOf(s.url))}</button>` : `<span>${E(s.title || s.text || "")}</span>`).join(" · ")}
        · <button class="linkish" data-si="link" data-url="${E(r.url)}">${E(tr("Wikipedia section"))}</button></div></div>`).join("");
    if (certs.length) h += `<div class="ni-sub">${E(tr("Age ratings"))} <span class="note">${E(tr("TMDB, from national rating boards"))}</span></div><div class="si-certs">${certs.map(c => `<span class="si-cert" title="${E(c.name || c.country)}"><b>${E(c.country)}</b> ${E(c.rating)}</span>`).join("")}</div>`;
    return h + `<div class="note si-disc">${E(tr("Connecting to another region doesn't change which laws apply to you, and NOBAD doesn't help bypass legal restrictions."))}</div>`;
  }
  const hostOf = u => { try { return new URL(u).hostname; } catch (_) { return u; } };
  function paneSources() {
    const R = SI.rep, av = R.availability, d = SI.restr, st = SI.status || {};
    const row = (k, v) => `<div class="kvr"><span>${E(tr(k))}</span><b>${v}</b></div>`;
    return row("Titles and metadata", "TMDB") +
      row("Streaming availability", `JustWatch via TMDB · ${E(ago(av.fetched))} ${E(tr("ago"))} ${av.fresh ? `<span class="ni-ok">${E(tr("fresh"))}</span>` : `<span class="ni-bad">${E(tr("stale"))}</span>`}`) +
      row("Restrictions", d ? (d.status === "ok" ? `Wikipedia (${d.pages} ${E(tr("lists"))}) · ${E(tr("index"))} ${E(ago(d.index_built))} ${E(tr("ago"))}` : E(tr(d.status))) : E(tr("loading")) ) +
      row("Identity", `TMDB ${E(R.title.ids.tmdb)}${R.title.ids.imdb ? " · IMDb " + E(R.title.ids.imdb) : ""}${R.title.ids.wikidata ? " · Wikidata " + E(R.title.ids.wikidata) : ""}`) +
      row("Your servers", `${R.servers.length} (${R.servers.filter(s => s.country_basis === "ip-geolocation").length} ${E(tr("located by IP"))}, ${R.servers.filter(s => s.country_basis === "name").length} ${E(tr("by name"))})`) +
      `<div class="si-actions"><button class="sm" data-si="refresh">${E(tr("Refresh now"))}</button></div>
       <div class="si-attr">${attribution()}<span>${E(st.restrictions_license || "")}</span></div>`;
  }

  /* ------------------------------------------------------------------ setup (key, my services, cache) */
  function setup() {
    const st = SI.status || {};
    const m = NX.modal({ title: tr("Streaming data sources"), sub: tr("NOBAD uses TMDB for titles and JustWatch data (through TMDB) for availability. Restrictions come from Wikipedia's banned-film lists."),
      html: `<div class="nx-field"><b>${E(tr("TMDB key"))}</b>
          <div class="note">${st.configured ? `${E(tr("Saved"))}: <code>${E(st.key_hint)}</code>${st.key_source === "environment" ? " (" + E(tr("from environment")) + ")" : ""}` : E(tr("Not set"))}. ${E(tr("It is stored encrypted on this PC and only sent to TMDB."))}</div>
          <details class="si-howto" ${st.configured ? "" : "open"}><summary>${E(tr("How to get a free key"))}</summary>${keyGuide()}</details>
          <div class="ni-inline"><input class="nx-in" id="siKey" type="password" placeholder="${E(tr("Paste API key or Read Access Token"))}" autocomplete="off" spellcheck="false"><button class="pri" data-k="save">${E(tr("Save & check"))}</button></div>
          <div class="si-actions"><button class="sm" data-k="signup">${E(tr("Open TMDB API page"))}</button>${st.configured && st.key_source !== "environment" ? `<button class="sm" data-k="remove">${E(tr("Remove key"))}</button>` : ""}</div><div id="siKeyMsg" class="note"></div></div>
        <div class="nx-field"><b>${E(tr("Services you have"))}</b><div class="note">${E(tr("Optional. Recommendations prefer countries where a service you have carries the title."))}</div>
          <div class="ni-inline"><input class="nx-in" id="siReg" maxlength="2" placeholder="${E(tr("Country code, e.g. IN"))}" value="${E((S.home && S.home.country) || "")}"><button class="sm" data-k="load">${E(tr("Load services"))}</button></div><div id="siSvc" class="si-svcs"></div></div>
        <div class="nx-field"><b>${E(tr("Cache"))}</b><div class="note">${(st.cache && st.cache.entries) || 0} ${E(tr("entries. Availability is refreshed after 12 hours; nothing from TMDB is kept longer than 6 months."))}</div><button class="sm" data-k="clear">${E(tr("Clear cache"))}</button></div>
        <div class="si-attr">${attribution()}</div>`,
      actions: [{ label: tr("Done"), fn: x => x.close() }] });
    const msg = t => { m.body.querySelector("#siKeyMsg").textContent = t; };
    m.body.addEventListener("click", e => {
      const b = e.target.closest("[data-k]"); if (!b) return;
      const k = b.dataset.k;
      if (k === "save") { b.disabled = true; msg(tr("Checking with TMDB…"));
        api("si_key", { key: m.body.querySelector("#siKey").value }).then(r => { b.disabled = false; msg(r.ok ? tr("Saved. You can search now.") : r.error); if (r.ok) { m.body.querySelector("#siKey").value = ""; loadStatus(); } }); }
      else if (k === "remove") { if (confirm(tr("Remove the saved TMDB key?"))) api("si_key_clear", {}).then(() => { loadStatus(); m.close(); }); }
      else if (k === "signup") api("si_open", { url: TMDB_API });
      else if (k === "clear") api("si_cache_clear", {}).then(() => { toast(tr("Cache cleared"), true); loadStatus(); });
      else if (k === "load") loadServices(m);
    });
    m.body.addEventListener("click", e => { const l = e.target.closest('[data-si="link"]'); if (l) openLink(l.dataset.url); });
    m.body.addEventListener("change", e => { if (e.target.matches("[data-svc]")) saveServices(m); });
    if (st.configured) loadServices(m);
  }
  function loadServices(m) {
    const box = m.body.querySelector("#siSvc"), reg = (m.body.querySelector("#siReg").value || "").trim().toUpperCase();
    box.innerHTML = `<div class="ni-busy"><i></i>${E(tr("Loading…"))}</div>`;
    api("si_providers", { region: reg }).then(r => {
      if (!r.ok) { box.innerHTML = `<div class="note">${E(r.error)}</div>`; return; }
      const mine = new Set((SI.status && SI.status.my_services) || []);
      const top = r.providers.slice(0, 120);
      box.innerHTML = top.map(p => `<label class="si-svc"><input type="checkbox" data-svc="${p.id}" ${mine.has(p.id) ? "checked" : ""}>${logo(p)}<span>${E(p.name)}</span></label>`).join("") || `<div class="note">${E(tr("No services found for that country."))}</div>`;
    });
  }
  function saveServices(m) {
    const ids = [...m.body.querySelectorAll("[data-svc]:checked")].map(x => +x.dataset.svc);
    const keep = new Set(((SI.status && SI.status.my_services) || []).filter(id => !m.body.querySelector(`[data-svc="${id}"]`)));
    ids.forEach(i => keep.add(i));
    api("si_prefs", { my_services: [...keep] }).then(r => { if (r.ok && SI.status) SI.status.my_services = [...keep]; });
  }
  function loadStatus() { api("si_status", {}).then(r => { if (r.ok) { SI.status = r; renderCard(); } }); }

  /* ------------------------------------------------------------------ actions */
  function onClick(e) {
    const b = e.target.closest("[data-si]"); if (!b) return;
    const a = b.dataset.si;
    if (a === "search") search();
    else if (a === "setup") setup();
    else if (a === "open") openTitle(b.dataset.key);
    else if (a === "pane") { SI.pane = b.dataset.p; $$("#siM .si-seg [data-p]").forEach(x => { x.classList.toggle("a", x === b); x.setAttribute("aria-selected", x === b); }); renderPane(); }
    else if (a === "filter") { SI.filter = b.dataset.f; renderPane(); }
    else if (a === "provider") { SI.provider = b.dataset.id ? +b.dataset.id : null; SI.pane = "countries"; renderModal(); }
    else if (a === "refresh") openTitle(SI.rep.key, true);
    else if (a === "link") openLink(b.dataset.url);
    else if (a === "connect") connect(b.dataset.server, b.dataset.cc, (b.dataset.svc || "").split(",").filter(Boolean));
  }
  function openLink(url) {
    api("si_open", { url }).then(r => {
      if (!r.ok && r.error === "confirm" && confirm(tr("Open this link in your browser?") + "\n" + r.host)) api("si_open", { url, confirm: true });
      else if (!r.ok && r.error !== "confirm") toast(r.error);
    });
  }
  function connect(server, cc, services) {
    if (S.connected && S.active === server) { SI.pending = { server, cc, services, stage: "verify" }; renderPane(); api("si_verify", { country: cc, services }); return; }
    SI.pending = { server, cc, services, stage: "connect" }; SI.verify = null; renderPane();
    api("connect", { name: server }).then(r => { if (!r.ok) { SI.pending = null; renderPane(); toast(r.error || tr("Could not connect")); } });
  }
  function onState(st) {
    const p = SI.pending; if (!p || p.stage !== "connect") return;
    if (st.connected && st.active === p.server) { p.stage = "verify"; if (SI.modal) renderPane(); api("si_verify", { country: p.cc, services: p.services }); }
    else if (!st.connecting && st.error && st.error.name === p.server) { SI.pending = null; if (SI.modal) renderPane(); }
  }

  /* ------------------------------------------------------------------ events */
  function handle(type, p) {
    switch (type) {
      case "si_title":
        if (!SI.modal || p.key !== SI.loading) return true;
        if (!p.ok) { $("#siM").innerHTML = `<div class="net-issue warn"><b>${E(p.error)}</b></div>`; return true; }
        SI.rep = p; SI.rec = null; renderModal(); return true;
      case "si_restrictions":
        if (!SI.rep || p.key !== SI.rep.key) return true;
        SI.restr = p.restrictions; SI.rec = p.recommendation; renderModal(); return true;
      case "si_verify":
        SI.verify = p; SI.pending = null; if (SI.modal && SI.rep) renderPane(); return true;
      default: return false;
    }
  }
  function init() {
    buildCard(); loadStatus();
    const prev = NX.handle; NX.handle = (t, p) => handle(t, p) || prev(t, p);
    const prevState = NX.onState; NX.onState = st => { prevState(st); onState(st); };
  }
  if (window.NX) init(); else addEventListener("load", init);
})();
