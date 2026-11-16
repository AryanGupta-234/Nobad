/* Evil Twin: trust grade of the network you're on (card at the top of the Network tab). Talks to /api/et_run and
   listens to et_report; everything shown is a measurement the backend just made. */
(function () {
  "use strict";
  const tr = s => (window.NX && NX.t ? NX.t(s) : s);
  const E = s => esc(s == null ? "" : String(s));
  const ET = { rep: null, busy: false, open: false };
  const ICON = { pass: "✓", warn: "!", fail: "✕", skip: "–" };
  const GRADE_NOTE = { A: "Looks safe", B: "Mostly safe", C: "Be careful", D: "Risky: use the VPN", F: "Under attack: use the VPN" };
  const ago = ts => { const s = Math.max(0, Math.round(Date.now() / 1000 - ts)); return s < 60 ? tr("just now") : s < 3600 ? Math.round(s / 60) + " min " + tr("ago") : Math.round(s / 3600) + " h " + tr("ago"); };

  function build() {
    const tab = $("#t5"); if (!tab || $("#etCard")) return;
    const c = document.createElement("div"); c.className = "card et-card"; c.id = "etCard";
    tab.insertBefore(c, tab.firstChild);
    c.addEventListener("click", e => {
      const b = e.target.closest("[data-et]"); if (!b) return;
      if (b.dataset.et === "run") run();
      else if (b.dataset.et === "more") { ET.open = !ET.open; render(); }
      else if (b.dataset.et === "vpn" && typeof mainAction === "function" && !S.connected) mainAction();
    });
    render();
  }
  function run() {
    if (ET.busy) return;
    ET.busy = true; render();
    api("et_run", {}).then(r => { if (!r.ok) { ET.busy = false; render(); toast(r.error || tr("Couldn't start the check")); } });
  }
  function render() {
    const c = $("#etCard"); if (!c) return;
    const r = ET.rep;
    const head = `<div class="et-head"><div><div class="h">${E(tr("Evil Twin · network trust check"))}</div>
      <div class="note">${E(tr("Is this network what it claims to be? Checks DNS, the router, the Wi-Fi itself and HTTPS in about 10 seconds."))}</div></div>
      <button class="sm" data-et="run" ${ET.busy ? "disabled" : ""}>${E(tr(ET.busy ? "Checking…" : r ? "Check again" : "Check now"))}</button></div>`;
    if (ET.busy && !r) { c.innerHTML = head + `<div class="ni-busy" role="status"><i></i>${E(tr("Checking DNS, the router, the Wi-Fi and HTTPS…"))}</div>`; return; }
    if (!r) { c.innerHTML = head + `<div class="empty-state">${E(tr(S.settings && S.settings.et_enabled === false ? "The automatic check is off (Settings → Network safety). Press Check now to grade this network." : "Runs by itself whenever you join a network. Press Check now to grade this one."))}</div>`; return; }
    if (!r.ok) { c.innerHTML = head + `<div class="net-issue warn"><b>${E(r.error)}</b></div>`; return; }
    const g = r.grade, cls = g === "A" || g === "B" ? "good" : g === "C" ? "warn" : "bad";
    const shown = ET.open ? r.checks : r.checks.filter(x => x.state === "fail" || x.state === "warn");
    const passed = r.checks.filter(x => x.state === "pass").length, total = r.checks.filter(x => x.state !== "skip").length;
    const thr = (S.settings && S.settings.et_vpn_below) || "C";
    let h = head + `<div class="et-grade et-${cls}"><div class="et-letter" aria-label="${E(tr("Grade"))} ${E(g)}">${E(g)}</div>
      <div class="et-gt"><b>${E(tr(GRADE_NOTE[g] || ""))}</b><span>${E(r.network)}${r.kind === "wifi" ? " · Wi-Fi" : r.kind === "wired" ? " · " + E(tr("wired")) : ""}${r.trusted ? " · " + E(tr("trusted")) : ""}</span>
      <small>${E(r.summary)}</small></div><div class="et-score"><b>${E(r.score)}</b><small>/100</small></div></div>`;
    if (r.action === "connected") h += `<div class="net-issue good"><b>${E(tr("NOBAD connected the VPN because this network graded below"))} ${E(thr)}.</b></div>`;
    else if ((g === "D" || g === "F") && !S.connected) h += `<div class="ni-rec"><p>${E(tr("Don't sign in to anything on this network without the VPN."))}</p><button class="pri sm" data-et="vpn">${E(tr("Connect NOBAD"))}</button></div>`;
    else if (r.vpn_connected) h += `<div class="note">${E(tr("NOBAD VPN is connected, so DNS and HTTPS checks were skipped: that traffic already goes through the tunnel."))}</div>`;
    h += shown.length ? `<div class="et-list">${shown.map(x => `<div class="et-row et-r-${E(x.state)}"><i>${ICON[x.state] || "?"}</i><div><b>${E(tr(x.title))}</b>${x.detail ? `<small>${E(x.detail)}</small>` : ""}${(x.evidence || []).length && x.state !== "pass" ? `<ul>${x.evidence.slice(0, 4).map(v => `<li><code>${E(v)}</code></li>`).join("")}</ul>` : ""}</div>${x.points && x.state !== "pass" && x.state !== "skip" ? `<em>−${E(x.points)}</em>` : ""}</div>`).join("")}</div>`
      : `<div class="net-issue good"><b>${E(tr("Every check passed"))}</b><p>${passed} / ${total} ${E(tr("checks passed"))}.</p></div>`;
    h += `<div class="et-foot"><button class="linkish" data-et="more">${E(tr(ET.open ? "Show problems only" : "Show all checks"))} (${r.checks.length})</button>
      <span class="note">${E(tr("Measured"))} ${ago(r.ts)} · ${E(r.took_s)} s · ${E(tr("VPN turns on below"))} ${E(thr === "off" ? tr("never") : thr)}</span></div>`;
    c.innerHTML = h;
  }
  function handle(type, p) {
    if (type === "et_report") { ET.rep = p; ET.busy = false; render(); return true; }
    if (type === "task_done" && p.key === "et_run" && ET.busy) { ET.busy = false; render(); if (p.error) toast(tr("The check stopped") + ": " + p.error); }
    return false;
  }
  function init() {
    build();
    const prev = NX.handle; NX.handle = (t, p) => handle(t, p) || prev(t, p);
    const prevState = NX.onState; NX.onState = st => { prevState(st); if (st && st.eviltwin && (!ET.rep || st.eviltwin.ts > ET.rep.ts)) { ET.rep = st.eviltwin; render(); } };
  }
  if (window.NX) init(); else addEventListener("load", init);
})();
