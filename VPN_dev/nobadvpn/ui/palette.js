/* Command palette v2 (Ctrl+K / Search): finds actions, servers, tabs and every setting with fuzzy matching, and
   turns free text into "Where to watch" and "Investigate" queries. Replaces palItems / palDraw / palRun from
   index.html; the open/close and keyboard handling there stay the same. */
(function () {
  "use strict";
  const tr = s => (window.NX && NX.t ? NX.t(s) : s);
  const RKEY = "nx_pal_recent";
  const recent = () => { try { return JSON.parse(localStorage.getItem(RKEY) || "[]"); } catch (_) { return []; } };
  const remember = id => { try { localStorage.setItem(RKEY, JSON.stringify([id].concat(recent().filter(x => x !== id)).slice(0, 8))); } catch (_) {} };
  const TABS = [["Servers", "t2", "locations configs probe"], ["Streaming", "t1", "speed test where to watch services"],
                ["Network", "t5", "health gaming valorant ping"], ["Intel", "t6", "network intelligence dns investigate"],
                ["Details", "t4", "usage history log"], ["Settings", "t3", "preferences options"]];
  const looksLikeHost = q => /^[a-z0-9-]+(\.[a-z0-9-]+)+(\/.*)?$/i.test(q.replace(/^https?:\/\//, "").trim());

  /* fuzzy score: substring > word-start initials > in-order letters; 0 = no match */
  function score(q, text) {
    if (!q) return 1;
    const t = text.toLowerCase(), s = q.toLowerCase().trim();
    if (!s) return 1;
    const i = t.indexOf(s);
    if (i === 0) return 1000 - t.length;
    if (i > 0 && /[^a-z0-9]/.test(t[i - 1])) return 800 - i;          // at a word start: "switch" in "kill switch"
    const words = t.split(/[^a-z0-9]+/).filter(Boolean);
    const initials = words.map(w => w[0]).join("");
    if (s.length >= 2 && !s.includes(" ") && initials.startsWith(s)) return 760 - words.length;   // "ks" -> Kill Switch
    if (s.split(/\s+/).every(part => words.some(w => w.startsWith(part)))) return 700;
    if (i > 0) return 420 - i;                                       // inside a word: "ks" in "checks"
    let j = 0, gaps = 0;
    for (const ch of t) { if (ch === s[j]) j++; else if (j) gaps++; if (j === s.length) break; }
    return j === s.length ? Math.max(1, 300 - gaps * 3) : 0;
  }

  function settingItems() {
    const out = [], groups = (window.NX && NX.groups) || [];
    groups.forEach(g => (g.rows || []).forEach(r => {
      if (r.custom) return;
      const title = tr(r.n || ""), group = tr(g.title);
      if (r.k && !r.type && !r.act) {
        const on = !!(S.settings && S.settings[r.k]);
        out.push({ id: "set:" + r.k, g: "Settings", t: `${title}: ${tr(on ? "turn off" : "turn on")}`, hint: group + " · " + tr(on ? "on" : "off"),
          kw: (r.kw || "") + " " + (r.d || ""),
          run: () => api("settings", { key: r.k, value: !on }).then(x => toast(x.ok ? `${title}: ${tr(!on ? "on" : "off")}` : (x.error || tr("Could not save")), !!x.ok)) });
      } else {
        out.push({ id: "set:" + (r.k || r.act), g: "Settings", t: title, hint: group, kw: (r.kw || "") + " " + (r.d || "") + " " + (r.label || ""),
          run: () => openSetting(g.id, r.k || r.act) });
      }
    }));
    return out;
  }
  function openSetting(gid, key) {
    tabTo("t3");
    setTimeout(() => {
      const grp = document.querySelector(`.nx-grp[data-g="${gid}"]`); if (grp) grp.open = true;
      const row = document.querySelector(`.nx-row[data-k="${key}"]`) || document.querySelector(`[data-act="${key}"]`);
      const el = row && row.closest(".nx-row") || row;
      if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); el.classList.add("nx-flash"); setTimeout(() => el.classList.remove("nx-flash"), 1600);
        const f = el.querySelector("input,select,button"); if (f) f.focus({ preventScroll: true }); }
    }, 120);
  }

  function items(q) {
    const st = S.settings || {}, conn = !!S.connected;
    const a = [
      { id: "main", g: "Actions", t: conn ? tr("Disconnect") : tr("Connect"), hint: conn ? S.active : (S.selected || ""), kw: "vpn on off", run: mainAction, key: "Space" },
      { id: "fastest", g: "Actions", t: tr("Connect to the fastest server"), kw: "quick best latency", run: () => api("fastest", {}) },
      { id: "ks", g: "Actions", t: tr(st.kill_switch ? "Turn the kill switch off" : "Turn the kill switch on"), kw: "kill switch block leak", run: () => api("settings", { key: "kill_switch", value: !st.kill_switch }) },
      { id: "speed", g: "Actions", t: tr("Run a speed test"), kw: "bandwidth mbps", run: () => { tabTo("t1"); setTimeout(() => { const b = $("#bSpeed"); if (b && !b.disabled) b.click(); }, 80); } },
      { id: "stream", g: "Actions", t: tr("Check streaming services"), kw: "netflix youtube disney prime reachability", run: () => { tabTo("t1"); setTimeout(() => { const b = $("#bStream"); if (b && !b.disabled) b.click(); }, 80); } },
      { id: "netcheck", g: "Actions", t: tr("Run a network check"), kw: "router internet dns health", run: () => { tabTo("t5"); setTimeout(() => { const b = $("#bNetCheck"); if (b && !b.disabled) b.click(); }, 80); } },
      { id: "probe", g: "Actions", t: tr("Probe all servers"), kw: "ping latency", run: () => { tabTo("t2"); api("probe", {}); } },
      { id: "restore", g: "Actions", t: tr("Restore internet"), kw: "panic reset fix offline firewall", run: () => NX.panic && NX.panic() },
      { id: "repair", g: "Actions", t: tr("Quick network repair"), kw: "fix internet dns flush dhcp", run: () => NX.netRepair && NX.netRepair("quick") },
      { id: "theme", g: "Actions", t: tr("Switch light / dark mode"), kw: "theme appearance", run: () => $("#bTheme").click() },
      { id: "mini", g: "Actions", t: tr("Open the quick view"), kw: "mini window tray compact", run: () => api("window", { do: "mini" }) },
      { id: "configs", g: "Actions", t: tr("Open the configs folder"), kw: "wireguard conf files", run: () => api("open_configs", {}) },
      { id: "watch", g: "Actions", t: tr("Where to watch…"), kw: "movie series anime streaming country", run: () => { tabTo("t1"); setTimeout(() => { const i = $("#siQ"); if (i) { i.scrollIntoView({ block: "center" }); i.focus(); } }, 120); } },
    ];
    TABS.forEach(([n, t, kw]) => a.push({ id: "tab:" + t, g: "Go to", t: tr(n), kw, run: () => tabTo(t) }));
    (S.regions || []).forEach(r => {
      const p = r.ping || {}, c = (r.geo && r.geo.country) || "";
      a.push({ id: "srv:" + r.name, g: "Servers", t: (S.connected && S.active === r.name ? tr("Connected: ") : tr("Connect to ")) + r.name,
        hint: [p.rtt != null ? p.rtt + " ms" : "", c].filter(Boolean).join(" · "), kw: r.name + " " + c + " " + (r.host || ""),
        run: () => { S.selected = r.name; api("connect", { name: r.name }); } });
    });
    a.push(...settingItems());
    const qq = (q || "").trim();
    if (qq.length >= 2) {
      if (looksLikeHost(qq)) a.push({ id: "q:investigate", g: "Ask", t: `${tr("Investigate")} “${qq}”`, hint: tr("Network Intelligence"), always: true,
        run: () => { tabTo("t6"); setTimeout(() => { const s = document.querySelector("[data-ni=sites]"); if (s) s.click();
          setTimeout(() => { const i = $("#niSite"); if (i) { i.value = qq; const b = document.querySelector("[data-go=investigate]"); if (b) b.click(); } }, 150); }, 150); } });
      a.push({ id: "q:watch", g: "Ask", t: `${tr("Where to watch")} “${qq}”`, hint: tr("streaming catalogues by country"), always: true,
        run: () => window.NXSI && NXSI.search(qq) });
    }
    return a;
  }

  window.palItems = function () { return PAL.items.map(x => [x.t, x.run]); };
  window.palDraw = function () {
    const q = $("#palin").value;
    const rec = recent();
    const scored = items(q).map(x => ({ x, s: x.always ? 1 : Math.max(score(q, x.t), score(q, (x.kw || "")) * 0.6) })).filter(o => o.s > 0);
    scored.forEach(o => { const r = rec.indexOf(o.x.id); if (r >= 0) o.s += q ? 40 - r * 4 : 2000 - r * 10; });
    const best = scored.reduce((m, o) => o.x.always ? m : Math.max(m, o.s), 0);
    if (q && best >= 400) for (let k = scored.length - 1; k >= 0; k--) if (!scored[k].x.always && scored[k].s < 300) scored.splice(k, 1);
    let list;
    if (!q) {                       // no query: recently used first, then the main actions and tabs
      list = scored.filter(o => rec.includes(o.x.id)).sort((a, b) => b.s - a.s).map(o => Object.assign({}, o.x, { g: "Recent" }))
        .concat(scored.filter(o => !rec.includes(o.x.id) && (o.x.g === "Actions" || o.x.g === "Go to")).map(o => o.x));
    } else {
      list = scored.sort((a, b) => b.s - a.s).slice(0, 40).map(o => o.x);
      const ask = list.filter(x => x.g === "Ask"), rest = list.filter(x => x.g !== "Ask");
      // keep each group together (ordered by its best match), so headings never repeat
      const order = [], byG = {};
      rest.forEach(x => { if (!byG[x.g]) { byG[x.g] = []; order.push(x.g); } byG[x.g].push(x); });
      const grouped = order.reduce((acc, g) => acc.concat(byG[g]), []);
      list = best >= 700 ? grouped.concat(ask) : ask.concat(grouped);     // no strong match: offer the free-text actions first
    }
    const seen = new Set();
    list = list.filter(x => { const k = x.t.toLowerCase(); if (seen.has(k)) return false; seen.add(k); return true; });
    PAL.items = list; PAL.list = list.map(x => [x.t, x.run]);
    PAL.sel = Math.min(PAL.sel, Math.max(0, list.length - 1));
    let h = "", last = null;
    list.forEach((x, i) => {
      if (x.g !== last && (!q || x.g === "Ask" || i === 0 || x.g !== last)) { h += `<div class="pal-g" role="presentation">${esc(tr(x.g))}</div>`; last = x.g; }
      h += `<div class="pal-i${i === PAL.sel ? " s" : ""}" data-i="${i}" id="palo${i}" role="option" aria-selected="${i === PAL.sel}">
        <span class="pal-t">${esc(x.t)}</span>${x.hint ? `<span class="pal-h">${esc(x.hint)}</span>` : ""}${x.key ? `<kbd>${esc(x.key)}</kbd>` : ""}</div>`;
    });
    $("#pall").innerHTML = h || `<div class="pal-empty" role="option" aria-disabled="true">${esc(tr("No match. Try a server, a setting or an action."))}</div>`;
    const inp = $("#palin");
    if (list.length) inp.setAttribute("aria-activedescendant", "palo" + PAL.sel); else inp.removeAttribute("aria-activedescendant");
    const cur = $("#palo" + PAL.sel); if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest" });
  };
  window.palRun = function (i) {
    const x = PAL.items && PAL.items[i]; if (!x) return;
    remember(x.id); palToggle();
    try { x.run(); } catch (e) { toast(String(e)); }
  };
  function init() {
    PAL.items = [];
    const inp = $("#palin"); if (inp) inp.placeholder = tr("Search actions, servers, settings… or type a site or a title");
  }
  if (window.NX) init(); else addEventListener("load", init);
})();
