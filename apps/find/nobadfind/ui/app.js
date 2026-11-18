// NOBAD Find UI. Every value from the index (file names, folders, snippets) is untrusted: it goes through esc()
// before it reaches innerHTML. Snippet match markers (\x02 \x03) become <mark> only after escaping.
"use strict";
const $ = s => document.querySelector(s);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const marks = v => esc(v).replace(/\x02/g, "<mark>").replace(/\x03/g, "</mark>");
const api = async (name, ...args) => {
  if (!window.pywebview || !pywebview.api || !pywebview.api[name]) return null;
  try { return await pywebview.api[name](...args); } catch (e) { console.warn(name, e); return null; }
};

const KIND = { pdf: "PDF", document: "DOC", spreadsheet: "XLS", slides: "PPT", text: "TXT", code: "</>", email: "MAIL",
  image: "IMG", video: "VID", audio: "AUD", archive: "ZIP", app: "APP", ebook: "BOOK", folder: "DIR", other: "FILE" };
const size = n => !n ? "" : n < 1024 ? n + " B" : n < 1 << 20 ? (n / 1024).toFixed(0) + " KB" :
  n < 1 << 30 ? (n / 1048576).toFixed(1) + " MB" : (n / 1073741824).toFixed(2) + " GB";

let results = [], sel = 0, seq = 0, timer = 0;

// ---------- toast ----------
let toastT = 0;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("on");
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove("on"), 3200);
}
window.nfNotice = toast;
window.nfFocus = () => { tab("search"); const q = $("#q"); q.focus(); q.select(); };
// (nfHere is set with the filters below)

// ---------- tabs ----------
function tab(name) {
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("on", v.id === "v-" + name));
  if (name === "index") refreshStatus(true);
  if (name === "settings") renderSettings();
}
document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => tab(b.dataset.tab)));

// ---------- search ----------
// ---------- filters (combined with whatever the question says) ----------
const filters = { kind: "", modified: "", size: "", folder: "", sort: "" };
const SELECTS = { kind: "#fKind", modified: "#fModified", size: "#fSize", sort: "#fSort" };
const anyFilter = () => !!(filters.kind || filters.modified || filters.size || filters.folder);
const baseName = p => String(p || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || p;
let hereFolder = "";
function paintFilters() {
  for (const [k, sel] of Object.entries(SELECTS)) { $(sel).value = filters[k]; $(sel).classList.toggle("on", !!filters[k]); }
  const f = $("#fFolder");
  f.textContent = filters.folder ? "In " + baseName(filters.folder) + "  ✕" : "Any folder";
  f.title = filters.folder ? filters.folder + " (click to search everywhere again)" : "Only inside one folder";
  f.classList.toggle("on", !!filters.folder);
  const h = $("#fHere");
  h.hidden = !hereFolder || filters.folder === hereFolder;
  h.textContent = "Here: " + baseName(hereFolder);
  h.title = hereFolder;
  $("#fClear").hidden = !(anyFilter() || filters.sort);
}
for (const [k, sel] of Object.entries(SELECTS)) $(sel).addEventListener("change", e => { filters[k] = e.target.value; paintFilters(); run(); });
$("#fFolder").addEventListener("click", async () => {
  if (filters.folder) filters.folder = "";
  else { const r = await api("pick_folder"); if (!r || !r.path) return; filters.folder = r.path; }
  paintFilters(); run();
});
$("#fHere").addEventListener("click", () => { filters.folder = hereFolder; paintFilters(); run(); });
$("#fClear").addEventListener("click", () => { Object.keys(filters).forEach(k => filters[k] = ""); paintFilters(); run(); $("#q").focus(); });
window.nfHere = async () => { const r = await api("here_folder"); hereFolder = (r && r.path) || ""; paintFilters(); if ($("#q").value.trim()) run(); };

// The quick find bar hands its words over (Alt+Enter): type them here and search.
window.nfQuery = text => { tab("search"); const q = $("#q"); q.value = String(text || ""); q.focus(); run(); };

async function run() {
  const text = $("#q").value;
  const my = ++seq;
  if (!text.trim() && !anyFilter()) { results = []; render({ results: [], understood: [] }); return; }
  const r = await api("search", text, filters);
  if (my !== seq || !r) return;               // a newer search is already running
  results = r.results || [];
  sel = 0;
  render(r);
}

function render(r) {
  $("#understood").innerHTML = (r.understood || []).map(u => `<span class="chip">${esc(u)}</span>`).join("");
  const q = $("#q").value.trim() || anyFilter();
  $("#home").style.display = q ? "none" : "";
  if (!q && Date.now() - recentAt > 3000) loadRecent();
  const count = results.length ? `${results.length}${r.more ? "+" : ""} results · ${r.ms} ms` : "Nothing found. Try fewer or other words, or fewer filters.";
  $("#meta").innerHTML = !q ? "" : r.error ? esc(r.error) :
    esc(count) + (r.notes || []).map(n => ` · <span class="note">${esc(n)}</span>`).join("");
  const firstWeak = results.findIndex(x => x.weak);
  $("#results").innerHTML = results.map((x, i) => `${i === firstWeak && i > 0 ? `<li class="divider">Less sure</li>` : ""}
    <li class="res${i === sel ? " sel" : ""}${x.weak ? " weak" : ""}" data-i="${i}">
      <span class="ico${THUMB_KINDS.has(x.kind) ? " thumbable" : ""}" data-id="${Number(x.id)}">${esc(KIND[x.kind] || "FILE")}</span>
      <div><div class="name">${esc(x.name)}</div><div class="dir">${esc(x.dir)}</div>
        ${x.snippet ? `<div class="snip">${marks(x.snippet)}</div>` : ""}
        <div class="why">${(x.why || []).map(w => `<span>${esc(w)}</span>`).join("")}</div></div>
      <div class="side">${esc(x.ago)}<br>${esc(size(x.size))}</div>
    </li>`).join("");
  watchThumbs();
}

// ---------- previews: Windows' own thumbnails, asked for by result id, only for results on screen ----------
const THUMB_KINDS = new Set(["image", "video", "pdf"]);
const thumbCache = new Map();
const thumbSeen = new IntersectionObserver(entries => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    thumbSeen.unobserve(e.target);
    loadThumb(e.target);
  }
}, { rootMargin: "200px" });
async function loadThumb(el) {
  const id = Number(el.dataset.id);
  let url = thumbCache.get(id);
  if (url === undefined) { const r = await api("thumbnail", id); url = (r && r.url) || ""; thumbCache.set(id, url); }
  if (!url || !url.startsWith("data:image/")) return;       // only our own data: URLs, never a page-made string
  const img = new Image();
  img.alt = "";
  img.src = url;                                            // set as a property, never through innerHTML
  el.textContent = "";
  el.appendChild(img);
  el.classList.add("has-thumb");
}
function watchThumbs() { document.querySelectorAll(".ico.thumbable").forEach(el => thumbSeen.observe(el)); }

function select(i) {
  if (!results.length) return;
  sel = Math.max(0, Math.min(results.length - 1, i));
  document.querySelectorAll(".res").forEach((el, k) => el.classList.toggle("sel", k === sel));
  const el = document.querySelector(`.res[data-i="${sel}"]`);
  if (el) el.scrollIntoView({ block: "nearest" });
}

async function act(kind, i = sel) {
  const x = results[i];
  if (!x) return;
  if (kind === "open") { const r = await api("open", x.id); if (r && !r.ok) toast(r.error); else if ((await api("get_settings") || {}).hide_after_open) api("hide"); }
  if (kind === "reveal") { const r = await api("reveal", x.id); if (r && !r.ok) toast("Couldn't show it in its folder."); }
  if (kind === "copy") { const r = await api("path_of", x.id); if (r && r.path) { await navigator.clipboard.writeText(r.path); toast("Path copied."); } }
  if (kind === "forget") {
    if (!confirm(`Forget "${x.name}" and keep it out of the index from now on?`)) return;
    const r = await api("forget", x.id);
    if (r && r.ok) { toast("Forgotten. Undo it in Settings → Never search."); run(); }
  }
}

$("#q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 110); });
$("#results").addEventListener("click", e => { const li = e.target.closest(".res"); if (li) { select(+li.dataset.i); act(e.ctrlKey ? "reveal" : "open"); } });
$("#results").addEventListener("contextmenu", e => { const li = e.target.closest(".res"); if (li) { e.preventDefault(); select(+li.dataset.i); act("reveal"); } });
document.addEventListener("keydown", e => {
  if (e.ctrlKey && ["1", "2", "3"].includes(e.key)) { e.preventDefault(); tab(["search", "index", "settings"][+e.key - 1]); return; }
  if (!$("#v-search").classList.contains("on")) { if (e.key === "Escape") api("hide"); return; }
  if (e.key === "ArrowDown") { e.preventDefault(); select(sel + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); select(sel - 1); }
  else if (e.key === "Enter") { e.preventDefault(); act(e.ctrlKey ? "reveal" : "open"); }
  else if (e.key === "Escape") { if ($("#q").value) { $("#q").value = ""; run(); } else api("hide"); }
  else if (e.key === "c" && e.ctrlKey && !window.getSelection().toString()) { e.preventDefault(); act("copy"); }
  else if (e.key === "Delete" && e.shiftKey) { e.preventDefault(); act("forget"); }
});

// ---------- index status ----------
const PHASE = { starting: "Starting", names: "Finding files", text: "Reading text", images: "Reading photos and scans", photos: "Understanding photos", meaning: "Learning meaning", watching: "Up to date", error: "Stopped" };
async function refreshStatus(full) {
  const s = await api("status");
  if (!s) { $("#railState").textContent = "preview"; return; }
  const phase = s.paused ? "Paused · " + s.paused : (PHASE[s.phase] || s.phase);
  $("#railState").textContent = phase;
  paintHome(s);
  if (!full && !$("#v-index").classList.contains("on")) return;
  paintIndexPage(s);
  const card = (v, l, live) => `<div class="card${live ? " live" : ""}"><b>${esc(v)}</b><span>${esc(l)}</span></div>`;
  $("#cards").innerHTML = [
    card(phase, "Status", s.phase !== "watching"),
    card(Number(s.files).toLocaleString(), "Files and folders"),
    card(Number(s.with_text).toLocaleString(), "Files with readable text"),
    card(Number((s.vectors || 0) + (s.name_vectors || 0)).toLocaleString(), "Meaning vectors (text + names)"),
    card(Number(s.photo_vectors || 0).toLocaleString(), "Photos understood"),
    card(s.memory_mb ? s.memory_mb + " MB" : "–", (s.models_loaded || []).length
      ? "Memory now · models in use: " + s.models_loaded.join(", ") : "Memory now · no models loaded (they load when you search)"),
    card(s.rate ? Number(s.rate).toLocaleString() + "/s" : "–", "Scan speed"),
    card((s.db_bytes / 1048576).toFixed(0) + " MB", "Index size"),
    card(s.plan && s.plan.cpu ? `${s.plan.text_workers}–${s.plan.text_workers_idle} of ${s.plan.cpu}` : "–", "Text workers / CPU threads"),
    card(s.speed ? s.speed.split(" (")[0] : "–", s.speed ? "Speed: " + s.speed.split(" (")[1].replace(")", "") : "Speed"),
    card(s.ocr === true ? "On" : "Off", s.ocr === true ? "OCR (Windows, offline)" : "OCR: " + (s.ocr || "not available")),
    card(s.plan && "ssd" in s.plan ? (s.plan.ssd ? "SSD" : "Hard disk") : "–", "Drive type"),
  ].join("");
  $("#roots").innerHTML = (s.roots || []).map(r => `<li>${esc(r)}</li>`).join("");
  const DT = { fixed: "this PC", removable: "USB / external", network: "network", cd: "disc", ram: "RAM disk" };
  $("#drives").innerHTML = (s.drives || []).map(d => `<li>${esc(d.root)} ${esc(d.label)} <span class="dim">· ${esc(DT[d.type] || d.type)}${d.present ? "" : " · not connected"}</span></li>`).join("");
  const n = $("#encNote");
  n.className = "note" + (s.encrypted ? "" : " warn");
  n.textContent = s.encrypted
    ? "The index is encrypted on disk (SQLCipher). Its key is protected by your Windows sign-in, and nothing leaves this PC."
    : "The index is NOT encrypted: SQLCipher isn't installed in this build. It stays in your own profile folder.";
}
$("#rescan").addEventListener("click", async () => { await api("rescan"); toast("Rescan started."); });
// The Indexing page refreshes every 2 s, but only while it is the open tab AND the window is really on screen.
// On other tabs the rail line just keeps itself current every 15 s.
function ixTick() {
  if (document.visibilityState === "visible" && $("#v-index").classList.contains("on")) refreshStatus(false);
}
setInterval(ixTick, 2000);
setInterval(() => { if (document.visibilityState === "visible" && !$("#v-index").classList.contains("on")) refreshStatus(false); }, 15000);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refreshStatus(false); });
const reportVisible = () => api("page_visible", document.visibilityState === "visible");
document.addEventListener("visibilitychange", reportVisible);
reportVisible();
setInterval(() => { if (document.visibilityState === "visible") api("heartbeat"); }, 5000);

// ---------- Indexing page: what NOBAD Find is doing, what it costs, what it decided ----------
const LEVEL = {
  full: "Working at full speed", gentle: "Working gently",
  light: "Working very lightly", paused: "Paused",
};
const STATE = { waiting: "Waiting", running: "Working", done: "Done", off: "Off" };
const fin = n => (Number.isFinite(Number(n)) ? Number(n) : 0);
const num = n => fin(n).toLocaleString();
const mb = v => { const n = fin(v); return n >= 1024 ? (n / 1024).toFixed(1) + " GB" : (n >= 100 ? Math.round(n) : n.toFixed(n < 10 ? 1 : 0)) + " MB"; };
function span(sec) {
  sec = Math.max(0, Math.round(sec));
  if (sec < 45) return "under a minute";
  if (sec < 5400) return "about " + Math.max(1, Math.round(sec / 60)) + " min";
  if (sec < 172800) return "about " + Math.round(sec / 3600) + " h";
  return "about " + Math.round(sec / 86400) + " days";
}
function perTime(r, unit) {
  if (!r || r <= 0) return "";
  return r >= 1 ? `${r >= 10 ? Math.round(r) : r.toFixed(1)} ${unit} per second` : `${Math.max(1, Math.round(r * 60))} ${unit} per minute`;
}
const pct = v => (v == null ? "–" : Math.round(v) + "%");

// The Now panel is built once (index.html) and updated in place, so the button keeps keyboard focus and the
// live region only changes (and is only announced) when the level or the reason really changes.
function paintNow(s) {
  const lv = LEVEL[s.level] ? s.level : "light", paused = lv === "paused";
  $("#ixNow").className = "now lv-" + lv;
  const lvEl = $("#ixLevel"), rsEl = $("#ixReason"), reason = s.reason || "";
  if (lvEl.textContent !== LEVEL[lv]) lvEl.textContent = LEVEL[lv];
  if (rsEl.textContent !== reason) rsEl.textContent = reason;
  const b = $("#ixPause"), act = paused ? "resume" : "pause";
  if (b.dataset.act !== act) {
    b.dataset.act = act;
    b.textContent = paused ? "Resume" : "Pause for 1 hour";
    b.classList.toggle("ghost", !paused);
  }
  b.disabled = false;
}
// A <progress> element, not a styled <i>: the CSP forbids inline styles, and this needs none.
const meter = (frac, busy) => `<progress class="meter" max="100"${busy ? "" : ` value="${Math.round(frac * 100)}"`}></progress>`;
function paintPipeline(s) {
  $("#ixPipeline").innerHTML = (s.phases || []).map(p => {
    const total = fin(p.total), done = fin(p.done), known = total > 0;
    const frac = p.state === "done" ? 1 : known ? Math.min(1, done / total) : 0;
    const count = p.state === "off" ? "" : known ? `${num(done)} / ${num(total)}` : done ? num(done) : "";
    const extra = p.state === "running"
      ? [perTime(p.rate, "files"), p.eta_s != null ? "done in " + span(p.eta_s) : ""].filter(Boolean).join(" · ") : "";
    return `<div class="phase ${esc(p.state)}"><span class="pl">${esc(p.label)}</span><span class="ps">${esc(STATE[p.state] || p.state)}</span>
      ${meter(frac, p.state === "running" && !known)}
      <span class="pc">${esc(count)}</span><span class="pe">${esc(extra)}</span></div>`;
  }).join("");
}
function paintResources(s) {
  const r = s.resources || {};
  const stat = (v, l) => `<div class="stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`;
  $("#ixStats").innerHTML = stat(pct(r.cpu), "Processor") + stat(r.memory_mb != null ? mb(r.memory_mb) : "–", "Memory") +
    stat(r.read_mb_s != null ? fin(r.read_mb_s).toFixed(fin(r.read_mb_s) < 10 ? 1 : 0) + " MB/s" : "–", "Disk reading") +
    stat(r.gpu == null ? "Not used" : pct(r.gpu), "Graphics card");
  const ps = r.processes || [];
  $("#ixProcs").innerHTML = ps.length
    ? `<thead><tr><th>Process</th><th>PID</th><th>Processor</th><th>Memory</th></tr></thead><tbody>` +
      ps.map(p => `<tr><td>${esc(p.name)}</td><td>${esc(p.pid)}</td><td>${esc(pct(p.cpu))}</td><td>${esc(mb(p.memory_mb || 0))}</td></tr>`).join("") + "</tbody>"
    : "";
  drawSpark(s.history || []);
}
let sparkData = [], sparkHover = -1;
function drawSpark(h) {
  sparkData = h;
  const c = $("#ixSpark"), dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth, ht = c.clientHeight;
  if (!w || !ht) return;
  if (c.width !== Math.round(w * dpr) || c.height !== Math.round(ht * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(ht * dpr); }
  const g = c.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, ht);
  const css = getComputedStyle(document.documentElement);
  const col = n => css.getPropertyValue(n).trim() || "#888";
  const padT = 8, padB = 6, H = ht - padT - padB, n = h.length;
  const maxCpu = Math.max(10, Math.ceil(Math.max(0, ...h.map(x => x.find_cpu || 0)) / 10) * 10);
  const maxMb = Math.max(1, ...h.map(x => x.find_mb || 0)) * 1.1;
  const X = i => w - (n - 1 - i) / 149 * w;            // the newest sample is always at the right edge
  const Y = (v, m) => padT + H - (v / m) * H;
  g.strokeStyle = col("--line"); g.lineWidth = 1;
  for (const f of [0, .5, 1]) { const y = Math.round(padT + H * f) + .5; g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
  g.fillStyle = col("--dim"); g.font = "10px Consolas, monospace"; g.textBaseline = "top";
  g.fillText(maxCpu + "%", 4, padT + 3);
  if (n < 2) { $("#ixSparkCap").textContent = "Collecting the first readings…"; return; }
  const line = (key, m, color, width, dash) => {
    g.beginPath(); h.forEach((x, i) => g[i ? "lineTo" : "moveTo"](X(i), Y(x[key] || 0, m)));
    g.setLineDash(dash); g.strokeStyle = color; g.lineWidth = width; g.lineJoin = "round"; g.stroke(); g.setLineDash([]);
  };
  line("find_mb", maxMb, col("--dim"), 1.25, [4, 3]);
  g.beginPath(); h.forEach((x, i) => g[i ? "lineTo" : "moveTo"](X(i), Y(x.find_cpu || 0, maxCpu)));
  g.lineTo(X(n - 1), padT + H); g.lineTo(X(0), padT + H); g.closePath();
  const grad = g.createLinearGradient(0, padT, 0, padT + H);
  grad.addColorStop(0, "rgba(" + col("--o-rgb") + ", .28)"); grad.addColorStop(1, "rgba(" + col("--o-rgb") + ", 0)");
  g.fillStyle = grad; g.fill();
  line("find_cpu", maxCpu, col("--o"), 1.75, []);
  const i = sparkHover >= 0 ? Math.min(n - 1, sparkHover) : n - 1, x = h[i];
  g.beginPath(); g.arc(X(i), Y(x.find_cpu || 0, maxCpu), 3.5, 0, 7); g.fillStyle = col("--o"); g.fill();
  const when = i === n - 1 ? "now" : span((n - 1 - i) * 2).replace("about ", "") + " ago";
  $("#ixSparkCap").innerHTML = `<span class="k cpu">Processor ${esc(pct(x.find_cpu || 0))}</span><span class="k mem">Memory ${esc(mb(x.find_mb || 0))}</span>` +
    `<span class="when">${esc(when)} · last 5 minutes</span>`;
}
$("#ixSpark").addEventListener("mousemove", e => {
  const c = e.currentTarget, n = sparkData.length;
  if (n < 2) return;
  sparkHover = Math.max(0, Math.min(n - 1, Math.round(e.offsetX / c.clientWidth * 149 - (150 - n))));
  drawSpark(sparkData);
});
$("#ixSpark").addEventListener("mouseleave", () => { sparkHover = -1; drawSpark(sparkData); });

function paintModels(s) {
  $("#ixModels").innerHTML = (s.models || []).map(m => {
    const dl = m.download;
    const where = m.device ? " on " + (m.device === "Windows" ? "Windows" : m.device) : "";
    const state = dl ? `Downloading ${mb(dl.got_mb)} of ${mb(dl.size_mb)}${fin(dl.mb_s) ? " at " + fin(dl.mb_s).toFixed(1) + " MB/s" : ""}`
      : m.loaded ? "In use now" + where : m.on_disk ? "Ready, loads when needed" : "Not downloaded";
    const bits = [m.size_mb ? mb(m.size_mb) + " download" : "Built into Windows", m.license,
      m.loaded && m.memory_mb ? mb(m.memory_mb) + " of memory" : "", m.items ? num(m.items) + " items made" : ""].filter(Boolean);
    return `<div class="model${m.loaded ? " live" : ""}"><div class="mh"><b>${esc(m.name)}</b><span class="ms">${esc(state)}</span></div>
      <p>${esc(bits.join(" · "))}</p>${dl && fin(dl.size_mb) > 0 ? meter(Math.min(1, fin(dl.got_mb) / fin(dl.size_mb))) : ""}</div>`;
  }).join("");
}
function clock(t) {
  const d = new Date(t < 1e11 ? t * 1000 : t);
  return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function paintActivity(s) {
  const a = s.activity || [];
  $("#ixActivity").innerHTML = a.length ? a.map(x => `<li><time>${esc(clock(x.t))}</time><span>${esc(x.text)}</span></li>`).join("")
    : `<li class="none">Nothing yet. NOBAD Find adds a line here whenever it changes pace, pauses or finishes something.</li>`;
}
function paintIndexPage(s) { paintNow(s); paintPipeline(s); paintResources(s); paintModels(s); paintActivity(s); }
$("#ixNow").addEventListener("click", async e => {
  const b = e.target.closest("#ixPause");
  if (!b) return;
  b.disabled = true;
  if (b.dataset.act === "resume") await api("resume"); else await api("pause_for", 3600);
  refreshStatus(true);
});
window.addEventListener("resize", () => { if ($("#v-index").classList.contains("on")) drawSpark(sparkData); });
if (!localStorage.getItem("nf-bg-notice")) $("#bgNotice").hidden = false;
$("#bgNoticeOk").addEventListener("click", () => { localStorage.setItem("nf-bg-notice", "1"); $("#bgNotice").hidden = true; });

// ---------- home: shown while the search box and filters are empty ----------
const EXAMPLES = ["rent pdf from last week", "beach photos in march", "budget.xlsx", "newest in my downloads", "video bigger than 100 mb"];
const TILES = [
  ["PDF", "PDFs", { kind: "pdf" }], ["IMG", "Photos", { kind: "image" }], ["DOC", "Documents", { kind: "document" }],
  ["XLS", "Spreadsheets", { kind: "spreadsheet" }], ["DIR", "Downloads folder", { text: "in my downloads" }],
  ["NEW", "Recent", { modified: "week", sort: "newest" }],
];
$("#homeChips").innerHTML = EXAMPLES.map((t, i) => `<button class="eg" data-i="${i}">${esc(t)}</button>`).join("");
$("#homeTiles").innerHTML = TILES.map(([g, label], i) => `<button class="tile" data-i="${i}"><span class="ico">${esc(g)}</span>${esc(label)}</button>`).join("");
$("#homeChips").addEventListener("click", e => {
  const b = e.target.closest(".eg");
  if (!b) return;
  $("#q").value = EXAMPLES[+b.dataset.i];
  $("#q").focus();
  run();
});
$("#homeTiles").addEventListener("click", e => {
  const b = e.target.closest(".tile");
  if (!b) return;
  const t = TILES[+b.dataset.i][2];
  Object.keys(filters).forEach(k => filters[k] = "");      // the same controls as the filter bar
  $("#q").value = t.text || "";
  for (const k of ["kind", "modified", "sort"]) if (t[k]) filters[k] = t[k];
  paintFilters();
  run();
});

let recentAt = 0;
async function loadRecent() {
  if ($("#home").style.display === "none") return;
  recentAt = Date.now();
  const r = await api("search", "", { sort: "newest" });
  const files = ((r && r.results) || []).filter(x => x.kind !== "folder").slice(0, 8);
  $("#homeRecent").innerHTML = files.length ? files.map(x => `<li><button class="rc" data-id="${Number(x.id)}">
      <span class="ico">${esc(KIND[x.kind] || "FILE")}</span>
      <span class="rn"><b>${esc(x.name)}</b><span>${esc(x.dir)}</span></span><span class="ra">${esc(x.ago)}</span></button></li>`).join("")
    : `<li class="none">Files you change will show up here once they are indexed.</li>`;
}
$("#homeRecent").addEventListener("click", async e => {
  const b = e.target.closest(".rc");
  if (!b) return;
  const r = await api("open", Number(b.dataset.id));
  if (r && !r.ok) toast(r.error); else if ((await api("get_settings") || {}).hide_after_open) api("hide");
});
function paintHome(s) {
  const el = $("#homeStatus");
  if (!s) { el.textContent = ""; return; }
  const lv = LEVEL[s.level] || "";
  el.innerHTML = `<span class="hs-n">${esc(num(s.files))}</span> files indexed${lv ? ` · ${esc(lv)}` : ""} · <button class="link" id="homeDetails">Details</button>`;
  if (Date.now() - recentAt > 14000) loadRecent();
}
$("#homeStatus").addEventListener("click", e => { if (e.target.id === "homeDetails") document.querySelector(".tab[data-tab=index]").click(); });

// ---------- settings ----------
// Each page is a list of groups; each group is [title, rows]; each row is [key, type, label, help, options?].
// Keys starting with "_" are not settings: they draw a block (model download, Windows Search, hardware, ...).
const PAGES = {
  general: [
    ["Look and launch", [
      ["theme", "select", "Theme", "Dark or light. Applies right away.", [["dark", "Dark"], ["light", "Light"]]],
      ["glass", "switch", "See-through window", "Windows 11 acrylic behind the window. Follows Windows' own Transparency effects switch. Takes effect at the next start."],
      ["hotkey", "txt", "Hotkey", "For example win+shift+space or ctrl+alt+f. Takes effect at the next start."],
      ["bar", "switch", "Quick find bar", "A small search box on its own shortcut that shows over whatever you are doing. Takes effect at the next start."],
      ["bar_hotkey", "txt", "Quick find bar shortcut", "For example ctrl+alt+space or win+alt+f. Takes effect at the next start."],
      ["hide_after_open", "switch", "Hide after opening a file", "Off: the window stays up after Enter opens a file. On: it hides, like a launcher."],
      ["autostart", "switch", "Start with Windows", "Starts hidden; the hotkey opens it."],
    ]],
  ],
  indexing: [
    ["What to search", [
      ["roots", "folders", "Folders to search", "Empty: your profile folder and every fixed drive (never other people's profiles or Windows itself)."],
      ["exclude", "folders", "Never search", "These folders and files are skipped and removed from the index."],
      ["content", "switch", "Read the text inside files", "Documents, PDFs, code, notes and e-mail files. Off: names only."],
      ["content_max_mb", "num", "Largest file to read (MB)", "Bigger files are still found by name."],
      ["ocr", "switch", "Words in photos and scans", "Screenshots, photos of documents and scanned PDFs, read with the OCR built into Windows (offline). Slower, so it runs after everything else."],
      ["src_mail", "switch", "E-mail files", ".eml and .mbox files found on your drives."],
      ["index_removable", "switch", "USB and external drives", "Indexed while plugged in. Their files stay findable (marked “not connected”) when you unplug them. Turning this off removes their files from the index."],
      ["index_network", "switch", "Network drives", "Mapped network drives (Z: and so on). Big shares take a while and use your home or office network."],
    ]],
  ],
  models: [
    ["Your PC", [["_hardware", "hardware", "", ""]]],
    ["Meaning search", [
      ["allow_model_download", "switch", "Allow the one-time model download",
        "23 MB from Hugging Face (all-MiniLM-L6-v2, pinned and checked by SHA-256). This is NOBAD Find's only internet connection."],
      ["semantic", "switch", "Search by meaning", "Finds “lease agreement” when you type “rent”, and photos or bills by what their names mean. Runs on this PC only."],
      ["_model", "model", "Model", ""],
    ]],
    ["Photo meaning", [
      ["allow_photo_model_download", "switch", "Allow the one-time photo model download",
        "About 211 MB from Hugging Face (SigLIP base by Google, Apache-2.0; pinned and checked by SHA-256). Only needed for this feature."],
      ["photo_meaning", "switch", "Find photos by what's in them", "“Dog on a beach” finds IMG_0042.jpg even with no words in it. Runs on this PC only. The first pass is slow (a few photos per second), in the background."],
      ["_photo_model", "pmodel", "Photo model", ""],
    ]],
  ],
  performance: [
    ["Staying out of your way", [
      ["games_mode", "select", "Games and presentations",
        "Smart slows down or pauses only for the apps that really need your PC, and learns which ones. Always pause stops whenever a game is running. Don't change never reacts to games. Presentations always pause NOBAD Find.",
        [["smart", "Smart (recommended)"], ["always", "Always pause"], ["off", "Don't change"]]],
      ["pause_on_battery", "switch", "Pause on battery", ""],
      ["pause_on_call", "switch", "Pause during calls", "While an app uses the microphone or camera."],
      ["keep_background", "switch", "Keep indexing in the background",
        "Closing the window stops indexing and every worker; NOBAD Find stays as one small idle process so the hotkey works. On: keeps indexing after closing."],
      ["workers", "num", "Text reading workers", "0 = choose from your CPU: two threads stay free while you use the PC, one when you're away."],
    ]],
    ["Apps NOBAD Find has learned", [["_learned", "learned", "Apps that slowed your PC down",
      "When an app lagged while NOBAD Find was working, NOBAD Find remembers the app's file name (nothing else) and starts gentler next time."]]],
  ],
  privacy: [
    ["Windows Search", [["_wsearch", "wsearch", "Use NOBAD Find instead of Windows Search", ""]]],
    ["Your data", [["_wipe", "wipe", "Delete the whole index", "Removes everything NOBAD Find has stored. It starts again from scratch."]]],
  ],
  about: [
    ["NOBAD Find", [["_about", "about", "", ""]]],
    ["Quit", [["_quit", "quit", "Quit NOBAD Find",
      "Closing the window stops indexing and leaves NOBAD Find as one small idle process so the hotkey still works (unless Keep indexing in the background is on). This stops it completely until you start it again."]]],
  ],
};
const SP_LINK = "github.com/nobad-studio/Nobad-VPN";
const gb = v => { const n = fin(v); return n ? (n >= 100 ? Math.round(n) : n.toFixed(1).replace(/\.0$/, "")) + " GB" : "–"; };
const bare = exe => String(exe || "").replace(/\.exe$/i, "");

function hardwareBlock(h) {
  if (!h) return `<p class="note">Not available here.</p>`;
  const tile = (v, l, wide) => `<div class="stat${wide ? " wide" : ""}"><b>${esc(v)}</b><span>${esc(l)}</span></div>`;
  const fast = [h.avx2 ? "AVX2" : "", h.avx512_vnni ? "AVX-512 VNNI" : ""].filter(Boolean).join(" + ");
  const drive = h.ssd === true ? "SSD" : h.ssd === false ? "Hard disk" : "Disk";
  return `<div class="stats hw">` +
    tile(gb(h.ram_gb), "Memory") +
    tile(`${num(h.cores)} cores`, `${num(h.threads)} threads`) +
    tile(h.gpu || "None found", h.gpu ? (fin(h.vram_gb) ? gb(h.vram_gb) + " video memory" : "Graphics card") + (h.directml ? ", usable for models" : "") : "Graphics card", true) +
    tile(fast || "Standard", "Processor speed-ups") +
    tile(drive, fin(h.disk_free_gb) ? gb(h.disk_free_gb) + " free" : "Drive type") + `</div>`;
}
function learnedBlock(list) {
  if (!list || !list.length) return `<p class="note">None yet. When an app lags while NOBAD Find works, it shows up here.</p>`;
  return list.map(a => `<div class="lapp"><div><b>${esc(bare(a.exe))}</b><small>${esc(a.reason)} Seen ${esc(num(a.seen))} ${a.seen === 1 ? "time" : "times"}.</small></div>
    <button class="btn ghost" data-reset="${esc(a.exe)}">Forget</button></div>`).join("");
}

async function renderSettings() {
  const s = await api("get_settings");
  if (!s) { $("#sp-general").innerHTML = "<p class='note'>Settings are available in the app.</p>"; return; }
  const st = await api("status");
  const ws = await api("wsearch_state");
  const hwd = await api("hardware");
  const learned = await api("learned_apps");
  applyTheme(s.theme);
  for (const [page, groups] of Object.entries(PAGES)) {
    $("#sp-" + page).innerHTML = groups.map(([title, rows]) => `<div class="group"><h3>${esc(title)}</h3>${rows.map(([k, type, label, help, opts]) => {
      let ctl = "", extra = "";
      if (type === "switch") ctl = `<input class="switch" type="checkbox" data-k="${k}" ${s[k] ? "checked" : ""} aria-label="${esc(label)}">`;
      if (type === "num") ctl = `<input class="num" type="number" min="0" data-k="${k}" value="${esc(s[k])}" aria-label="${esc(label)}">`;
      if (type === "txt") ctl = `<input class="txt" type="text" data-k="${k}" value="${esc(s[k])}" aria-label="${esc(label)}">`;
      if (type === "select") ctl = `<select class="pick" data-k="${k}" aria-label="${esc(label)}">${opts.map(([v, l]) => `<option value="${esc(v)}"${s[k] === v ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
      if (type === "folders") ctl = `<button class="btn ghost" data-add="${k}">Add folder</button>
        <div class="list">${(s[k] || []).map((p, i) => `<div><span>${esc(p)}</span><button data-del="${k}" data-i="${i}" title="Remove">✕</button></div>`).join("")}</div>`;
      if (type === "model") {
        const m = st && st.model || {};
        help = m.state === "ready" ? "Downloaded and verified." : m.state === "downloading"
          ? `Downloading… ${m.size ? Math.round(100 * m.got / m.size) : 0}%` : (m.error ? "Last try failed: " + m.error : "Not downloaded.");
        ctl = m.state === "ready" ? "" : `<button class="btn" id="getModel">Download</button>`;
      }
      if (type === "pmodel") {
        const m = st && st.photo_model || {};
        help = m.state === "ready" ? `Downloaded and verified. ${Number(st.photo_vectors || 0).toLocaleString()} photos understood so far.`
          : m.state === "downloading" ? `Downloading… ${m.size ? Math.round(100 * m.got / m.size) : 0}%`
          : (m.error ? "Last try failed: " + m.error : "Not downloaded.");
        ctl = m.state === "ready" ? "" : `<button class="btn" id="getPhotoModel">Download</button>`;
      }
      if (type === "hardware") return `<div class="set block">${hardwareBlock(hwd)}</div>`;
      if (type === "learned") {
        ctl = learned && learned.length ? `<button class="btn ghost" id="resetAll">Reset all</button>` : "";
        extra = `<div class="lapps">${learnedBlock(learned)}</div>`;
      }
      if (type === "about") {
        return `<div class="set about"><div><b class="ver">Version ${esc((st && st.version) || "")}</b>
          <p>Private, offline file search for Windows. Your files, your index and your searches stay on this PC.</p>
          <p class="dim">Open source under the MIT licence. Source and releases: ${esc(SP_LINK)}</p></div>
          <button class="btn ghost" id="copyLink">Copy link</button></div>`;
      }
      if (type === "wsearch") {
        if (!ws || ws.missing) help = "Windows Search isn't installed on this PC.";
        else {
          const off = ws.start === "disabled";
          help = (off ? "Done: Windows Search indexing is off and NOBAD Find starts with Windows. "
                      : `Windows Search indexing is on (${esc(ws.start)}${ws.running ? ", running" : ""}). One click turns it off and starts NOBAD Find with Windows. `) +
            "<span class='warn'>With it off, the Start menu, Explorer and Outlook stop finding files by their content (NOBAD Find does that instead). " +
            "Windows asks for permission once; going back restores exactly the setting it had before.</span>";
          ctl = `<button class="btn ${off ? "ghost" : ""}" id="wsToggle" data-off="${off ? 0 : 1}">${off ? "Go back to Windows Search" : "Switch to NOBAD Find"}</button>`;
        }
      }
      if (type === "wipe") ctl = `<button class="btn danger" id="wipe">Delete index</button>`;
      if (type === "quit") ctl = `<button class="btn ghost" id="quitApp">Quit</button>`;
      return `<div class="set"><label><b>${esc(label)}</b>${help ? `<small>${type === "wsearch" ? help : esc(help)}</small>` : ""}</label>${ctl}${extra}</div>`;
    }).join("")}</div>`).join("");
  }
}
function showPage(name) {
  document.querySelectorAll("#spNav button").forEach(b => b.classList.toggle("on", b.dataset.sp === name));
  document.querySelectorAll(".spage").forEach(p => p.classList.toggle("on", p.id === "sp-" + name));
}
$("#spNav").addEventListener("click", e => { const b = e.target.closest("button[data-sp]"); if (b) showPage(b.dataset.sp); });

// The look, dark or light. Remembered locally so the next start does not flash the other one first.
function applyTheme(t) {
  const v = t === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = v;
  try { localStorage.setItem("nf-theme", v); } catch (e) { /* storage unavailable: the setting still applies */ }
}
applyTheme(localStorage.getItem("nf-theme"));

const settingsEl = $("#settings");
settingsEl.addEventListener("change", async e => {
  const k = e.target.dataset.k;
  if (!k) return;
  const v = e.target.type === "checkbox" ? e.target.checked : e.target.type === "number" ? Number(e.target.value) : e.target.value;
  if (k === "theme") applyTheme(v);
  const r = await api("set_settings", { [k]: v });
  if (r && !r.changed.length) toast("That value wasn't accepted.");
  renderSettings();
});
settingsEl.addEventListener("click", async e => {
  const t = e.target.closest("button") || e.target;
  const s = await api("get_settings");
  if (!s) return;
  if (t.dataset.add) {
    const r = await api("pick_folder");
    if (r && r.path) { await api("set_settings", { [t.dataset.add]: [...s[t.dataset.add], r.path] }); renderSettings(); }
  } else if (t.dataset.del) {
    const list = s[t.dataset.del].filter((_, i) => i !== +t.dataset.i);
    await api("set_settings", { [t.dataset.del]: list }); renderSettings();
  } else if (t.dataset.reset) {
    await api("reset_learned", t.dataset.reset); toast("Forgotten."); renderSettings();
  } else if (t.id === "resetAll") {
    if (confirm("Forget every app NOBAD Find has learned?")) { await api("reset_learned", null); toast("Forgotten."); renderSettings(); }
  } else if (t.id === "copyLink") {
    try { await navigator.clipboard.writeText("https://" + SP_LINK); toast("Link copied."); } catch (err) { toast("Couldn't copy the link."); }
  } else if (t.id === "getPhotoModel") {
    const r = await api("download_photo_model"); if (r && !r.ok) toast(r.error); else toast("Downloading the photo model…");
    const poll = setInterval(async () => { await renderSettings(); const st = await api("status"); if (!st || st.photo_model.state !== "downloading") clearInterval(poll); }, 1000);
  } else if (t.id === "getModel") {
    const r = await api("download_model"); if (r && !r.ok) toast(r.error); else toast("Downloading the model…");
    const poll = setInterval(async () => { await renderSettings(); const st = await api("status"); if (!st || st.model.state !== "downloading") clearInterval(poll); }, 1000);
  } else if (t.id === "wsToggle") {
    t.disabled = true; t.textContent = "Waiting for Windows…";
    const r = await api("use_instead_of_windows_search", t.dataset.off === "1");
    toast(r && r.ok ? "Done." : (r && r.error) || "No change.");
    renderSettings();
  } else if (t.id === "quitApp") {
    await api("quit");
  } else if (t.id === "wipe") {
    if (prompt('This deletes the whole index. Type DELETE to confirm.') === "DELETE") { await api("wipe", "DELETE"); toast("Index deleted. Rebuilding."); }
  }
});

window.addEventListener("pywebviewready", async () => {
  const s = await api("get_settings");
  if (s) applyTheme(s.theme);
  refreshStatus(false); loadRecent(); $("#q").focus();
});
$("#q").focus();
