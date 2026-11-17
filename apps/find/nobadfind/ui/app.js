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
  $("#empty").style.display = q ? "none" : "";
  const count = results.length ? `${results.length}${r.more ? "+" : ""} results · ${r.ms} ms` : "Nothing found. Try fewer or other words, or fewer filters.";
  $("#meta").innerHTML = !q ? "" : r.error ? esc(r.error) :
    esc(count) + (r.notes || []).map(n => ` · <span class="note">${esc(n)}</span>`).join("");
  $("#results").innerHTML = results.map((x, i) => `
    <li class="res${i === sel ? " sel" : ""}" data-i="${i}">
      <span class="ico">${esc(KIND[x.kind] || "FILE")}</span>
      <div><div class="name">${esc(x.name)}</div><div class="dir">${esc(x.dir)}</div>
        ${x.snippet ? `<div class="snip">${marks(x.snippet)}</div>` : ""}
        <div class="why">${(x.why || []).map(w => `<span>${esc(w)}</span>`).join("")}</div></div>
      <div class="side">${esc(x.ago)}<br>${esc(size(x.size))}</div>
    </li>`).join("");
}

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
  if (kind === "open") { const r = await api("open", x.id); if (r && !r.ok) toast(r.error); else api("hide"); }
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
  if (!full && !$("#v-index").classList.contains("on")) return;
  const card = (v, l, live) => `<div class="card${live ? " live" : ""}"><b>${esc(v)}</b><span>${esc(l)}</span></div>`;
  $("#cards").innerHTML = [
    card(phase, "Status", s.phase !== "watching"),
    card(Number(s.files).toLocaleString(), "Files and folders"),
    card(Number(s.with_text).toLocaleString(), "Files with readable text"),
    card(Number((s.vectors || 0) + (s.name_vectors || 0)).toLocaleString(), "Meaning vectors (text + names)"),
    card(Number(s.photo_vectors || 0).toLocaleString(), "Photos understood"),
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
setInterval(() => refreshStatus(false), 2500);

// ---------- settings ----------
const GROUPS = [
  ["What to search", [
    ["content", "switch", "Read the text inside files", "Documents, PDFs, code, notes and e-mail files. Off: names only."],
    ["content_max_mb", "num", "Largest file to read (MB)", "Bigger files are still found by name."],
    ["src_mail", "switch", "E-mail files", ".eml and .mbox files found on your drives."],
    ["ocr", "switch", "Words in photos and scans", "Screenshots, photos of documents and scanned PDFs, read with the OCR built into Windows (offline). Slower, so it runs after everything else."],
    ["index_removable", "switch", "USB and external drives", "Indexed while plugged in. Their files stay findable (marked “not connected”) when you unplug them. Turning this off removes their files from the index."],
    ["index_network", "switch", "Network drives", "Mapped network drives (Z: and so on). Big shares take a while and use your home or office network."],
    ["roots", "folders", "Folders to search", "Empty: your profile folder and every fixed drive (never other people's profiles or Windows itself)."],
    ["exclude", "folders", "Never search", "These folders and files are skipped and removed from the index."],
  ]],
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
  ["Staying out of your way", [
    ["pause_on_battery", "switch", "Pause on battery", ""],
    ["pause_fullscreen", "switch", "Pause during games and presentations", ""],
    ["pause_on_call", "switch", "Pause during calls", "While an app uses the microphone or camera."],
    ["workers", "num", "Text reading workers", "0 = choose from your CPU: two threads stay free while you use the PC, one when you're away."],
  ]],
  ["Launch", [
    ["hotkey", "txt", "Hotkey", "For example win+shift+space or ctrl+alt+f. Takes effect at the next start."],
    ["autostart", "switch", "Start with Windows", "Starts hidden; the hotkey opens it."],
  ]],
  ["Windows Search", [["_wsearch", "wsearch", "Use NOBAD Find instead of Windows Search", ""]]],
  ["Your data", [["_wipe", "wipe", "Delete the whole index", "Removes everything NOBAD Find has stored. It starts again from scratch."]]],
];

async function renderSettings() {
  const s = await api("get_settings");
  if (!s) { $("#settings").innerHTML = "<p class='note'>Settings are available in the app.</p>"; return; }
  const st = await api("status");
  const ws = await api("wsearch_state");
  $("#settings").innerHTML = GROUPS.map(([title, rows]) => `<div class="group"><h3>${esc(title)}</h3>${rows.map(([k, type, label, help]) => {
    let ctl = "";
    if (type === "switch") ctl = `<input class="switch" type="checkbox" data-k="${k}" ${s[k] ? "checked" : ""}>`;
    if (type === "num") ctl = `<input class="num" type="number" min="0" data-k="${k}" value="${esc(s[k])}">`;
    if (type === "txt") ctl = `<input class="txt" type="text" data-k="${k}" value="${esc(s[k])}">`;
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
    return `<div class="set"><label><b>${esc(label)}</b>${help ? `<small>${type === "wsearch" ? help : esc(help)}</small>` : ""}</label>${ctl}</div>`;
  }).join("")}</div>`).join("");
}

const settingsEl = $("#settings");
settingsEl.addEventListener("change", async e => {
  const k = e.target.dataset.k;
  if (!k) return;
  const v = e.target.type === "checkbox" ? e.target.checked : e.target.type === "number" ? Number(e.target.value) : e.target.value;
  const r = await api("set_settings", { [k]: v });
  if (r && !r.changed.length) toast("That value wasn't accepted.");
  renderSettings();
});
settingsEl.addEventListener("click", async e => {
  const t = e.target;
  const s = await api("get_settings");
  if (!s) return;
  if (t.dataset.add) {
    const r = await api("pick_folder");
    if (r && r.path) { await api("set_settings", { [t.dataset.add]: [...s[t.dataset.add], r.path] }); renderSettings(); }
  } else if (t.dataset.del) {
    const list = s[t.dataset.del].filter((_, i) => i !== +t.dataset.i);
    await api("set_settings", { [t.dataset.del]: list }); renderSettings();
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
  } else if (t.id === "wipe") {
    if (prompt('This deletes the whole index. Type DELETE to confirm.') === "DELETE") { await api("wipe", "DELETE"); toast("Index deleted. Rebuilding."); }
  }
});

window.addEventListener("pywebviewready", () => { refreshStatus(false); $("#q").focus(); });
$("#q").focus();
