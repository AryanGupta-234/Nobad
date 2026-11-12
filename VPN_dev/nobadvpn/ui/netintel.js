/* Network Intelligence section (tab #t6). Self-contained: talks to /api/ni_* and listens to ni_* events.
   Everything shown comes from a measurement the backend just made; nothing is computed or guessed here. */
(function () {
  "use strict";
  const tr = s => (window.NX && NX.t ? NX.t(s) : s);
  const E = s => esc(s == null ? "" : String(s));
  const PANES = [["overview", "Overview"], ["sites", "Sites"], ["dns", "DNS"], ["ip", "IPv4 / IPv6"], ["vpn", "VPN"], ["history", "History"]];
  const NI = { pane: "overview", ov: null, inv: null, fix: null, lookup: null, vpn: null, hist: null, busy: {} };
  const sev = s => (s === "bad" ? "bad" : s === "warn" ? "warn" : "good");
  const conf = f => `<span class="ni-conf ni-${E(f.confidence_label)}" title="${E(tr("Confidence"))} ${Math.round((f.confidence || 0) * 100)}%">${E(tr(f.confidence_label || ""))} · ${Math.round((f.confidence || 0) * 100)}%</span>`;
  const ago = ts => { const s = Math.max(0, Math.round(Date.now() / 1000 - ts)); return s < 60 ? s + " s" : s < 3600 ? Math.round(s / 60) + " min" : Math.round(s / 3600) + " h"; };

  function finding(f) {
    const ev = (f.evidence || []).map(e => `<li>${E(e)}</li>`).join("");
    const rec = (f.recommend || []).map(r => `<p class="next">${E(r)}</p>`).join("");
    const contra = (f.contra || []).map(c => `<li class="ni-contra">${E(c)}</li>`).join("");
    return `<div class="net-issue ${sev(f.severity)}"><div class="ni-ft"><b>${E(f.title)}</b>${f.severity === "info" ? "" : conf(f)}</div>
      ${f.layer ? `<span class="ni-layer">${E(f.layer)}</span>` : ""}${ev || contra ? `<ul class="ni-ev">${ev}${contra}</ul>` : ""}${f.note ? `<p>${E(f.note)}</p>` : ""}${rec}</div>`;
  }
  const empty = t => `<div class="empty-state">${E(tr(t))}</div>`;
  const busy = k => NI.busy[k] ? `<div class="ni-busy" role="status"><i></i>${E(tr("Measuring…"))}</div>` : "";

  function buildShell() {
    const seg = $("#niSeg"); if (!seg || seg.dataset.ok) return; seg.dataset.ok = "1";
    seg.innerHTML = PANES.map(([k, n]) => `<button role="tab" data-ni="${k}" class="${k === NI.pane ? "a" : ""}" aria-selected="${k === NI.pane}">${E(tr(n))}</button>`).join("");
    seg.addEventListener("click", e => { const b = e.target.closest("[data-ni]"); if (!b) return; NI.pane = b.dataset.ni;
      $$("#niSeg [data-ni]").forEach(x => { x.classList.toggle("a", x === b); x.setAttribute("aria-selected", x === b); }); render();
      if (NI.pane === "history") loadHistory(); });
    $("#niBody").addEventListener("click", onClick);
    $("#niBody").addEventListener("keydown", e => { if (e.key === "Enter" && e.target.id === "niSite") go("investigate"); if (e.key === "Enter" && e.target.id === "niName") go("lookup"); });
  }

  /* ------------------------------------------------------------------ panes */
  // Everything the command line can do (--panic, --repair-network quick|full), as buttons: users never need a terminal.
  function repairCard() {
    const busy = window.NX && NX.repairBusy && NX.repairBusy(), dis = busy ? "disabled" : "";
    const row = (lvl, title, text, label, cls) => `<div class="ni-fixrow"><div><b>${E(tr(title))}</b><p>${E(tr(text))}</p></div>
      <button class="sm${cls ? " " + cls : ""}" data-go="repair" data-level="${lvl}" ${dis}>${E(tr(label))}</button></div>`;
    return `<div class="card ni-fixcard"><div class="h">${E(tr("Fix my internet"))}</div>
      <div class="note">${E(tr("Works without internet. Start with the first option; each one asks before it changes anything and shows the real result of every step."))}</div>
      ${row("undo", "1 · Restore internet", "Removes NOBAD's firewall rules, tunnels and DNS changes. Use this if pages stopped loading after using NOBAD.", "Restore", "pri")}
      ${row("quick", "2 · Quick repair", "Also flushes DNS, clears the ARP cache and renews your IP address. Takes seconds; Wi-Fi may blink once.", "Repair")}
      ${row("full", "3 · Full network reset", "Also resets Winsock, TCP/IP and proxy settings, like Windows' own network reset. Needs a restart; manually set IP addresses must be entered again.", "Reset…", "danger")}
      ${busy ? `<div class="note">${E(tr("Repairing network…"))}</div>` : ""}</div>`;
  }
  function paneOverview() { return paneOverviewMain() + repairCard(); }
  function paneOverviewMain() {
    const o = NI.ov;
    let h = `<div class="card"><div class="ni-row"><div><div class="h">${E(tr("Network overview"))}</div><div class="note">${E(tr("Adapters, gateway, DNS health, interception and changes since this network was last seen."))}</div></div>
      <button class="pri shiny-cta" data-go="overview" ${NI.busy.overview ? "disabled" : ""}>${E(tr(o ? "Analyze again" : "Analyze network"))}</button></div>${busy("overview")}`;
    if (!o) return h + empty("Run an analysis to see your network.") + "</div>";
    if (!o.ok) return h + `<div class="net-issue bad"><b>${E(o.error)}</b></div></div>`;
    const s = o.snapshot, p = (s.adapters || []).find(a => a.index === s.primary);
    const bl = o.baseline || {};
    h += `<div class="net-metrics"><div class="m"><small>${E(tr("Uplink"))}</small><span>${E(p ? p.name : tr("none"))}</span></div>
      <div class="m"><small>IPv4 / IPv6</small><span>${s.v4_available ? "✓" : "✕"} / ${s.v6_available ? "✓" : "✕"}</span></div>
      <div class="m"><small>${E(tr("This network"))}</small><span>${bl.known ? E(tr("seen")) + " " + bl.seen + "×" : E(tr("new"))}</span></div></div>`;
    if (p) h += `<div class="kvr"><span>${E(tr("Gateway"))}</span><b>${E((p.gateways4 || []).join(", ") || "—")}</b></div>
      <div class="kvr"><span>${E(tr("Windows DNS"))}</span><b>${E([].concat(p.dns4, p.dns6).join(", ") || "—")}</b></div>
      <div class="kvr"><span>${E(tr("Network's own DNS (DHCP)"))}</span><b>${E((p.dhcp_dns || []).join(", ") || "—")}</b></div>
      <div class="kvr"><span>${E(tr("Encrypted DNS templates in Windows"))}</span><b>${(s.doh_templates || []).length}</b></div>`;
    h += `<div class="ni-sub">${E(tr("Resolvers"))}</div>` + (o.resolvers || []).map(r => `<div class="ni-res"><span class="ni-g ni-g-${E(r.group)}">${E(tr(r.group))}</span><b>${E(r.ip)}</b>
      <span class="${r.ok ? "ni-ok" : "ni-bad"}">${r.ok ? E(r.rtt_ms) + " ms" : E(r.error || r.rcode || "no answer")}</span>${r.nx_hijack ? `<span class="ni-bad">${E(tr("invents answers"))}</span>` : ""}${r.in_use ? `<span class="ni-tag">${E(tr("in use"))}</span>` : ""}</div>`).join("");
    h += `<div class="ni-sub">${E(tr("Findings"))}</div>` + ((o.findings || []).length ? o.findings.map(finding).join("") :
      `<div class="net-issue good"><b>${E(tr("Nothing unusual found"))}</b><p>${E(tr("DNS answers normally, nothing intercepts DNS, and nothing changed since this network was last seen."))}</p></div>`);
    return h + `<div class="note ni-foot">${E(tr("Measured"))} ${ago(o.ts)} ${E(tr("ago"))} · ${E(o.took_s)} s</div></div>`;
  }

  function paneSites() {
    const auto = !!(S.settings && S.settings.ni_autofix);
    let h = `<div class="card"><div class="h">${E(tr("Investigate a site"))}</div><div class="note">${E(tr("Compares your network's DNS with independent and encrypted resolvers, then tests TCP, TLS and HTTP to find exactly where a site is blocked or failing."))}</div>
      <div class="ni-inline"><input class="nx-in" id="niSite" placeholder="${E(tr("site.com or https://site.com/page"))}" autocomplete="off" spellcheck="false" value="${E(NI.lastTarget || "")}"><button class="pri" data-go="investigate" ${NI.busy.investigate ? "disabled" : ""}>${E(tr("Investigate"))}</button></div>
      <label class="ni-agent"><span class="sw"><input type="checkbox" role="switch" id="niAuto" ${auto ? "checked" : ""}><i></i></span><span><b>${E(tr("Smart fix agent"))}</b><small>${E(tr(auto ? "On: fixes DNS filtering by itself, checks that nothing else broke, and undoes it automatically if something did." : "Off: nothing is changed unless you click Fix."))}</small></span></label>${busy("investigate")}`;
    const r = NI.inv;
    if (!r) return h + empty("Enter a site that doesn't open (or any site) to see what your network does with it.") + "</div>";
    if (!r.ok) return h + `<div class="net-issue bad"><b>${E(r.error)}</b></div></div>`;
    const V = { "dns-filtering": "Blocked by DNS", "sni-filtering": "Blocked by site name (SNI)", "ip-unreachable": "Real addresses unreachable",
      "dns-interception": "DNS intercepted", "http-451": "Unavailable for legal reasons", "resolver-failed": "Resolver failing", "resolver-error": "Resolver error",
      "os-resolution-failed": "Windows can't resolve it", "tls-failed": "TLS failing", "ipv6-path-broken": "IPv6 path broken", "dns-divergence": "DNS answers differ",
      "name-does-not-exist": "Name does not exist", "local-network": "No internet on this PC", ok: "Reachable, nothing filtered" };
    const top = (r.findings || []).filter(f => f.severity !== "info").sort((a, b) => b.confidence - a.confidence)[0];
    h += `<div class="ni-verdict ni-v-${r.verdict === "ok" || r.verdict === "name-does-not-exist" ? "good" : top ? sev(top.severity) : "warn"}"><small>${E(r.target)}</small><b>${E(tr(V[r.verdict] || r.verdict))}</b>
      ${r.affected === false && r.verdict === "dns-filtering" ? `<span>${E(tr("This PC isn't affected (Windows uses another resolver)."))}</span>` : r.affected ? `<span>${E(tr("Apps on this PC get the filtered answer."))}</span>` : ""}</div>`;
    h += (r.recommendations || []).map(x => `<div class="ni-rec"><p>${E(x.text)}</p>${x.action === "vpn" ? `<button class="sm" data-go="vpnconnect">${E(tr("Connect NOBAD"))}</button>` : ""}${x.action === "dns_fix" ? `<button class="sm pri" data-go="fix" ${r.fixable && !r.fixable.ok ? "disabled" : ""}>${E(tr("Fix DNS safely"))}</button>` : ""}</div>`).join("");
    if (r.fixable && !r.fixable.ok && (r.recommendations || []).some(x => x.action === "dns_fix")) h += `<div class="note">${E(tr("Fix not available"))}: ${E(r.fixable.reasons.join("; "))}</div>`;
    h += fixBox();
    h += `<div class="ni-sub">${E(tr("Evidence"))}</div>` + (r.findings || []).map(finding).join("") || "";
    const d = r.data || {};
    h += `<div class="ni-sub">${E(tr("What each resolver answered"))}</div><div class="ni-table" role="table">` + (d.matrix || []).map(m => {
      const a = m.results.A || {}, q = m.results.AAAA || {};
      const ans = a.rcode === "NOERROR" ? (a.cnames || []).map(c => `<code>→ ${E(c)}</code>`).join(" ") + " " + E((a.addrs || []).join(", ") || tr("no address")) : E(a.error || a.rcode);
      return `<div class="ni-tr" role="row"><span class="ni-g ni-g-${E(m.group)}">${E(tr(m.group))}</span><b>${E(m.ip || (m.doh || "").split("/")[2])}</b><span class="ni-ans">${ans}${q.addrs && q.addrs.length ? `<br><small>${E(q.addrs.join(", "))}</small>` : ""}</span><small>${a.rtt_ms != null ? E(a.rtt_ms) + " ms" : ""}</small></div>`;
    }).join("") + `</div>`;
    if (d.isp) h += `<div class="ni-sub">${E(tr("Who is doing it"))}</div><div class="note">${d.isp.matches && d.isp.matches.length ? E(tr("Evidence links the filtering to your provider")) + ": " + E(d.isp.provider_label) : E(d.isp.note || tr("Not enough evidence to name the operator."))}</div>`;
    return h + `<div class="note ni-foot">${E(tr("Measured"))} ${ago(r.ts)} ${E(tr("ago"))} · ${E(r.took_s)} s</div></div>`;
  }

  function fixBox() {
    const f = NI.fix; if (!f) return NI.busy.fix ? busy("fix") : "";
    const S2 = { applied: "Fixed", refused: "Not changed", rolled_back: "Undone automatically", failed: "Could not change", busy: "Busy", rolled_back_by_user: "Undone" };
    const checks = (f.checks || []).map(c => `<div class="pr ${c.ok ? "" : "bad"}"><i>${c.ok ? "✓" : "!"}</i><span>${E(c.check)}</span><b>${E(c.detail || "")}</b></div>`).join("");
    return `<div class="net-issue ${f.ok ? "good" : f.state === "refused" ? "warn" : "bad"}"><b>${E(tr(S2[f.state] || f.state))}${f.servers ? " · " + E(f.servers.join(", ")) + " " + E(tr("on")) + " " + E(f.adapter) : ""}</b>
      ${(f.reasons || []).map(x => `<p>${E(x)}</p>`).join("")}${checks}${f.ok && f.entry ? `<p class="next"><button class="sm" data-go="rollback" data-entry="${E(f.entry)}">${E(tr("Undo this change"))}</button></p>` : ""}</div>`;
  }

  function paneDns() {
    const types = ["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SOA"];
    let h = `<div class="card"><div class="h">${E(tr("DNS intelligence"))}</div><div class="note">${E(tr("Ask every resolver for any record type and compare the raw answers."))}</div>
      <div class="ni-inline"><input class="nx-in" id="niName" placeholder="example.com" autocomplete="off" spellcheck="false" value="${E(NI.lastName || "")}"><button class="pri" data-go="lookup" ${NI.busy.lookup ? "disabled" : ""}>${E(tr("Look up"))}</button></div>
      <div class="ni-types">${types.map(t => `<label><input type="checkbox" data-rt="${t}" ${(NI.types || ["A", "AAAA", "CNAME"]).includes(t) ? "checked" : ""}> ${t}</label>`).join("")}</div>${busy("lookup")}`;
    const L = NI.lookup; if (!L) return h + empty("Results appear here.") + "</div>";
    h += L.rows.map(row => `<div class="ni-sub">${E(row.label)} <span class="ni-g ni-g-${E(row.group)}">${E(tr(row.group))}</span></div>` + L.types.map(t => {
      const x = row.records[t];
      const body = x.error ? `<span class="ni-bad">${E(x.error)}</span>` : (x.answers.length ? x.answers.map(a => `<code>${E(a.type)} ${E(typeof a.data === "object" ? JSON.stringify(a.data) : a.data)}</code> <small>ttl ${E(a.ttl)}</small>`).join("<br>") : `<small>${E(x.rcode)}${x.authority.length ? " · SOA " + E((x.authority[0].data || {}).mname || "") : ""}</small>`);
      return `<div class="ni-tr"><b>${t}</b><span class="ni-ans">${body}</span><small>${x.rtt_ms != null ? E(x.rtt_ms) + " ms" : ""}</small></div>`;
    }).join("")).join("");
    return h + "</div>";
  }

  function paneIp() {
    const o = NI.ov;
    let h = `<div class="card"><div class="ni-row"><div><div class="h">${E(tr("IPv4 / IPv6 analysis"))}</div><div class="note">${E(tr("Addresses, routes and DNS per adapter, from the last network analysis."))}</div></div><button class="sm" data-go="overview" ${NI.busy.overview ? "disabled" : ""}>${E(tr("Analyze"))}</button></div>${busy("overview")}`;
    if (!o || !o.ok) return h + empty("Run a network analysis first.") + "</div>";
    const up = (o.snapshot.adapters || []).filter(a => (a.status || "").toLowerCase() === "up");
    h += up.map(a => `<div class="ni-ad"><div class="ni-row"><b>${E(a.name)}</b><span class="ni-tag">${E(tr(a.role))}</span>${a.index === o.snapshot.primary ? `<span class="ni-tag ni-ok">${E(tr("primary"))}</span>` : ""}</div>
      <small>${E(a.description)} · ${E(a.media || "")} ${E(a.speed || "")} · MTU ${E(a.mtu)}</small>
      <div class="kvr"><span>IPv4</span><b>${E(a.ipv4.map(x => x.ip + "/" + x.prefix + " (" + x.kind + ", " + x.origin + ")").join(", ") || "—")}</b></div>
      <div class="kvr"><span>IPv6</span><b>${E(a.ipv6.filter(x => x.kind !== "link-local").map(x => x.ip + " (" + x.kind + ", " + x.origin + ")").join(", ") || tr("link-local only"))}</b></div>
      <div class="kvr"><span>${E(tr("Default route"))}</span><b>v4 ${a.default4 ? "✓ " + E((a.gateways4 || []).join(", ") || "on-link") : "✕"} · v6 ${a.default6 ? "✓ " + E((a.gateways6 || []).join(", ") || "on-link") : "✕"}</b></div>
      <div class="kvr"><span>DNS</span><b>${E([].concat(a.dns4, a.dns6).join(", ") || "—")}</b></div></div>`).join("");
    const v6f = (o.findings || []).filter(f => f.layer === "ipv6" || f.layer === "routing");
    return h + v6f.map(finding).join("") + "</div>";
  }

  function paneVpn() {
    const v = NI.vpn;
    let h = `<div class="card"><div class="ni-row"><div><div class="h">${E(tr("VPN integrity"))}</div><div class="note">${E(tr("Checks that IPv4, IPv6 and DNS really go through the tunnel, and that nothing leaks around it."))}</div></div><button class="pri" data-go="vpn" ${NI.busy.vpn ? "disabled" : ""}>${E(tr("Check"))}</button></div>${busy("vpn")}`;
    if (!v) return h + empty(S.connected ? "Run the check while connected." : "Connect NOBAD, then run the check.") + "</div>";
    if (!v.ok) return h + `<div class="net-issue bad"><b>${E(v.error)}</b></div></div>`;
    if (v.connected) h += `<div class="net-metrics"><div class="m"><small>${E(tr("Tunnel"))}</small><span>${E(v.tunnel)}</span></div><div class="m"><small>${E(tr("Kill switch"))}</small><span>${v.kill_switch ? "✓" : "✕"}</span></div><div class="m"><small>${E(tr("DNS leak block"))}</small><span>${v.dns_block ? "✓" : "✕"}</span></div></div>`
      + (v.routes || []).map(c => `<div class="kvr"><span>${E(c.family)} → ${E(c.dest)}</span><b class="${c.tunnel ? "ni-ok" : "ni-bad"}">${E(c.via || tr("no route"))}</b></div>`).join("")
      + (v.leak_tests || []).map(t => `<div class="kvr"><span>${E(tr("Direct DNS to"))} ${E(t.resolver)}</span><b class="${t.answered ? "ni-bad" : "ni-ok"}">${E(t.answered ? tr("answered (leak path)") : tr("blocked"))}</b></div>`).join("");
    h += (v.findings || []).map(finding).join("");
    if (v.transitions && v.transitions.length) h += `<div class="ni-sub">${E(tr("Recent network transitions"))}</div>` + v.transitions.map(t => `<div class="kvr"><span>${E(new Date(t.ts * 1000).toLocaleTimeString())}</span><b>${E(t.kind)} · ${E(t.detail)}</b></div>`).join("");
    return h + "</div>";
  }

  function paneHistory() {
    const H = NI.hist;
    let h = `<div class="card"><div class="ni-row"><div><div class="h">${E(tr("Diagnostic history"))}</div><div class="note">${E(tr("Stored only on this PC. Networks are identified by a hash, never by name."))}</div></div><button class="sm" data-go="hclear">${E(tr("Clear"))}</button></div>`;
    if (!H) return h + empty("Loading…") + "</div>";
    if (!H.enabled) h += `<div class="note">${E(tr("History is off (Settings → Network Intelligence)."))}</div>`;
    if (!H.items.length) return h + empty("No diagnostics yet.") + "</div>";
    return h + H.items.map(x => `<div class="ni-tr"><small>${E(new Date(x.ts * 1000).toLocaleString())}</small><b>${E(tr(x.kind))}</b><span class="ni-ans">${E(x.target || "")} ${x.verdict ? "· " + E(x.verdict) : ""}${x.state ? "· " + E(x.state) : ""}${x.findings ? "· " + E(x.findings.join(", ") || tr("nothing unusual")) : ""}</span></div>`).join("") + "</div>";
  }

  function render() {
    const body = $("#niBody"); if (!body) return;
    const map = { overview: paneOverview, sites: paneSites, dns: paneDns, ip: paneIp, vpn: paneVpn, history: paneHistory };
    const focus = document.activeElement && document.activeElement.id, val = focus && $("#" + focus) ? $("#" + focus).value : null;
    body.innerHTML = map[NI.pane]();
    if (focus && $("#" + focus)) { const el = $("#" + focus); el.focus(); if (val != null && "value" in el) el.value = val; }
  }

  /* ------------------------------------------------------------------ actions */
  function go(what, el) {
    const call = (path, body, key) => { NI.busy[key] = true; render(); return api(path, body).then(r => { if (!r.ok) { NI.busy[key] = false; render(); toast(r.error || tr("Failed")); } return r; }); };
    if (what === "overview") call("ni_overview", {}, "overview");
    else if (what === "investigate") { const t = ($("#niSite") || {}).value || ""; NI.lastTarget = t; NI.fix = null; call("ni_investigate", { target: t }, "investigate"); }
    else if (what === "lookup") { const n = ($("#niName") || {}).value || ""; NI.lastName = n; NI.types = $$("#niBody [data-rt]").filter(x => x.checked).map(x => x.dataset.rt); call("ni_lookup", { name: n, types: NI.types }, "lookup"); }
    else if (what === "vpn") call("ni_vpn", {}, "vpn");
    else if (what === "fix") { if (!NI.inv) return; if (!confirm(tr("Change this adapter's DNS to an independent resolver that returned the real address? NOBAD saves your current DNS first, checks other sites afterwards, and undoes the change automatically if anything breaks."))) return; NI.fix = null; call("ni_fix", { id: NI.inv.id }, "fix"); }
    else if (what === "rollback") api("ni_rollback", { entry: el.dataset.entry }).then(r => { if (!r.ok) toast(r.error || r.detail); });
    else if (what === "repair") { if (window.NX && NX.netRepair) NX.netRepair(el.dataset.level); }
    else if (what === "vpnconnect") { if (typeof mainAction === "function" && !S.connected) mainAction(); }
    else if (what === "hclear") { if (confirm(tr("Delete the local diagnostic history and baselines?"))) api("ni_history_clear", {}).then(loadHistory); }
  }
  function onClick(e) { const b = e.target.closest("[data-go]"); if (b) go(b.dataset.go, b); }
  document.addEventListener("change", e => { if (e.target && e.target.id === "niAuto") api("settings", { key: "ni_autofix", value: e.target.checked }).then(r => { if (!r.ok) toast(r.error); }); });
  function loadHistory() { api("ni_history", {}).then(r => { if (r.ok) { NI.hist = r; if (NI.pane === "history") render(); } }); }

  /* ------------------------------------------------------------------ events */
  function handle(type, p) {
    switch (type) {
      case "ni_overview": NI.busy.overview = false; NI.ov = p; render(); return true;
      case "ni_progress": return true;
      case "net_repair_start": case "net_repair_done": if (NI.pane === "overview") setTimeout(render, 0); return false;   // app_ext shows the result
      case "ni_investigation": NI.busy.investigate = false; NI.inv = p; render(); return true;
      case "ni_lookup": NI.busy.lookup = false; NI.lookup = p; render(); return true;
      case "ni_vpn": NI.busy.vpn = false; NI.vpn = p; render(); return true;
      case "ni_fix": NI.busy.fix = false; NI.fix = p; if (NI.pane === "sites") render(); if (p.state === "applied") toast(tr("Site unblocked"), true); return true;
      default: return false;
    }
  }
  function init() {
    buildShell(); render();
    const prev = NX.handle; NX.handle = (t, p) => handle(t, p) || prev(t, p);
    const prevState = NX.onState; NX.onState = st => { prevState(st); if (NI.pane === "sites") { const a = $("#niAuto"); if (a && document.activeElement !== a) a.checked = !!st.settings.ni_autofix; } };
    const tab = document.querySelector('#dock [data-tab="t6"]');   /* ids are rewritten by the a11y layer */ if (tab) tab.addEventListener("click", () => { if (!NI.ov && !NI.busy.overview) go("overview"); });
  }
  if (window.NX) init(); else addEventListener("load", init);
})();
