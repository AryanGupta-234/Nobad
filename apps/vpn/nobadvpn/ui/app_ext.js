/* NOBAD VPN — UI additions. Loaded after the main inline script; shares its globals (S, $, $$, api, toast, esc, fmtB). */
(function () {
"use strict";
const NXS = { st: null, wizShown: false, restoring: false, dismissed: {}, lastSig: "", prevConn: null, usageAt: 0 };
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

/* ============================== text ============================== */
// English only. t() fills {placeholders}; translate() is kept as a no-op hook for older call sites.
function t(s, v) { return v ? String(s).replace(/\{(\w+)\}/g, (m, k) => (has(v, k) ? v[k] : m)) : s; }
function translate() {}

/* ============================== helpers ============================== */
const live = () => $("#nxlive");
function announce(msg) { const el = live(); if (!el) return; el.textContent = ""; setTimeout(() => { el.textContent = msg; }, 30); }
const skel = (n, kind) => Array.from({ length: n }, () => kind === "row"
  ? '<div class="nx-skelrow"><div class="skel dot"></div><div class="skel"></div><div class="skel" style="flex:.3"></div></div>'
  : '<div class="skel"></div>').join("");
const fmtBytes = b => (typeof fmtB === "function" ? fmtB(b) : String(b));

const MODALS = [];  // open modals, newest last: only the top one handles Esc / Tab
function modal(opts) {
  const prev = document.activeElement, id = "nxm" + Math.random().toString(36).slice(2, 7);
  const ov = document.createElement("div"); ov.className = "nx-ov";
  ov.innerHTML = `<div class="nx-modal${opts.wide ? " wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="${id}"><h2 id="${id}"></h2><div class="nx-sub"></div><div class="nx-body"></div><div class="nx-actions"></div></div>`;
  const box = ov.firstChild;
  box.querySelector("h2").textContent = opts.title || "";
  const sub = box.querySelector(".nx-sub"); if (opts.sub) sub.textContent = opts.sub; else sub.remove();
  const body = box.querySelector(".nx-body"); if (opts.html) body.innerHTML = opts.html;
  const bar = box.querySelector(".nx-actions");
  const api2 = { el: ov, box, body, bar, buttons: {}, close() { const i = MODALS.indexOf(api2); if (i >= 0) MODALS.splice(i, 1); ov.remove(); document.removeEventListener("keydown", onKey, true); if (prev && prev.focus) try { prev.focus(); } catch (_) {} if (opts.onClose) opts.onClose(); } };
  (opts.actions || []).forEach(a => {
    const b = document.createElement("button"); b.textContent = a.label; b.className = (a.cls || "") + (a.left ? " nx-left" : "");
    b.onclick = () => a.fn(api2); bar.appendChild(b); api2.buttons[a.id || a.label] = b;
  });
  function onKey(e) {
    if (!ov.isConnected || MODALS[MODALS.length - 1] !== api2) return;
    if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); api2.close(); return; }
    if (e.key !== "Tab") return;
    const f = [...box.querySelectorAll('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])')].filter(x => !x.disabled && x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  document.addEventListener("keydown", onKey, true);
  MODALS.push(api2);
  document.body.appendChild(ov); translate(ov);
  setTimeout(() => { const f = box.querySelector("input,textarea,select,button"); if (f) f.focus(); }, 0);
  return api2;
}
function askText(title, label, def, ph) {
  return new Promise(res => {
    let done = false; const fin = v => { if (!done) { done = true; res(v); } };
    const m = modal({ title, html: `<label class="nx-field"><span></span><input type="text" class="nx-in" maxlength="300"></label>`, onClose: () => fin(null),
      actions: [{ label: t("Cancel"), fn: x => x.close() }, { label: t("OK"), cls: "pri", id: "ok", fn: x => { fin(x.box.querySelector("input").value.trim() || null); x.close(); } }] });
    const inp = m.box.querySelector("input"), sp = m.box.querySelector("label span");
    sp.textContent = label; inp.value = def || ""; if (ph) inp.placeholder = ph;
    inp.onkeydown = e => { if (e.key === "Enter") m.buttons.ok.click(); };
  });
}

/* ============================== banners ============================== */
function bars() {
  let c = $("#nxbars");
  if (!c) { c = document.createElement("div"); c.id = "nxbars"; c.setAttribute("role", "region"); c.setAttribute("aria-label", "Notices"); $("#stage").prepend(c); window.addEventListener("resize", placeBars); }   /* overlay inside the stage: never a grid item of .app */
  return c;
}
function placeBars() {   // sit just under the status card (the error is about it) without covering it
  const c = $("#nxbars"), st = $("#stage"), h = $("#hud"); if (!c || !st) return;
  const sr = st.getBoundingClientRect(), hr = h && h.offsetParent ? h.getBoundingClientRect() : null;
  const left = hr ? Math.max(12, hr.left - sr.left) : 12;
  c.style.top = (hr ? hr.bottom - sr.top + 10 : 12) + "px"; c.style.left = left + "px";
  c.style.width = "min(560px, calc(100% - " + (left + 12) + "px))";
}
const BAR = {};
function setBar(id, spec) {
  const sig = JSON.stringify(spec);
  if (BAR[id] && BAR[id].sig === sig) return;
  clearBar(id, true);
  if (NXS.hiddenBars && NXS.hiddenBars[id] === sig) return;   // the user closed this exact notice
  const el = document.createElement("div"); el.className = "nx-bar " + spec.kind; el.dataset.id = id;
  el.setAttribute("role", spec.kind === "bad" ? "alert" : "status");
  el.innerHTML = `<div class="nx-bt"><b></b><p></p></div><div class="nx-ba"></div>`;
  el.querySelector("b").textContent = spec.title;
  const p = el.querySelector("p"); if (spec.detail) p.textContent = spec.detail; else p.remove();
  const ba = el.querySelector(".nx-ba");
  (spec.actions || []).forEach(a => { const b = document.createElement("button"); b.className = "sm" + (a.cls ? " " + a.cls : ""); b.textContent = a.label; b.onclick = () => a.fn(); ba.appendChild(b); });
  if (spec.close) {
    const x = document.createElement("button"); x.className = "nx-bx"; x.type = "button"; x.textContent = "×";
    x.setAttribute("aria-label", t("Close")); x.title = t("Close");
    x.onclick = () => { (NXS.hiddenBars = NXS.hiddenBars || {})[id] = sig; clearBar(id); if (typeof spec.close === "function") spec.close(); };
    el.appendChild(x);
  }
  bars().appendChild(el); translate(el); placeBars();
  BAR[id] = { el, sig };
  if (spec.ttl) {   // transient notices fade out by themselves; hovering or focusing them pauses the timer
    let left = spec.ttl, t0 = Date.now(), tm = null;
    const arm = () => { t0 = Date.now(); tm = setTimeout(() => { if (BAR[id] && BAR[id].el === el) { el.classList.add("nx-out"); setTimeout(() => { if (spec.expire) spec.expire(); else clearBar(id); }, 260); } }, left); };
    const hold = () => { if (tm) { clearTimeout(tm); tm = null; left = Math.max(1500, left - (Date.now() - t0)); } };
    el.addEventListener("mouseenter", hold); el.addEventListener("focusin", hold);
    el.addEventListener("mouseleave", () => { if (!tm && !el.contains(document.activeElement)) arm(); });
    el.addEventListener("focusout", () => { if (!tm && !el.matches(":hover")) arm(); });
    arm(); BAR[id].tm = () => tm && clearTimeout(tm);
  }
  if (spec.kind === "bad" || spec.kind === "warn") announce(spec.title + ". " + (spec.detail || ""));
}
function clearBar(id, quiet) { const b = BAR[id]; if (b) { if (b.tm) b.tm(); b.el.remove(); delete BAR[id]; } }

const ACTIONS = {
  retry: e => { const n = (e && e.name) || (NXS.st && NXS.st.settings.last_region); NXS.st.error = null; clearBar("error"); api("dismiss_error", {}); if (n) api("connect", { name: n }); },
  check_endpoint: e => { api("endpoint_check", { name: e && e.name }).then(r => { if (!r.ok) toast(r.error); else toast(t("Checking endpoint…"), true); }); },
  install_wg: () => api("install_wireguard", {}).then(r => toast(r.ok ? t("Installing WireGuard…") : r.error, !!r.ok)),
  elevate: () => api("elevate", {}).then(r => { if (!r.ok) toast(r.error); }),
  edit_config: e => { if (e && e.name) openEditor(e.name); },
  panic: () => panic(),
  open_portal: () => api("open_url", { key: "portal" }),
  show_log: () => $("#loglist").classList.add("o"),
  dismiss: () => { if (NXS.st) NXS.st.error = null; api("dismiss_error", {}); updateBanners(NXS.st); },
};
function panic() {
  if (!confirm(t("Remove all NOBAD firewall rules and stop NOBAD tunnels? Your internet will work normally afterwards."))) return;
  api("panic_reset", {}).then(() => toast(t("Restoring internet…"), true));
}
// Engine errors arrive in English; known codes are rebuilt from translatable templates.
const ERR_TITLES = {
  handshake: "{name} never completed a handshake", start_failed: "Couldn't start {name}",
  bad_config: "Can't read the config for {name}", dns_endpoint: "Can't find the server address for {name}",
  wg_missing: "WireGuard for Windows isn't installed", not_admin: "NOBAD needs administrator rights",
  captive: "Wi-Fi sign-in required", reconnect_failed: "Couldn't reconnect",
};
const ERR_DETAILS = {
  handshake: "Check the keys and the endpoint address/port.",
  wg_missing: "NOBAD drives the official WireGuard service. Install it, then try again.",
  not_admin: "Creating tunnels and firewall rules requires elevation.",
  captive: "This network is intercepting traffic. Kill switch is paused so you can sign in; NOBAD reconnects automatically afterwards.",
};
function trDetail(d) {  // details may be "a · b · c": translate each known part
  return String(d || "").split(" · ").map(p => t(p)).join(" · ");
}
// A failed attempt is news, not a state: it closes itself. Setup problems (WireGuard, admin, config) stay until fixed or closed.
const ERR_TRANSIENT = new Set(["handshake", "start_failed", "dns_endpoint", "reconnect_failed"]);
function errSpec(err) {
  const title = ERR_TITLES[err.code] ? t(ERR_TITLES[err.code], { name: err.name || "" }) : t(err.title);
  const detail = ERR_DETAILS[err.code] && err.detail === ERR_DETAILS[err.code] ? t(ERR_DETAILS[err.code]) : trDetail(err.detail);
  const transient = ERR_TRANSIENT.has(err.code);
  return { kind: err.code === "captive" ? "warn" : "bad", title, detail, close: ACTIONS.dismiss, at: err.ts || 0,
    ttl: transient ? 15000 : 0, expire: transient ? ACTIONS.dismiss : null,
    actions: (err.actions || []).map(a => ({ label: t(a.label), fn: () => ACTIONS[a.id] && ACTIONS[a.id](err) })) };
}
function updateBanners(st) {
  if (!st) return;
  if (st.error) setBar("error", errSpec(st.error)); else clearBar("error");
  if (st.fw_off && (st.settings.kill_switch || st.settings.dns_leak_block)) setBar("fwoff", { kind: "bad", title: t("Protection not enforced"),
    detail: t("Windows Firewall is off, so the kill switch can't block traffic."),
    actions: [{ label: t("Turn on Windows Firewall"), fn: () => api("open_url", { key: "firewall_settings" }) }] }); else clearBar("fwoff");
  if (st.wireguard === false && st.wg_installing) setBar("wg", { kind: "info", title: t("Installing WireGuard…"), detail: t("NOBAD needs the official WireGuard service. This takes about a minute; no action needed.") });
  else if (st.wireguard === false) setBar("wg", { kind: "warn", title: t("WireGuard for Windows isn't installed"), detail: t("NOBAD needs the official WireGuard service to create tunnels."),
    actions: [{ label: t("Install WireGuard"), fn: ACTIONS.install_wg }, { label: t("Open setup"), fn: () => wizardOpen() }] }); else clearBar("wg");
  if (st.ks_active && !st.connected && !st.connecting) setBar("ksblock", { kind: "warn", title: t("Kill switch is blocking your internet"),
    detail: t("You're not connected, so non-VPN traffic is blocked. Reconnect, or restore normal internet."),
    actions: [{ label: t("Restore internet"), fn: panic, cls: "pri" }] }); else clearBar("ksblock");
  const u = st.update;
  if (u && u.available && !NXS.dismissed.update) setBar("update", { kind: "info", title: t("Update available: {v}", { v: u.version }), detail: u.notes || "",
    actions: [{ label: t("Install now"), fn: () => api("update_install", {}) }, { label: t("Later"), fn: () => { NXS.dismissed.update = 1; clearBar("update"); } }] }); else clearBar("update");
  if (st.crash_pending > 0 && !NXS.dismissed.crash) setBar("crash", { kind: "info", title: t("NOBAD closed unexpectedly last time"),
    detail: t("A crash report was saved on this PC. Nothing is sent unless you choose to."),
    actions: [{ label: t("Review report"), fn: crashReview }, { label: t("Dismiss"), fn: () => { NXS.dismissed.crash = 1; clearBar("crash"); } }] }); else clearBar("crash");
}

/* ============================== config editor / import ============================== */
function renderVal(ul, r) {
  const li = [];
  (r.errors || []).forEach(e => li.push(`<li class="e">✕ ${esc(e)}</li>`));
  (r.warnings || []).forEach(e => li.push(`<li class="w">⚠ ${esc(e)}</li>`));
  if (!li.length) li.push(`<li class="g">✓ ${esc(t("Config looks valid"))}</li>`);
  ul.innerHTML = li.join("");
}
async function openEditor(name, prefill) {
  const creating = !name; let text = prefill || "", meta = null;
  if (!creating) { const r = await api("config_get", { name }); if (!r.ok) { toast(r.error); return; } text = r.text; meta = r; }
  const m = modal({ wide: true, title: creating ? t("Paste a config") : t("Edit {name}", { name }),
    sub: creating ? t("Paste the contents of a WireGuard .conf file.") : t("Private and preshared keys are hidden here and kept exactly as they are unless you replace them.") + (meta && meta.encrypted ? " " + t("Stored encrypted (Windows DPAPI).") : ""),
    html: (creating ? `<label class="nx-field"><span>${esc(t("Name"))}</span><input type="text" id="nxName" maxlength="32" placeholder="Home-Mumbai"></label>` : "") +
      `<label class="nx-sr" for="nxText">${esc(t("Config text"))}</label><textarea id="nxText" spellcheck="false" aria-describedby="nxVal"></textarea><ul class="nx-val" id="nxVal" aria-live="polite"></ul>`,
    actions: [
      ...(creating ? [] : [{ label: t("Delete"), cls: "danger", left: true, fn: async x => { if (!confirm(t("Delete {name}? This can't be undone.", { name }))) return; const r = await api("config_delete", { name }); if (r.ok) { toast(t("Deleted"), true); x.close(); } else toast(r.error); } }]),
      { label: t("Cancel"), fn: x => x.close() },
      { label: t("Save"), cls: "pri", id: "save", fn: async x => {
        const body = x.box.querySelector("#nxText").value;
        const r = creating ? await api("import", { name: x.box.querySelector("#nxName").value, content: body }) : await api("config_save", { name, text: body });
        if (!r.ok) { toast(r.error || t("Could not save")); return; }
        toast(r.note || t("Saved"), true); x.close(); } }] });
  const ta = m.box.querySelector("#nxText"), ul = m.box.querySelector("#nxVal"); ta.value = text;
  let timer = 0;
  const check = async () => { const r = await api("config_validate", { name: creating ? "" : name, text: ta.value }); if (!r.ok) return; renderVal(ul, r); m.buttons.save.disabled = !r.valid; translate(ul); };
  ta.oninput = () => { clearTimeout(timer); timer = setTimeout(check, 300); };
  check();
}
let qrLoading = null;
function loadQR() {
  if (window.jsQR) return Promise.resolve();
  if (!qrLoading) qrLoading = new Promise((res, rej) => { const s = document.createElement("script"); s.src = "/static/vendor/jsqr.js"; s.onload = res; s.onerror = () => rej(new Error("QR decoder failed to load")); document.head.appendChild(s); });
  return qrLoading;
}
async function decodeQR(file) {
  await loadQR();
  const bmp = await createImageBitmap(file);
  for (const max of [1600, 900, 500]) {
    const sc = Math.min(1, max / Math.max(bmp.width, bmp.height)), w = Math.round(bmp.width * sc), h = Math.round(bmp.height * sc);
    const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
    const c = cv.getContext("2d"); c.drawImage(bmp, 0, 0, w, h);
    const q = window.jsQR(c.getImageData(0, 0, w, h).data, w, h, { inversionAttempts: "attemptBoth" });
    if (q && q.data) return q.data;
  }
  return null;
}
async function importFiles(files) {
  const ok = [], bad = [];
  for (const f of files) {
    try {
      if (f.type && f.type.startsWith("image/")) {
        const txt = await decodeQR(f);
        if (!txt) { bad.push(f.name + ": " + t("no QR code found")); continue; }
        const name = await askText(t("Name this server"), t("Name"), (f.name.replace(/\.[^.]+$/, "") || "QR-import").slice(0, 32));
        if (!name) continue;
        const r = await api("import", { name, content: txt, untrusted: true });
        r.ok ? ok.push(r.name) : bad.push(name + ": " + r.error);
      } else {
        const r = await api("import", { name: f.name, content: await f.text() });
        r.ok ? ok.push(r.name) : bad.push(f.name + ": " + r.error);
      }
    } catch (e) { bad.push(f.name + ": " + (e.message || e)); }
  }
  if (ok.length) toast(t("Imported {n}: {names}", { n: ok.length, names: ok.join(", ") }) + (bad.length ? " · " + t("{n} failed", { n: bad.length }) : ""), true);
  if (bad.length) { if (!ok.length) toast(bad[0]); bad.forEach(b => console.warn("import:", b)); }
  return { ok, bad };
}
async function importUrl() {
  const url = await askText(t("Import from URL"), t("HTTPS link to a .conf file"), "", "https://");
  if (!url) return;
  const r = await api("import_url", { url });
  toast(r.ok ? t("Imported {n}: {names}", { n: 1, names: r.name }) : r.error, !!r.ok);
}
function serversTools() {
  const row = $("#bRescan").parentNode;
  const mk = (id, label, fn) => { const b = document.createElement("button"); b.className = "sm"; b.id = id; b.textContent = label; b.onclick = fn; row.appendChild(b); };
  mk("nxBtnUrl", t("Import from URL"), importUrl);
  mk("nxBtnQr", t("Import QR image"), () => { const i = document.createElement("input"); i.type = "file"; i.accept = "image/*"; i.onchange = () => importFiles([...i.files]); i.click(); });
  mk("nxBtnPaste", t("Paste config"), () => openEditor(null));
  mk("nxBtnSmart", t("Smart pick"), () => api("smart", {}).then(r => { if (!r.ok) toast(r.error); }));
  $("#file").onchange = async e => { const fs = [...e.target.files]; e.target.value = ""; if (fs.length) importFiles(fs); };
  $("#srv").addEventListener("click", e => { const b = e.target.closest("[data-edit]"); if (b) openEditor(b.dataset.edit); });
  const t2 = $("#t2");
  ["dragenter", "dragover"].forEach(ev => t2.addEventListener(ev, e => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { e.preventDefault(); t2.style.outline = "2px dashed var(--cy)"; } }));
  ["dragleave", "drop"].forEach(ev => t2.addEventListener(ev, () => { t2.style.outline = ""; }));
  t2.addEventListener("drop", e => { if (e.dataTransfer && e.dataTransfer.files.length) { e.preventDefault(); importFiles([...e.dataTransfer.files]); } });
  document.addEventListener("paste", e => {
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || !$("#t2").classList.contains("a")) return;
    const img = [...(e.clipboardData ? e.clipboardData.files : [])].find(f => f.type.startsWith("image/"));
    if (img) { e.preventDefault(); importFiles([img]); return; }
    const txt = e.clipboardData && e.clipboardData.getData("text");
    if (txt && /\[Interface\]/i.test(txt)) { e.preventDefault(); openEditor(null, txt); }
  });
}

/* ============================== usage history ============================== */
const U = { days: 30, more: false, data: null, loading: false };
function usageInit() {
  const card = document.createElement("div"); card.className = "card"; card.id = "nxUsage";
  card.innerHTML = `<div class="h">Usage history</div>
  <div class="nx-urow"><label class="nx-sr" for="nxuRange">Range</label><select id="nxuRange" class="nx-in"><option value="7">Last 7 days</option><option value="30" selected>Last 30 days</option><option value="0">All time</option></select><button class="sm" id="nxuRefresh">Refresh</button></div>
  <div id="nxuBody"></div>`;
  $("#t4").appendChild(card);
  $("#nxuRange").onchange = e => { U.days = +e.target.value; usageLoad(); };
  $("#nxuRefresh").onclick = () => usageLoad();
  $$("#dock [data-tab]").forEach(b => b.addEventListener("click", () => { if (b.dataset.tab === "t4" && Date.now() - NXS.usageAt > 4000) usageLoad(); }));
}
async function usageLoad() {
  if (U.loading) return; U.loading = true; NXS.usageAt = Date.now();
  const body = $("#nxuBody"); body.setAttribute("aria-busy", "true");
  if (!U.data) body.innerHTML = skel(2, "tall") + skel(3);
  const r = await api("usage", { days: U.days });
  U.loading = false; body.removeAttribute("aria-busy");
  if (!r || !r.ok) { body.innerHTML = `<div class="note">${esc(t("Usage history is unavailable."))}</div>`; return; }
  U.data = r; usageRender();
}
function bucketDaily(daily, maxBars) {
  if (daily.length <= maxBars) return daily.map(d => ({ label: d.day, rx: d.rx, tx: d.tx }));
  const per = Math.ceil(daily.length / maxBars), out = [];
  for (let i = 0; i < daily.length; i += per) { const s = daily.slice(i, i + per); out.push({ label: s[0].day, rx: s.reduce((a, d) => a + d.rx, 0), tx: s.reduce((a, d) => a + d.tx, 0) }); }
  return out;
}
function usageRender() {
  const r = U.data, tot = r.totals, body = $("#nxuBody");
  const dur2 = typeof dur === "function" ? dur : (n => n + "s");
  const sp = r.speed || [], best = sp.length ? Math.max(...sp.map(x => x.mbps)) : null, avg = sp.length ? sp.reduce((a, x) => a + x.mbps, 0) / sp.length : null;
  const sess = (r.sessions || []).slice(0, U.more ? 100 : 8);
  body.innerHTML = `<div class="grid"><div class="m"><small>Downloaded</small><span>${esc(fmtBytes(tot.rx))}</span></div><div class="m"><small>Uploaded</small><span>${esc(fmtBytes(tot.tx))}</span></div><div class="m"><small>Time connected</small><span>${esc(dur2(tot.secs))}</span></div></div>
  <canvas id="nxuChart" role="img" aria-label="${esc(t("Daily data usage chart"))}"></canvas>
  <div class="nx-legend"><span><i style="background:#f65000"></i>${esc(t("Download"))}</span><span><i style="background:#a9aab2"></i>${esc(t("Upload"))}</span></div>
  <details class="nx-ulist"><summary>${esc(t("Data table"))}</summary><div class="nx-sr-table" style="overflow:auto;max-height:200px">${(r.daily || []).slice(-60).reverse().map(d => `<div class="kvr"><span>${esc(d.day)}</span><b>↓ ${esc(fmtBytes(d.rx))} · ↑ ${esc(fmtBytes(d.tx))}</b></div>`).join("") || `<div class="note">${esc(t("No data yet."))}</div>`}</div></details>
  <div class="h" style="margin-top:12px">${esc(t("By server"))}</div><div class="nx-ulist">${(r.servers || []).slice(0, 8).map(s => `<div class="kvr"><span>${esc(s.name)}</span><b>${esc(fmtBytes(s.rx + s.tx))} · ${s.sessions}×</b></div>`).join("") || `<div class="note">${esc(t("No data yet."))}</div>`}</div>
  <div class="h" style="margin-top:12px">${esc(t("Speed tests"))}</div>
  ${sp.length ? `<canvas id="nxuSpeed" role="img" aria-label="${esc(t("Speed test history"))}" style="height:60px"></canvas><div class="note">${esc(t("Latest {a} Mbps · best {b} · average {c}", { a: sp[sp.length - 1].mbps, b: best, c: avg.toFixed(1) }))}</div>` : `<div class="note">${esc(t("Run a speed test to start the history."))}</div>`}
  <div class="h" style="margin-top:12px">${esc(t("Sessions"))}</div>
  ${sess.map(x => `<div class="ses"><div class="a1"><div>${esc(x.name)}</div><div>${esc(typeof when === "function" ? when(x.start) : x.start)}</div></div><div class="a2"><b>${esc(dur2(x.secs))}</b>↓ ${esc(fmtBytes(x.rx))} · ↑ ${esc(fmtBytes(x.tx))}${x.peak_bps ? " · " + esc(t("peak")) + " " + esc(fmtRate(x.peak_bps)) : ""}</div></div>`).join("") || `<div class="note">${esc(t("No sessions yet."))}</div>`}
  ${(r.sessions || []).length > 8 ? `<button class="sm nx-more" id="nxuMore">${esc(U.more ? t("Show fewer") : t("Show more"))}</button>` : ""}`;
  translate(body);
  const more = $("#nxuMore"); if (more) more.onclick = () => { U.more = !U.more; usageRender(); };
  drawUsage(); drawSpeed(sp);
}
function cssv(n, d) { return (getComputedStyle(document.documentElement).getPropertyValue(n) || "").trim() || d; }
function drawUsage() {
  const cv = $("#nxuChart"); if (!cv || !U.data) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 3), w = cv.clientWidth, h = cv.clientHeight; if (!w) return;
  cv.width = w * dpr; cv.height = h * dpr; const c = cv.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
  const bars = bucketDaily(U.data.daily || [], 60), mu = cssv("--mu", "#8e9bb2");
  c.font = "10px " + (typeof FONTS === "string" ? FONTS : "sans-serif"); c.fillStyle = mu;
  if (!bars.length) { c.textAlign = "center"; c.fillText(t("No data yet."), w / 2, h / 2); return; }
  const mx = Math.max(1, ...bars.map(b => b.rx + b.tx)), bw = Math.max(2, (w - 8) / bars.length - 2), base = h - 14;
  bars.forEach((b, i) => {
    const x = 4 + i * ((w - 8) / bars.length), hr = (b.rx / mx) * (base - 14), ht = (b.tx / mx) * (base - 14);
    c.fillStyle = "#a9aab2"; c.fillRect(x, base - hr - ht, bw, ht); c.fillStyle = "#f65000"; c.fillRect(x, base - hr, bw, hr);
  });
  c.fillStyle = mu; c.textAlign = "left"; c.fillText(fmtBytes(mx), 4, 10); c.fillText(bars[0].label.slice(5), 4, h - 2);
  c.textAlign = "right"; c.fillText(bars[bars.length - 1].label.slice(5), w - 4, h - 2);
}
function drawSpeed(sp) {
  const cv = $("#nxuSpeed"); if (!cv || sp.length < 1) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 3), w = cv.clientWidth, h = cv.clientHeight; if (!w) return;
  cv.width = w * dpr; cv.height = h * dpr; const c = cv.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
  const v = sp.slice(-40).map(x => x.mbps), mx = Math.max(...v) * 1.15 || 1; c.strokeStyle = "#f65000"; c.lineWidth = 1.6; c.beginPath();
  v.forEach((m, i) => { const x = v.length === 1 ? w / 2 : 4 + i * (w - 8) / (v.length - 1), y = h - 4 - (m / mx) * (h - 8); i ? c.lineTo(x, y) : c.moveTo(x, y); }); c.stroke();
  v.forEach((m, i) => { const x = v.length === 1 ? w / 2 : 4 + i * (w - 8) / (v.length - 1), y = h - 4 - (m / mx) * (h - 8); c.fillStyle = "#f65000"; c.beginPath(); c.arc(x, y, 2, 0, 6.3); c.fill(); });
}

/* ============================== wizard ============================== */
let wiz = null;
function wizardOpen() {
  if (wiz && wiz.el.isConnected) return;
  wiz = modal({ title: t("Set up NOBAD"), wide: true, sub: t("NOBAD checks what it needs and offers a fix for anything missing."),
    html: `<div id="nxWiz"></div>`, onClose: () => { wiz = null; },
    actions: [{ label: t("Re-check"), fn: () => api("state").then(s => { if (s && s.regions) applyState(s); }) },
      { label: t("Finish"), cls: "pri", id: "done", fn: x => { api("wizard_done", {}); x.close(); } }] });
  updateWizard(NXS.st);
}
function updateWizard(st) {
  if (!wiz || !wiz.el.isConnected || !st) return;
  const box = $("#nxWiz"); if (!box) return;
  if (box.contains(document.activeElement) && document.activeElement.tagName !== "BODY" && box.dataset.sig === sigOf(st)) return;
  const item = (ok, title, desc, btns) => `<div class="nx-wiz-item ${ok ? "ok" : "todo"}"><i aria-hidden="true">${ok ? "✓" : "!"}</i><div class="t"><b>${esc(title)}</b><small>${esc(desc)}</small><div class="b">${btns || ""}</div></div><span class="nx-sr">${esc(ok ? t("Done") : t("Needs attention"))}</span></div>`;
  const B = (id, label) => `<button class="sm" data-w="${id}">${esc(label)}</button>`;
  const s = st.settings || {};
  const tog = (k, label) => `<label style="display:inline-flex;gap:8px;align-items:center;margin-right:14px"><span class="sw"><input type="checkbox" data-wt="${k}" ${s[k] ? "checked" : ""} aria-label="${esc(label)}"><i></i></span><span>${esc(label)}</span></label>`;
  box.innerHTML =
    item(st.wireguard, t("WireGuard for Windows"), st.wireguard ? t("Installed.") : t("Not found. NOBAD uses the official WireGuard service."), st.wireguard ? "" : B("install", t("Install WireGuard")) + B("download", t("Open download page"))) +
    item(st.admin, t("Administrator rights"), st.admin ? t("Running as administrator.") : t("Needed for tunnels and firewall rules."), st.admin ? "" : B("elevate", t("Relaunch as administrator"))) +
    item(st.regions.length > 0, t("A server config"), st.regions.length ? t("{n} server(s) found.", { n: st.regions.length }) : t("Import a WireGuard .conf from your provider."),
      B("files", t("Choose files…")) + B("url", t("From URL")) + B("qr", t("From QR image")) + B("paste", t("Paste")) + B("folder", t("Open folder"))) +
    item(true, t("Optional"), t("You can change these any time in Settings."), `<div style="display:flex;flex-wrap:wrap;gap:8px">${tog("kill_switch", t("Kill switch"))}${tog("dns_leak_block", t("DNS leak block"))}${tog("start_with_windows", t("Start with Windows"))}${st.tray ? tog("tray", t("Tray icon")) : ""}${tog("ip_lookup", t("Show my location and exit IP (uses ipinfo.io)"))}</div>`);
  box.dataset.sig = sigOf(st); translate(box);
  const done = wiz.buttons.done; if (done) done.textContent = (st.wireguard && st.admin && st.regions.length) ? t("Finish") : t("Skip for now");
}
const sigOf = st => JSON.stringify([st.wireguard, st.admin, st.regions.length, st.settings.kill_switch, st.settings.dns_leak_block, st.settings.start_with_windows, st.settings.tray, st.settings.ip_lookup]);
document.addEventListener("click", e => {
  const b = e.target.closest("[data-w]"); if (!b) return;
  const w = b.dataset.w;
  if (w === "install") ACTIONS.install_wg(); else if (w === "download") api("open_url", { key: "wireguard_install" });
  else if (w === "elevate") ACTIONS.elevate(); else if (w === "files") $("#file").click();
  else if (w === "url") importUrl(); else if (w === "paste") openEditor(null); else if (w === "folder") api("open_configs", {});
  else if (w === "qr") { const i = document.createElement("input"); i.type = "file"; i.accept = "image/*"; i.onchange = () => importFiles([...i.files]); i.click(); }
});
document.addEventListener("change", e => { const c = e.target.closest("[data-wt]"); if (c) api("settings", { key: c.dataset.wt, value: c.checked }).then(r => { if (!r.ok) toast(r.error); }); });

/* ============================== settings ============================== */
const SVC_OPTS = [["", "Off"], ["netflix", "Netflix"], ["youtube", "YouTube"], ["disney", "Disney+"], ["prime", "Prime Video"], ["spotify", "Spotify"], ["twitch", "Twitch"]];
const GROUPS = [
  { id: "protection", title: "Protection", rows: [
    { k: "kill_switch", n: "Kill switch", d: "Blocks any non-VPN traffic while connected and keeps blocking if the tunnel drops.", kw: "firewall leak block" },
    { k: "dns_leak_block", n: "DNS leak block", d: "While connected, DNS (ports 53 and 853) can only leave through the tunnel. Even a DNS server on your own router is blocked.", kw: "dns leak" },
    { k: "force_tunnel_dns", n: "Add a fallback DNS when a config has none", d: "Adds a DNS line to the temporary runtime copy so the DNS block doesn't break name lookups. Your .conf files are never edited.", kw: "dns" },
    { k: "fallback_dns", n: "Fallback DNS servers", d: "Comma-separated IP addresses.", type: "text", ph: "1.1.1.1, 1.0.0.1", kw: "dns" },
    { k: "ks_strict", n: "Strict kill switch", d: "Keep blocking even when a connection attempt fails. Use Restore internet to undo.", kw: "fail closed" },
    { k: "watchdog", n: "Crash watchdog", d: "A tiny helper restarts NOBAD if it crashes while the kill switch is armed.", kw: "crash restart" },
    { k: "watchdog_failopen", n: "Release the kill switch if NOBAD can't restart", d: "Off keeps you blocked (safest). On restores internet after three failed restarts.", kw: "fail open" },
    { act: "panic", n: "Restore internet now", d: "Panic reset: removes every NOBAD firewall rule and stops NOBAD tunnels.", label: "Panic reset", kw: "panic emergency reset" } ] },
  { id: "safety", title: "Network safety", rows: [
    { custom: "netsafety" },
    { act: "nr_quick", n: "Quick network repair", d: "Undoes every NOBAD change, then flushes DNS, clears the ARP cache and renews DHCP. Takes seconds; Wi-Fi may blink once.", label: "Repair", kw: "fix internet dns broken reset network offline" },
    { act: "nr_full", n: "Full network reset", d: "Quick repair plus a Winsock, TCP/IP (IPv4 and IPv6) and WinHTTP proxy reset. Needs a restart, and manually set IP addresses must be entered again.", label: "Reset…", kw: "winsock tcp ip reset broken offline" } ] },
  { id: "netintel", title: "Network Intelligence", rows: [
    { k: "ni_autofix", n: "Smart fix agent", d: "When a site is blocked by your network's DNS, switch this adapter's DNS to an independent resolver that returned the real address, verify that nothing else broke, and undo it automatically if something did. Also undone when you leave that network, and by any reset. Off: nothing changes unless you click Fix.", kw: "autofix blocked site dns agent" },
    { k: "ni_history", n: "Keep local diagnostic history", d: "Remembers what is normal for each network to spot changes. Stored only on this PC.", kw: "baseline history" },
    { k: "ni_reference_dns", n: "Independent resolvers to compare with", d: "Comma-separated IP addresses. At least two, so answers can be cross-checked.", type: "text", ph: "1.1.1.1, 8.8.8.8, 9.9.9.9", kw: "dns compare reference" } ] },
  { id: "connection", title: "Connection", rows: [
    { k: "auto_repair", n: "Auto-repair & failover", d: "Reconnects if the link degrades, then moves to a better server.", kw: "reconnect" },
    { k: "reconnect_on_network_change", n: "Reconnect after sleep or network changes", d: "Cleanly reconnects after the laptop wakes up or you switch between Wi-Fi and Ethernet. The kill switch stays armed meanwhile.", kw: "sleep resume wifi ethernet" },
    { k: "stream_tuned", n: "Streaming-tuned tunnel", d: "MTU 1380 and keepalive 25 on a temporary copy. Your .conf files stay untouched.", kw: "mtu keepalive" },
    { k: "auto_connect", n: "Connect on launch", d: "Reconnects to the last server when NOBAD starts." },
    { k: "smart_select", n: "Smart server choice", d: "Learns which server is fastest at each time of day and uses that when failing over.", kw: "learn" },
    { k: "guard_service", n: "Watch a streaming service", d: "NOBAD checks this service through the tunnel and remembers which servers it works on.", type: "select", opts: SVC_OPTS, kw: "netflix streaming blocked" },
    { k: "guard_auto_switch", n: "Switch server if it gets blocked", d: "If the watched service stops working, move to a server that still works.", kw: "netflix" } ] },
  { id: "networks", title: "Trusted networks", rows: [
    { k: "ssid_rules", n: "Use trusted-network rules", d: "Connect automatically on networks you don't trust, disconnect on ones you do.", kw: "wifi ssid home" },
    { k: "autoconnect_untrusted", n: "Auto-connect on untrusted networks", d: "Applies when rules are on." },
    { k: "autodisconnect_trusted", n: "Auto-disconnect on trusted networks", d: "Applies when rules are on." },
    { custom: "trusted" } ] },
  { id: "startup", title: "Startup & tray", rows: [
    { k: "start_with_windows", n: "Start with Windows", d: "Runs at sign-in as an elevated scheduled task, so there is no UAC prompt each time.", kw: "autostart boot login" },
    { k: "tray", n: "Tray icon", d: "Quick connect, status and a compact window from the notification area.", kw: "system tray" },
    { k: "close_to_tray", n: "Closing the window keeps NOBAD in the tray", d: "Requires the tray icon.", kw: "minimize" },
    { k: "guardian", n: "Keep guarding after the window closes", d: "Stays in the background so auto-repair and the kill switch keep working." },
    { k: "notifications", n: "Windows notifications", d: "Toasts for connect, drop, failover and kill-switch events.", kw: "toast alerts" },
    { k: "visual_effects", n: "Visual effects", d: "Frosted glass and ambient animations. Off keeps NOBAD light on CPU, GPU and battery.", kw: "performance animation blur battery lag" },
    { k: "custom_titlebar", n: "NOBAD title bar", d: "NOBAD's own top bar with minimise, maximise and close. Off brings back the standard Windows title bar. Applies the next time NOBAD starts.", kw: "window title bar frame buttons" } ] },
  { id: "connectivity", title: "Connectivity", rows: [
    { k: "net_adapt", n: "Adapt to network blocks automatically", d: "If this network blocks a service NOBAD uses (by its name or through DNS), NOBAD switches to the service's official alternative name or looks it up with encrypted DNS, and remembers what works. Doesn't change Windows settings or your VPN traffic.", kw: "isp block dns doh alternative adapt auto" },
    { act: "reach_test", n: "Test connectivity", d: "Checks every service NOBAD uses on this network and shows which route works.", label: "Test", kw: "reachability blocked isp check" },
    { act: "reach_forget", n: "Re-learn routes", d: "Forget the routes NOBAD remembered (done automatically when you change networks).", label: "Reset", kw: "reset routes" } ] },
  { id: "privacy", title: "Privacy & security", rows: [
    { k: "ip_lookup", n: "Look up my exit IP address", d: "Sends your public IP to third-party services (ipinfo.io and fallbacks) to show where you appear to be. Off means no lookup at all.", kw: "ipinfo third party" },
    { k: "startup_checks", n: "Run extra checks at startup", d: "Also runs the speed test, streaming service checks and VALORANT region checks each time NOBAD starts. These contact third-party sites. A quick connectivity check always runs.", kw: "speed test valorant" },
    { k: "encrypt_configs", n: "Encrypt stored configs (Windows DPAPI)", d: "Stores .conf files encrypted. This protects copies, backups and a stolen disk, not other administrators on this PC.", kw: "dpapi keys" },
    { k: "crash_reporting", n: "Send crash reports (opt-in)", d: "Off by default. Reports are always saved locally; they're only sent if this is on and a server URL is set.", kw: "telemetry" },
    { k: "crash_report_url", n: "Crash report server", d: "HTTPS URL that receives reports.", type: "text", ph: "https://", kw: "telemetry" },
    { custom: "crash" },
    { act: "diag", n: "Export diagnostics", d: "Bundles logs, settings and network checks into a zip with private keys removed.", label: "Export…", kw: "logs support" } ] },
  { id: "updates", title: "Updates", rows: [
    { k: "auto_install_wg", n: "Reinstall WireGuard automatically", d: "If WireGuard for Windows goes missing, NOBAD installs the official, signature-checked copy at start-up (works offline).", kw: "wireguard install repair" },
    { k: "auto_update_check", n: "Check for updates on launch", d: "Needs an update URL below." },
    { k: "update_url", n: "Update manifest URL", d: "HTTPS link to the JSON manifest published with each release.", type: "text", ph: "https://", kw: "release" },
    { custom: "updates" } ] },
  { id: "help", title: "Help", rows: [
    { act: "wizard", n: "Setup checklist", d: "Re-run the first-run checks and fixes.", label: "Open setup", kw: "wizard onboarding" } ] },
];
let setBuilt = false;
const rowText = r => ((r.n || "") + " " + (r.d || "") + " " + (r.kw || "") + " " + (r.k || "") + " " +
  (r.n ? t(r.n) : "") + " " + (r.d ? t(r.d) : "")).toLowerCase();
function buildSettings() {
  const host = $("#tgs"); host.classList.add("nx-set"); host.setAttribute("role", "region"); host.setAttribute("aria-label", "Settings");
  let h = `<div class="h">Settings</div><label class="nx-sr" for="nxSetQ">Search settings</label><input type="search" id="nxSetQ" class="nx-in" placeholder="Search settings…" autocomplete="off">`;
  GROUPS.forEach(g => {
    h += `<details class="nx-grp" data-g="${g.id}" ${g.id === "protection" || g.id === "connection" ? "open" : ""}><summary>${esc(g.title)}</summary>`;
    g.rows.forEach((r, i) => {
      if (r.custom) { h += `<div class="nx-row nx-custom" data-custom="${r.custom}" data-text="${esc((g.title + " " + t(g.title)).toLowerCase() + " " + r.custom)}"></div>`; return; }
      const lid = "nxl-" + (r.k || r.act);
      let ctl;
      if (r.act) ctl = `<button class="sm" data-act="${r.act}">${esc(r.label)}</button>`;
      else if (r.type === "text") ctl = `<input class="nx-in" data-sv="${r.k}" aria-labelledby="${lid}" placeholder="${esc(r.ph || "")}" autocomplete="off" spellcheck="false">`;
      else if (r.type === "select") ctl = `<select class="nx-in" data-sv="${r.k}" aria-labelledby="${lid}">${r.opts.map(o => `<option value="${esc(o[0])}">${esc(o[1])}</option>`).join("")}</select>`;
      else ctl = `<label class="sw"><input type="checkbox" role="switch" data-s="${r.k}" aria-labelledby="${lid}"><i></i></label>`;
      h += `<div class="tg nx-row" data-k="${r.k || ""}" data-text="${esc(rowText(r))}"><div><b id="${lid}">${esc(r.n)}</b><small>${esc(r.d || "")}</small></div>${ctl}</div>`;
    });
    h += `</details>`;
  });
  h += `<div class="nx-empty" id="nxSetEmpty" hidden>No settings match your search.</div>`;
  host.innerHTML = h; translate(host);
  host.addEventListener("change", async e => {
    const el = e.target, k = el.dataset.s || el.dataset.sv; if (!k) return;
    const value = el.dataset.s ? el.checked : el.value;
    const r = await api("settings", { key: k, value });
    if (!r.ok) { toast(r.error || t("Could not save")); updateSettings(true); return; }
  });
  host.addEventListener("click", e => {
    const b = e.target.closest("[data-act]"); if (!b) return;
    const a = b.dataset.act;
    if (a === "panic") panic(); else if (a === "wizard") wizardOpen();
    else if (a === "diag") { b.disabled = true; api("diagnostics_export", {}).then(r => { b.disabled = false; toast(r.ok ? t("Collecting diagnostics…") : r.error, !!r.ok); }); }
    else if (a === "tadd") { const inp = $("#nxTAdd"); api("trusted_add", { name: b.dataset.name || (inp && inp.value) || "" }).then(r => { if (!r.ok) toast(r.error); else if (inp) inp.value = ""; }); }
    else if (a === "tdel") { const l = (S.settings.trusted_networks || []).filter(x => x !== b.dataset.name); api("settings", { key: "trusted_networks", value: l }); }
    else if (a === "ucheck") api("update_check", {}); else if (a === "uinstall") api("update_install", {});
    else if (a === "crashview") crashReview();
    else if (a === "reach_test") { b.disabled = true; b.textContent = t("Testing…"); api("reach_test", {}).then(r => { if (!r.ok) { b.disabled = false; b.textContent = t("Test"); toast(r.error); } }); }
    else if (a === "reach_forget") api("reach_forget", {}).then(r => toast(r.ok ? t("Routes will be re-learned.") : r.error, !!r.ok));
    else if (a === "nr_quick" || a === "nr_full") netRepair(a === "nr_full" ? "full" : "quick");
  });
  $("#nxSetQ").addEventListener("input", filterSettings);
  setBuilt = true;
}
function filterSettings() {
  const q = ($("#nxSetQ").value || "").trim().toLowerCase(), toks = q.split(/\s+/).filter(Boolean);
  let any = false;
  $$("#tgs .nx-grp").forEach(g => {
    let vis = 0; const title = g.querySelector("summary").textContent.toLowerCase();
    g.querySelectorAll(".nx-row").forEach(r => {
      const hay = (r.dataset.text || "") + " " + title, ok = toks.every(tk => hay.includes(tk));
      r.classList.toggle("nx-hide", !ok); if (ok) vis++;
    });
    g.classList.toggle("nx-hide", !vis); if (vis) any = true;
    if (toks.length) g.open = !!vis;
  });
  $("#nxSetEmpty").hidden = any || !toks.length;
  if (toks.length) announce(any ? "" : t("No settings match your search."));
}
function updateSettings(force) {
  if (!setBuilt || !NXS.st) return;
  const s = S.settings || {}, st = NXS.st;
  $$("#tgs [data-s]").forEach(el => { el.checked = !!s[el.dataset.s]; });
  $$("#tgs [data-sv]").forEach(el => { if (document.activeElement !== el || force) el.value = s[el.dataset.sv] == null ? "" : s[el.dataset.sv]; });
  ["tray", "close_to_tray"].forEach(k => { const el = $(`#tgs [data-s="${k}"]`); if (el) el.disabled = !st.tray; });
  const tr = $("#tgs [data-custom=trusted]");
  if (tr) {
    const list = s.trusted_networks || [], cur = st.network && st.network.name, pend = st.network && st.network.pending;
    const fps = s.trusted_fingerprints || {};
    const sig = JSON.stringify([list, cur, pend, Object.keys(fps)]);
    if (tr.dataset.sig !== sig || force) {
      tr.dataset.sig = sig;
      const warn = pend ? `<div class="net-issue warn" role="status"><b>${esc(t("\"{name}\" doesn't match the network you trusted", { name: pend.name }))}</b><p>${esc(t(pend.why))}. ${esc(t("NOBAD treats it as untrusted until you confirm it. Only confirm if you're sure this is your network."))}</p><button class="sm" data-act="tadd" data-name="${esc(pend.name)}">${esc(t("Confirm this network"))}</button></div>` : "";
      tr.innerHTML = `${warn}<div class="note">${esc(t("Current network"))}: <b>${esc(cur || t("none detected"))}</b></div><div class="nx-tags" role="list">${list.map(n => `<span class="nx-tag" role="listitem">${esc(n)}${fps[n] ? "" : ` <small class="note">(${esc(t("not confirmed"))})</small>`}<button class="sm" data-act="tdel" data-name="${esc(n)}" aria-label="${esc(t("Remove {name}", { name: n }))}">✕</button></span>`).join("") || `<span class="note">${esc(t("No trusted networks yet."))}</span>`}</div>
      <div class="nx-inline"><label class="nx-sr" for="nxTAdd">${esc(t("Network name"))}</label><input class="nx-in" id="nxTAdd" placeholder="${esc(t("Wi-Fi name, or Ethernet"))}" autocomplete="off"><button class="sm" data-act="tadd">${esc(t("Add"))}</button>${cur ? `<button class="sm" data-act="tadd" data-name="${esc(cur)}">${esc(t("Trust current network"))}</button>` : ""}</div>`;
      translate(tr);
    }
  }
  const up = $("#tgs [data-custom=updates]");
  if (up) {
    const u = st.update || {}; const sig = JSON.stringify(u);
    if (up.dataset.sig !== sig) {
      up.dataset.sig = sig;
      up.innerHTML = `<div class="note">${esc(t("Installed version"))}: <b>${esc(u.current || "")}</b>${u.checked ? " · " + esc(t("Latest")) + ": <b>" + esc(u.version || u.current || "") + "</b>" : ""}</div>
      ${u.error ? `<div class="note" style="color:var(--am)">${esc(u.error)}</div>` : ""}${u.busy ? `<div class="note">${esc(t("Downloading…"))} ${u.progress || 0}%</div>` : ""}
      <div class="nx-inline"><button class="sm" data-act="ucheck" ${u.configured ? "" : "disabled"}>${esc(t("Check now"))}</button>${u.available ? `<button class="sm pri" data-act="uinstall" ${u.busy ? "disabled" : ""}>${esc(t("Install {v}", { v: u.version }))}</button>` : ""}</div>`;
      translate(up);
    }
  }
  netSafetyRow();
  const cr = $("#tgs [data-custom=crash]");
  if (cr) { const n = st.crash_pending || 0; const sig = String(n);
    if (cr.dataset.sig !== sig) { cr.dataset.sig = sig; cr.innerHTML = n ? `<div class="nx-inline"><span class="note">${esc(t("{n} saved crash report(s)", { n }))}</span><button class="sm" data-act="crashview">${esc(t("Review"))}</button></div>` : ""; translate(cr); } }
}
/* ---------- network safety ---------- */
const NETS = { changes: null, last: null, busy: false };
function netSafetyRow() {
  const el = $("#tgs [data-custom=netsafety]"); if (!el) return;
  if (NETS.changes === null) { NETS.changes = []; api("net_changes", {}).then(r => { if (r.ok) { NETS.changes = r.changes; netSafetyRow(); } }); }
  const sig = JSON.stringify([NETS.changes, NETS.last, NETS.busy]); if (el.dataset.sig === sig) return; el.dataset.sig = sig;
  const ch = (NETS.changes || []).map(c => `<li>${esc(c.reason || c.kind)} <span class="note">· ${esc(new Date((c.ts || 0) * 1000).toLocaleString())}</span></li>`).join("");
  const last = NETS.last ? `<div class="note">${esc(t("Last repair"))}: <b>${esc(NETS.last.level)}</b> · ${NETS.last.steps.filter(x => x.ok).length}/${NETS.last.steps.length} ${esc(t("steps succeeded"))}${NETS.last.restart_needed ? " · " + esc(t("restart Windows to finish")) : ""}</div>` : "";
  el.innerHTML = `<div class="note">${esc(t("Works even when NOBAD is closed or you are offline: Start menu → NOBAD VPN → Restore internet. If Windows restarts after NOBAD was killed with the kill switch on, a boot guard restores your internet by itself."))}</div>
    <div class="note">${ch ? esc(t("Windows settings NOBAD changed (each is undone by any reset):")) + `<ul class="nx-list">${ch}</ul>` : esc(t("NOBAD has not changed any Windows network setting outside its own tunnel and firewall rules."))}</div>${last}${NETS.busy ? `<div class="note">${esc(t("Repairing…"))}</div>` : ""}`;
  translate(el);
}
function netRepair(level) {
  const msg = level === "undo"
    ? t("Restore internet: removes every NOBAD firewall rule, tunnel and DNS change, so Windows is back exactly as it was before NOBAD. Nothing else is touched. Continue?")
    : level === "full"
    ? t("Full network reset: removes every NOBAD change, then resets Winsock, TCP/IP and the WinHTTP proxy. Windows must restart afterwards, and manually set IP addresses must be entered again. Continue?")
    : t("Quick network repair: removes every NOBAD change, then flushes DNS, clears the ARP cache and renews DHCP. Your connection may blink once. Continue?");
  if (!confirm(msg)) return;
  api("net_repair", { level }).then(r => { if (!r.ok) toast(r.error); });
}
function reachReport(p) {
  const b = document.querySelector('[data-act="reach_test"]'); if (b) { b.disabled = false; b.textContent = t("Test"); }
  const label = s => s.status !== "ok" ? t("Blocked") : s.route === "alt" ? t("Alternative name") : s.route === "doh" ? t("Encrypted DNS") : t("Direct");
  const rows = (p.services || []).map(s => `<div class="pr ${s.status === "ok" ? "" : "bad"}"><i>${s.status === "ok" ? "✓" : "!"}</i>
      <span><b>${esc(t(s.label))}</b><br><small>${esc(t(s.explain))}${s.via ? " (" + esc(s.via) + ")" : ""}</small></span><b>${esc(label(s))}${s.status === "ok" ? " · " + esc(s.ms) + " ms" : ""}</b></div>`).join("");
  modal({ wide: true, title: t("Connectivity on this network"), sub: p.adapt ? t("Automatic adaptation is on: NOBAD uses whichever route works.") : t("Automatic adaptation is off: every request goes direct."),
    html: rows, actions: [{ label: t("Close"), fn: x => x.close() }] });
}
function netRepairDone(res) {
  NETS.busy = false; NETS.last = res; NETS.changes = null; netSafetyRow();
  const rows = res.steps.map(s => `<div class="pr ${s.ok ? "" : "bad"}"><i>${s.ok ? "✓" : "!"}</i><span>${esc(s.step)}</span><b>${esc(s.detail || "")}</b></div>`).join("");
  modal({ title: res.ok ? t("Network repaired") : t("Repair finished with problems"),
    sub: res.restart_needed ? t("Restart Windows to finish the reset.") : t("Each line is the real result of the command that ran."),
    html: rows, actions: [{ label: t("Close"), fn: x => x.close() }] });
}
async function crashReview() {
  const r = await api("crash_pending", {});
  if (!r.ok || !r.items.length) { toast(t("No crash reports."), true); return; }
  const m = modal({ wide: true, title: t("Crash reports"), sub: t("These contain the error, the app version, your Windows version and recent log lines. Private keys are removed. Folder paths and your user name are masked.") + (r.configured ? "" : " " + t("No crash-report server is set, so they can only be dismissed. Use Export diagnostics to share one manually.")), html: "<div id=\"nxCr\"></div>", actions: [{ label: t("Close"), fn: x => x.close() }] });
  const host = m.box.querySelector("#nxCr");
  r.items.forEach(it => {
    const d = document.createElement("div"); d.className = "nx-field";
    const head = document.createElement("b"); head.textContent = new Date((it.ts || 0) * 1000).toLocaleString() + " · " + it.where;
    const pre = document.createElement("pre"); pre.style.cssText = "max-height:180px;overflow:auto;font-size:11px;white-space:pre-wrap"; pre.textContent = it.traceback + "\n\n" + (it.log_tail || []).join("\n");
    const row = document.createElement("div"); row.className = "nx-inline";
    const send = document.createElement("button"); send.className = "sm"; send.textContent = t("Send report"); send.disabled = !r.configured;
    send.onclick = async () => { const x = await api("crash_send", { file: it.file }); toast(x.ok ? t("Report sent") : (x.error || x.message), !!x.ok); if (x.ok) d.remove(); };
    const dis = document.createElement("button"); dis.className = "sm"; dis.textContent = t("Dismiss"); dis.onclick = async () => { await api("crash_dismiss", { file: it.file }); d.remove(); };
    row.append(send, dis); d.append(head, pre, row); host.appendChild(d);
  });
}

/* ============================== accessibility, tabs, skeletons ============================== */
function a11yInit() {
  const live = document.createElement("div"); live.id = "nxlive"; live.className = "nx-sr"; live.setAttribute("aria-live", "polite"); live.setAttribute("role", "status"); document.body.appendChild(live);
  const skip = document.createElement("a"); skip.className = "nx-skip"; skip.href = "#hero"; skip.textContent = "Skip to controls";
  skip.onclick = e => { e.preventDefault(); const h = $("#hero"); h.setAttribute("tabindex", "-1"); h.focus(); }; document.body.insertBefore(skip, document.body.firstChild);
  // WebView2 moves focus to the first focusable element when the window opens; that is not a keyboard user, so
  // the skip link must not pop up then. It still appears on the first real Tab press.
  let keyUsed = false;
  document.addEventListener("keydown", () => { keyUsed = true; }, { capture: true, once: true });
  skip.addEventListener("focus", () => { if (!keyUsed) skip.blur(); });
  const toastEl = $("#toast"); toastEl.setAttribute("role", "status"); toastEl.setAttribute("aria-live", "polite");
  const orbit = $("#orbit"); if (orbit) { orbit.setAttribute("role", "img"); orbit.setAttribute("aria-label", "Map of your server locations. Use the Servers tab for a keyboard-accessible list."); }
  const pal = $("#pal"); if (pal) { pal.setAttribute("role", "dialog"); pal.setAttribute("aria-label", "Command palette"); }
  const adm = $("#adm"); adm.setAttribute("role", "button"); adm.tabIndex = 0; adm.title = "Relaunch as administrator";
  adm.onclick = () => ACTIONS.elevate(); adm.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ACTIONS.elevate(); } };
  const tabs = $$("#dock [data-tab]");
  tabs.forEach(b => { b.id = "nxtab-" + b.dataset.tab; b.setAttribute("aria-controls", b.dataset.tab); });
  $$(".tab").forEach(p => { p.setAttribute("role", "tabpanel"); p.setAttribute("aria-labelledby", "nxtab-" + p.id); });
  const rove = () => tabs.forEach(b => { b.tabIndex = b.classList.contains("a") ? 0 : -1; });
  rove();
  tabs.forEach(b => b.addEventListener("click", () => { setTimeout(rove, 0); if (!NXS.restoring) api("ui_state", { tab: b.dataset.tab }); }));
  $("#dock").addEventListener("keydown", e => {
    const i = tabs.indexOf(document.activeElement); if (i < 0) return;
    let n = -1; if (e.key === "ArrowRight") n = (i + 1) % tabs.length; else if (e.key === "ArrowLeft") n = (i - 1 + tabs.length) % tabs.length; else if (e.key === "Home") n = 0; else if (e.key === "End") n = tabs.length - 1;
    if (n >= 0) { e.preventDefault(); tabs[n].focus(); tabs[n].click(); }
  });
  $$("#hChips [data-k]").forEach(b => b.setAttribute("aria-pressed", "false"));
}
function skeletonHooks() {
  if (typeof svRender === "function") { const o = svRender; window.svRender = svRender = function () { o(); if (typeof SV !== "undefined" && SV._) { const el = $("#svs"); el.innerHTML = skel(5, "row"); el.setAttribute("aria-busy", "true"); } else $("#svs").removeAttribute("aria-busy"); }; }
  const sk = (btn, target, rows) => { const b = $(btn); if (b) b.addEventListener("click", () => setTimeout(() => { if (b.classList.contains("is-busy")) { $(target).innerHTML = skel(rows); $(target).setAttribute("aria-busy", "true"); } }, 0)); };
  sk("#bNetCheck", "#netResults", 4); sk("#bGameCheck", "#gameResults", 3);
}
function mainStateTweaks(st) {
  const ipv = $("#ipV"); if (ipv) ipv.classList.toggle("skel-text", !!(st.connected && !st.exit && st.settings.ip_lookup));
  if (st.exit && st.exit.disabled && ipv) { ipv.textContent = t("Lookup off"); const l = $("#ipL"); if (l) l.textContent = t("Turn on in Settings → Privacy"); }
  if (st.note && !st.connected) { const ss = $("#ss"); if (ss) ss.textContent = (st.connecting || "") + (st.connecting ? " · " : "") + st.note; }
  $$("#hChips [data-k]").forEach(b => b.setAttribute("aria-pressed", st.settings[b.dataset.k] ? "true" : "false"));
  const o = $("#orbit"); if (o) o.setAttribute("aria-label", t("Map of {n} server locations.", { n: st.regions.length }) + (st.connected ? " " + t("Connected to {name}.", { name: st.active }) : ""));
}
function restoreTab(st) {
  if (NXS.tabDone) return; NXS.tabDone = true;
  const tab = st.settings.last_tab, b = tab && document.querySelector('#dock [data-tab="' + tab + '"]');
  if (b && !b.classList.contains("a")) { NXS.restoring = true; b.click(); NXS.restoring = false; }
}

/* ============================== public hooks ============================== */
function onState(st) {
  NXS.st = st; S.dnsActive = st.dns_active;
  document.body.classList.toggle("fx", !!st.settings.visual_effects);
  const conn = st.connected ? "c" : st.connecting ? "w" : "d";
  if (NXS.prevConn !== null && conn !== NXS.prevConn) announce(conn === "c" ? t("Connected to {name}", { name: st.active }) : conn === "d" ? t("Disconnected") : t("Connecting…"));
  NXS.prevConn = conn;
  updateBanners(st); updateSettings(); updateWizard(st); mainStateTweaks(st); restoreTab(st); titlebar(st);
  if (!st.settings.wizard_done && !NXS.wizShown) { NXS.wizShown = true; wizardOpen(); }
}
function handle(type, p) {
  switch (type) {
    case "error_action": if (NXS.st) { NXS.st.error = p; updateBanners(NXS.st); } return true;
    case "notify": if (document.hasFocus()) toast(p.title + (p.msg ? " — " + p.msg : ""), p.level === "ok"); return true;
    case "endpoint_report": {
      const lines = [p.dns_ok ? t("Resolved to {ips}", { ips: (p.resolved || []).join(", ") }) : t("Name did not resolve"),
        p.icmp && p.icmp.rtt != null ? t("Ping {ms} ms", { ms: p.icmp.rtt }) : t("No ping reply"), p.tcp ? t("TCP {port} reachable", { port: p.tcp }) : t("TCP 443/80 not reachable")].concat(p.notes || []);
      setBar("endpoint", { kind: "info", title: t("Endpoint check: {h}", { h: p.host + ":" + p.port }), detail: lines.join(" · "), actions: [{ label: t("Dismiss"), fn: () => clearBar("endpoint") }] }); return true; }
    case "update": if (NXS.st) { NXS.st.update = p; updateBanners(NXS.st); updateSettings(); } return true;
    case "guard": if (p.blocked) toast(t("{svc} looks blocked on {srv}", { svc: p.service, srv: p.server })); return true;
    case "valorant_result": { const h = $("#valoRows .skel-hold"); if (h) h.remove(); return false; }
    case "valorant_start": setTimeout(() => { const v = $("#valoRows"); if (v) v.innerHTML = '<div class="skel-hold">' + skel(4, "row") + "</div>"; }, 0); return false;
    case "task_done": if (p.key === "network_diagnose" || p.key === "gaming") { const n = p.key === "gaming" ? $("#gameResults") : $("#netResults"); if (n) n.removeAttribute("aria-busy"); } return false;
    case "fix_result": announce(p.message || ""); return false;
    case "net_repair_start": NETS.busy = true; netSafetyRow(); toast(t("Repairing network…"), true); return true;
    case "net_repair_done": netRepairDone(p); return true;
    case "reach_report": reachReport(p); return true;
    default: return false;
  }
}
function patchProt() {
  if (typeof protHTML !== "function") return;
  const o = protHTML; window.protHTML = protHTML = function () { return o().replace("system DNS", S.dnsActive ? "fallback DNS, locked to tunnel" : "system DNS"); };
}
/* ============================== custom title bar (frameless main window) ============================== */
const TB = { on: false, max: false };
function titlebar(st) {
  if (TB.on || !st || !st.settings || !st.settings.custom_titlebar || document.body.dataset.view === "mini") return;
  const h = document.querySelector("header"); if (!h) return;
  TB.on = true; document.body.classList.add("tb");
  const ico = { min: '<svg viewBox="0 0 12 12"><path d="M1 6.5h10"/></svg>',
    max: '<svg viewBox="0 0 12 12"><rect x="1.5" y="1.5" width="9" height="9" rx="1"/></svg>',
    res: '<svg viewBox="0 0 12 12"><rect x="1.5" y="3.5" width="7" height="7" rx="1"/><path d="M3.5 3.5V2.5a1 1 0 0 1 1-1h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-1"/></svg>',
    close: '<svg viewBox="0 0 12 12"><path d="M2 2l8 8M10 2l-8 8"/></svg>' };
  const w = document.createElement("div"); w.className = "winctl"; w.setAttribute("role", "group"); w.setAttribute("aria-label", t("Window"));
  w.innerHTML = `<button type="button" data-w="minimize" title="${esc(t("Minimize"))}" aria-label="${esc(t("Minimize"))}">${ico.min}</button>
    <button type="button" data-w="maximize" title="${esc(t("Maximize"))}" aria-label="${esc(t("Maximize"))}">${ico.max}</button>
    <button type="button" data-w="close" class="x" title="${esc(t("Close"))}" aria-label="${esc(t("Close"))}">${ico.close}</button>`;
  h.appendChild(w);
  const setMax = m => { TB.max = !!m; document.body.classList.toggle("tb-max", TB.max); const b = w.querySelector('[data-w="maximize"]');
    b.innerHTML = TB.max ? ico.res : ico.max; b.title = t(TB.max ? "Restore" : "Maximize"); b.setAttribute("aria-label", b.title); };
  const win = (act, extra) => api("window", Object.assign({ do: act }, extra || {})).then(r => { if (r && r.ok && "maximized" in r) setMax(r.maximized); return r; });
  w.addEventListener("click", e => { const b = e.target.closest("[data-w]"); if (b) win(b.dataset.w); });
  // drag on empty title-bar space (not on buttons, inputs, links or pills); double-click maximises like Windows
  const interactive = el => el.closest("button,a,input,select,textarea,label,[role=button],.pill,.warn,#brand,.winctl");
  h.addEventListener("mousedown", e => { if (e.button === 0 && e.detail === 1 && !interactive(e.target)) win("drag"); });
  h.addEventListener("dblclick", e => { if (!interactive(e.target)) win("maximize"); });
  // invisible resize edges and corners
  ["t", "b", "l", "r", "tl", "tr", "bl", "br"].forEach(edge => {
    const g = document.createElement("div"); g.className = "rz rz-" + edge; g.setAttribute("aria-hidden", "true");
    g.addEventListener("mousedown", e => { if (e.button === 0 && !TB.max) { e.preventDefault(); win("resize", { edge }); } });
    document.body.appendChild(g);
  });
  win("state");
  addEventListener("resize", () => { clearTimeout(TB.rt); TB.rt = setTimeout(() => win("state"), 250); });
}

/* smooth theme switch: cross-fade old and new look (View Transitions API, Chromium/WebView2) */
function smoothTheme() {
  const orig = window.chooseTheme; if (typeof orig !== "function" || orig.__smooth) return;
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const wrapped = function (mode) {
    if (calm || !document.startViewTransition) return orig(mode);
    document.startViewTransition(() => { orig(mode); });
  };
  wrapped.__smooth = true; window.chooseTheme = wrapped;
}

function init() {
  a11yInit(); smoothTheme(); serversTools(); usageInit(); skeletonHooks(); patchProt(); buildSettings();
  window.addEventListener("resize", () => { drawUsage(); });
}
window.NX = { renderSettings() { updateSettings(); }, onState, handle, t, openEditor, importFiles, wizardOpen, netRepair, repairBusy: () => !!NETS.busy, modal, groups: GROUPS, panic };
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
