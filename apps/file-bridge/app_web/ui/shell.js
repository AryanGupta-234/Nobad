// App shell: navigation rail, routing (#/screen), header, bottom dock, keyboard shortcuts and start-up.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, $$ = NB.$$, esc = NB.esc;

  // Every screen, in rail order. `ready` screens have a real implementation; the others show what is coming.
  NB.SCREENS = [
    { id: "files", label: "Files", icon: "files", group: "main", keys: "Ctrl+1" },
    { id: "connections", label: "Connections", icon: "servers", group: "main", keys: "Ctrl+2" },
    { id: "terminal", label: "Terminal", icon: "terminal", group: "main", keys: "Ctrl+3" },
    { id: "editor", label: "Editor", icon: "code", group: "main", keys: "Ctrl+4" },
    { id: "sync", label: "Sync jobs", icon: "sync", group: "main", keys: "Ctrl+5" },
    { id: "deploy", label: "Deployments", icon: "deploy", group: "main", keys: "Ctrl+6" },
    { id: "vault", label: "Credential vault", icon: "vault", group: "main", keys: "Ctrl+7" },
    { id: "dashboard", label: "Server health", icon: "pulse", group: "tools" },
    { id: "services", label: "Services", icon: "services", group: "tools" },
    { id: "tunnels", label: "Tunnels", icon: "tunnel", group: "tools" },
    { id: "logs", label: "Live logs", icon: "logs", group: "tools" },
    { id: "playbooks", label: "Playbooks", icon: "play", group: "tools" },
    { id: "settings", label: "Settings", icon: "settings", group: "foot", keys: "Ctrl+," }
  ];
  NB.screens = NB.screens || {};
  var byId = {};
  NB.SCREENS.forEach(function (s) { byId[s.id] = s; });
  var current = null;

  // ---------------------------------------------------------------- rail
  function railItem(s) {
    var ready = NB.screens[s.id] && NB.screens[s.id].ready;
    return '<button class="rail-item' + (ready ? '' : ' upcoming') + '" type="button" data-screen="' + s.id + '" title="' +
      esc(s.label + (ready ? '' : ' (being rebuilt)')) + '"' +
      (s.keys ? ' aria-keyshortcuts="' + s.keys.replace("Ctrl", "Control") + '"' : "") + ">" + ICO(s.icon) +
      '<span class="label">' + esc(s.label) + "</span></button>";
  }
  function renderRail() {
    var html = "";
    html += NB.SCREENS.filter(function (s) { return s.group === "main"; }).map(railItem).join("");
    html += '<div class="rail-group" id="toolsLabel">Server tools</div>';
    html += NB.SCREENS.filter(function (s) { return s.group === "tools"; }).map(railItem).join("");
    html += '<div class="rail-foot">' + NB.SCREENS.filter(function (s) { return s.group === "foot"; }).map(railItem).join("") +
      '<button class="rail-item" type="button" id="railToggle" aria-label="Collapse sidebar">' + ICO("sidebar") +
      '<span class="label">Collapse</span></button></div>';
    var rail = $("#rail");
    rail.innerHTML = html;
    rail.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-screen]");
      if (btn) { go(btn.getAttribute("data-screen")); }
    });
    $("#railToggle").addEventListener("click", function () { setRailCollapsed(!$("#app").classList.contains("rail-collapsed")); });
    // Arrow keys move between rail items (one tab stop for the whole list would hide it; keep Tab too).
    rail.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") { return; }
      var items = $$(".rail-item", rail), i = items.indexOf(document.activeElement);
      if (i < 0) { return; }
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    });
  }
  function setRailCollapsed(on) {
    $("#app").classList.toggle("rail-collapsed", on);
    var t = $("#railToggle");
    t.setAttribute("aria-label", on ? "Expand sidebar" : "Collapse sidebar");
    t.querySelector(".label").textContent = on ? "Expand" : "Collapse";
    NB.uiState("railCollapsed", on);
  }

  // ---------------------------------------------------------------- routing
  function go(id, opts) {
    if (!byId[id]) { id = "files"; }
    if (location.hash !== "#/" + id) { history.replaceState(null, "", "#/" + id); }
    show(id, opts || {});
  }
  NB.go = go;
  function show(id, opts) {
    var s = byId[id], impl = NB.screens[id] || NB.screens.__upcoming;
    if (current && current.impl.leave) { current.impl.leave(); }
    $$(".rail-item[data-screen]").forEach(function (b) {
      if (b.getAttribute("data-screen") === id) { b.setAttribute("aria-current", "page"); } else { b.removeAttribute("aria-current"); }
    });
    var host = $("#screen");
    host.innerHTML = "";
    var el = document.createElement("div");
    el.className = "screen";
    el.setAttribute("data-screen", id);
    host.appendChild(el);
    current = { id: id, impl: impl };
    impl.render(el, s, opts);
    document.title = s.label + " · NOBAD File Bridge";
    NB.uiState("screen", id);
    if (opts.focus !== false) { $("#main").focus({ preventScroll: true }); }
  }
  window.addEventListener("hashchange", function () { show(location.hash.replace(/^#\//, "") || "files", {}); });

  // ---------------------------------------------------------------- banners
  NB.banner = function (id, kind, title, text) {
    var host = $("#banners"), el = host.querySelector('[data-banner="' + id + '"]');
    if (!el) { el = document.createElement("div"); el.setAttribute("data-banner", id); host.appendChild(el); }
    el.className = "banner " + kind;
    el.innerHTML = ICO(kind === "bad" ? "warn" : kind === "warn" ? "warn" : "info") + "<div><b></b><p></p></div>";
    el.querySelector("b").textContent = title;
    el.querySelector("p").textContent = text;
  };

  // ---------------------------------------------------------------- dock
  var logEntries = [], dockTab = "transfers";
  function dockOpen() { return !$("#dock").classList.contains("collapsed"); }
  function setDock(open, tab) {
    if (tab) { dockTab = tab; }
    $("#dock").classList.toggle("collapsed", !open);
    var t = $("#dockToggle");
    t.innerHTML = ICO(open ? "down" : "up");
    t.setAttribute("aria-expanded", open ? "true" : "false");
    t.setAttribute("aria-label", open ? "Hide dock" : "Show dock");
    $$(".dock-tab").forEach(function (b) { b.setAttribute("aria-selected", b.getAttribute("data-tab") === dockTab ? "true" : "false"); });
    $("#dockBody").setAttribute("aria-labelledby", dockTab === "activity" ? "dockTabActivity" : "dockTabTransfers");
    NB.uiState("dock", { open: open, tab: dockTab });
    renderDock();
  }
  NB.setDock = setDock;
  function renderDock() {
    $("#logCount").textContent = String(logEntries.length);
    if (!dockOpen()) { return; }
    var body = $("#dockBody");
    if (dockTab === "transfers") {
      body.innerHTML = '<div class="dock-empty">No transfers yet. Uploads and downloads you start will show here with their speed and progress.</div>';
      return;
    }
    if (!logEntries.length) { body.innerHTML = '<div class="dock-empty">Nothing logged yet.</div>'; return; }
    body.innerHTML = logEntries.map(function (e) {
      return '<div class="log-row ' + esc(e.level) + '"><span class="ts">' + esc(e.ts) + '</span><span class="lv" aria-hidden="true"></span>' +
        '<span class="msg"><span class="sr-only">' + esc(e.level) + ": </span>" + esc(e.msg) + "</span></div>";
    }).join("");
    body.scrollTop = body.scrollHeight;
  }
  function bindDock() {
    $$(".dock-tab").forEach(function (b) {
      b.addEventListener("click", function () {
        var tab = b.getAttribute("data-tab");
        setDock(!(dockOpen() && tab === dockTab), tab);
      });
    });
    $("#dockToggle").addEventListener("click", function () { setDock(!dockOpen()); });
    // Tablist pattern: Left/Right move between the dock tabs.
    $(".dock-bar").addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") { return; }
      var tabs = $$(".dock-tab"), i = tabs.indexOf(document.activeElement);
      if (i < 0) { return; }
      e.preventDefault();
      var next = tabs[(i + 1) % tabs.length];
      next.focus();
      setDock(true, next.getAttribute("data-tab"));
    });
    NB.on("log", function (entry) {
      logEntries.push(entry);
      if (logEntries.length > 300) { logEntries.shift(); }
      renderDock();
    });
    NB.on("log_cleared", function () { logEntries = []; renderDock(); });
  }

  // ---------------------------------------------------------------- header
  function renderThemeButton() {
    var dark = document.documentElement.getAttribute("data-theme") !== "light";
    var b = $("#themeBtn");
    b.innerHTML = ICO(dark ? "sun" : "moon");
    b.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    b.title = b.getAttribute("aria-label");
  }
  NB.toggleTheme = function () {
    var next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    NB.applyTheme(next);
    NB.api("settings.set", { id: "web_ui.theme", value: next }).then(function (r) {
      if (!r.ok) { NB.toast(r.error || "Couldn't save the theme."); }
    });
  };
  NB.on("theme", renderThemeButton);
  NB.on("setting_changed", function (p) { if (p && p.id === "web_ui.theme" && p.value !== NB.themePref) { NB.applyTheme(p.value); } });

  // ---------------------------------------------------------------- keyboard
  function bindKeys() {
    document.addEventListener("keydown", function (e) {
      var mod = e.ctrlKey || e.metaKey;
      if (!mod || e.altKey) { return; }
      var k = e.key.toLowerCase();
      if (k === "k") { e.preventDefault(); NB.palette.open(); return; }
      if (k === "j") { e.preventDefault(); setDock(!dockOpen()); return; }
      if (k === "b") { e.preventDefault(); setRailCollapsed(!$("#app").classList.contains("rail-collapsed")); return; }
      if (k === ",") { e.preventDefault(); go("settings"); return; }
      if (/^[1-7]$/.test(k)) { e.preventDefault(); go(NB.SCREENS[Number(k) - 1].id); }
    });
  }

  // ---------------------------------------------------------------- start-up
  function start() {
    renderRail();
    bindDock();
    bindKeys();
    $("#themeBtn").addEventListener("click", NB.toggleTheme);
    $("#openPalette").addEventListener("click", function () { NB.palette.open(); });
    renderThemeButton();
    if (NB.uiState("railCollapsed")) { setRailCollapsed(true); }
    var dock = NB.uiState("dock") || {};
    setDock(!!dock.open, dock.tab || "transfers");
    var first = location.hash.replace(/^#\//, "") || NB.uiState("screen") || "files";
    go(first, { focus: false });

    NB.api("app.info").then(function (r) {
      if (!r.ok) { return; }
      $("#dockMeta").textContent = "v" + r.data.version + " · ✦ made with AI";
      if (NB.titlebar) { NB.titlebar.enable(r.data.window); }
      if (r.data.storage_warning) { NB.banner("storage", "warn", "Your data isn't being saved", r.data.storage_warning); }
    });
    NB.api("settings.schema").then(function (r) {
      if (r.ok && r.data.values["web_ui.theme"] !== NB.themePref) { NB.applyTheme(r.data.values["web_ui.theme"]); }
    });
    NB.api("log.recent").then(function (r) {
      if (r.ok) { logEntries = r.data.concat(logEntries).slice(-300); renderDock(); }
    });
    var lost = false;
    NB.on("stream", function (state) {
      if (state === "lost" && !lost) { lost = true; NB.banner("stream", "bad", "Lost contact with the app", "Live updates stopped. They resume on their own when the app is reachable again."); }
      if (state === "open" && lost) { lost = false; var b = $('[data-banner="stream"]'); if (b) { b.remove(); } }
    });
    NB.connectEvents();
  }
  document.addEventListener("DOMContentLoaded", start);
})();
