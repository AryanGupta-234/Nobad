// Terminal: xterm.js tabs for the connected server (SSH) and this computer (ConPTY / PTY).
// Terminals live on when you switch screens: their xterm instances stay in NB.terms and are re-attached.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, $$ = NB.$$, esc = NB.esc;
  var terms = (NB.terms = new Map());      // id -> {info, xterm, fit, el, queue, sending, dead}
  var activeId = null, host = null, settings = { font: 13, scrollback: 5000 };

  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function theme() {
    var light = document.documentElement.getAttribute("data-theme") === "light";
    return {
      background: cssVar("--surface"), foreground: cssVar("--tx"), cursor: cssVar("--acc"), cursorAccent: cssVar("--surface"),
      selectionBackground: light ? "rgba(37,99,235,.22)" : "rgba(59,130,246,.35)",
      black: light ? "#1f2430" : "#2a2e38", red: cssVar("--bad"), green: cssVar("--ok"), yellow: cssVar("--warn"),
      blue: cssVar("--acc-tx"), magenta: light ? "#9a3fbf" : "#c792ea", cyan: cssVar("--busy"), white: light ? "#4e5665" : "#d7dae0",
      brightBlack: light ? "#6b7280" : "#5c6370", brightRed: light ? "#e5484d" : "#ff7a8a", brightGreen: light ? "#18a36d" : "#6ff0be",
      brightYellow: light ? "#c27c0e" : "#ffd27a", brightBlue: light ? "#3b82f6" : "#9ec5ff", brightMagenta: light ? "#b45ad6" : "#e1b6ff",
      brightCyan: light ? "#0e9ccf" : "#7fd8ff", brightWhite: light ? "#121620" : "#ffffff"
    };
  }

  NB.termTheme = theme;            // shared with read-only output views (Playbooks)

  // ---- create / attach
  function create(info) {
    var el = document.createElement("div");
    el.className = "term-view";
    el.setAttribute("data-id", info.id);
    var xterm = new window.Terminal({
      fontFamily: getComputedStyle(document.documentElement).getPropertyValue("--font-mono"),
      fontSize: settings.font, scrollback: settings.scrollback, cursorBlink: true, allowProposedApi: false,
      theme: theme(), macOptionIsMeta: true, rightClickSelectsWord: true
    });
    var FitCls = window.FitAddon && (window.FitAddon.FitAddon || window.FitAddon);
    var fit = new FitCls();
    xterm.loadAddon(fit);
    var t = { info: info, xterm: xterm, fit: fit, el: el, queue: "", sending: false, dead: !info.alive, opened: false };
    terms.set(info.id, t);
    xterm.onData(function (data) {
      if (t.dead) { if (data === "\r") { closeTerm(info.id); } return; }
      t.queue += data;
      pump(t);
    });
    xterm.attachCustomKeyEventHandler(function (e) {
      if (e.type !== "keydown") { return true; }
      var mod = e.ctrlKey || e.metaKey;
      if (mod && e.shiftKey && e.key.toLowerCase() === "c") { var s = xterm.getSelection(); if (s) { navigator.clipboard.writeText(s); } return false; }
      if (mod && e.shiftKey && e.key.toLowerCase() === "v") {
        navigator.clipboard.readText().then(function (text) { if (text) { xterm.paste(text); } });
        return false;
      }
      return true;
    });
    xterm.onResize(function (size) { if (!t.dead) { NB.api("term.resize", { id: info.id, cols: size.cols, rows: size.rows }); } });
    return t;
  }
  // Keystrokes are sent in order: one request at a time, with everything typed meanwhile in the next one.
  function pump(t) {
    if (t.sending || !t.queue) { return; }
    var data = t.queue;
    t.queue = "";
    t.sending = true;
    NB.api("term.input", { id: t.info.id, data: data }).then(function (r) {
      t.sending = false;
      if (!r.ok) { t.xterm.write("\r\n\x1b[31m" + r.error + "\x1b[0m\r\n"); }
      pump(t);
    });
  }
  function attach(t) {
    var body = $(".term-body", host);
    if (!body) { return; }
    if (!t.el.parentNode || t.el.parentNode !== body) { body.appendChild(t.el); }
    if (!t.opened) { t.xterm.open(t.el); t.opened = true; }
  }
  function show(id) {
    activeId = id;
    if (!host) { return; }
    terms.forEach(function (t, tid) { t.el.hidden = tid !== id; });
    var t = terms.get(id);
    if (t) {
      attach(t);
      requestAnimationFrame(function () { try { t.fit.fit(); } catch (e) { /* hidden */ } t.xterm.focus(); });
    }
    renderTabs();
  }

  // ---- open / close
  NB.openTerminal = function (kind, cwd) {
    var size = { cols: 100, rows: 30 };
    return NB.api("term.open", { kind: kind, cwd: cwd || null, cols: size.cols, rows: size.rows }).then(function (r) {
      if (!r.ok) { NB.toast(r.error); return null; }
      create(r.data);
      activeId = r.data.id;
      if (host) { renderBody(); show(r.data.id); } else { NB.go("terminal"); }
      return r.data.id;
    });
  };
  function closeTerm(id) {
    NB.api("term.close", { id: id });
    drop(id);
  }
  function drop(id) {
    var t = terms.get(id);
    if (!t) { return; }
    t.xterm.dispose();
    t.el.remove();
    terms.delete(id);
    if (activeId === id) { activeId = terms.size ? Array.from(terms.keys()).pop() : null; }
    if (host) { if (activeId) { show(activeId); } else { renderBody(); } }
  }
  NB.on("term.out", function (p) { var t = terms.get(p.id); if (t) { t.xterm.write(p.data); } });
  NB.on("term.exit", function (p) {
    var t = terms.get(p.id);
    if (!t || t.dead) { return; }
    t.dead = true;
    t.xterm.write("\r\n\x1b[2m[The session ended. Press Enter to close this tab.]\x1b[0m\r\n");
    renderTabs();
  });
  NB.on("term.closed", function (p) { drop(p.id); });
  NB.on("theme", function () { terms.forEach(function (t) { t.xterm.options.theme = theme(); }); });
  NB.on("setting_changed", function (p) {
    if (p.id === "terminal.font_size") { settings.font = p.value; terms.forEach(function (t) { t.xterm.options.fontSize = p.value; try { t.fit.fit(); } catch (e) { /* hidden */ } }); }
    if (p.id === "terminal.scrollback") { settings.scrollback = p.value; terms.forEach(function (t) { t.xterm.options.scrollback = p.value; }); }
  });

  // ---- render
  function renderTabs() {
    var bar = host && $(".term-tabs", host);
    if (!bar) { return; }
    var connected = NB.conn.status === "connected";
    bar.innerHTML = Array.from(terms.values()).map(function (t) {
      var on = t.info.id === activeId;
      return '<div class="term-tab' + (on ? " on" : "") + (t.dead ? " dead" : "") + '" role="presentation">' +
        '<button type="button" role="tab" class="term-tab-btn" data-id="' + esc(t.info.id) + '" aria-selected="' + on + '">' +
        ICO(t.info.kind === "remote" ? "servers" : "window") + '<span>' + esc(t.info.title) + "</span></button>" +
        '<button type="button" class="icon ghost sm term-x" data-close="' + esc(t.info.id) + '" aria-label="Close ' + esc(t.info.title) + ' terminal">' + ICO("close") + "</button></div>";
    }).join("") +
      '<div class="term-new"><button type="button" class="sm" data-new="remote"' + (connected ? "" : " disabled title=\"Connect to a server first\"") + ">" + ICO("plus") + "Server</button>" +
      '<button type="button" class="sm" data-new="local">' + ICO("plus") + "This computer</button></div>";
  }
  function renderBody() {
    var body = $(".term-body", host), empty = $(".term-empty", host);
    if (!terms.size) {
      body.hidden = true;
      empty.hidden = false;
      var connected = NB.conn.status === "connected";
      empty.innerHTML = '<div class="empty"><div class="empty-ico">' + ICO("terminal") + "</div><h2>Open a terminal</h2>" +
        "<p>" + (connected ? "A shell on " + esc(NB.conn.profile.name) + ", or one on this computer." : "A shell on this computer. Connect to a server to open one there too.") + "</p>" +
        '<div class="actions">' + (connected ? '<button type="button" class="pri" data-new="remote">' + ICO("servers") + "On " + esc(NB.conn.profile.name) + "</button>" : "") +
        '<button type="button"' + (connected ? "" : ' class="pri"') + ' data-new="local">' + ICO("window") + "On this computer</button></div>" +
        '<p class="faint">Copy with Ctrl+Shift+C, paste with Ctrl+Shift+V.</p></div>';
    } else {
      body.hidden = false;
      empty.hidden = true;
    }
    renderTabs();
  }

  NB.screens.terminal = {
    ready: true,
    render: function (el) {
      el.classList.add("screen-term");
      el.innerHTML = '<div class="term-shell card"><div class="term-tabs" role="tablist" aria-label="Terminals"></div>' +
        '<div class="term-body"></div><div class="term-empty" hidden></div></div>';
      host = el;
      el.addEventListener("click", function (e) {
        var b = e.target.closest("[data-new],[data-close],.term-tab-btn");
        if (!b) { return; }
        if (b.hasAttribute("data-new")) { NB.openTerminal(b.getAttribute("data-new")); }
        else if (b.hasAttribute("data-close")) { closeTerm(b.getAttribute("data-close")); }
        else { show(b.getAttribute("data-id")); }
      });
      $(".term-tabs", el).addEventListener("keydown", function (e) {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") { return; }
        var ids = Array.from(terms.keys()), i = ids.indexOf(activeId);
        if (i < 0) { return; }
        e.preventDefault();
        show(ids[(i + (e.key === "ArrowRight" ? 1 : ids.length - 1)) % ids.length]);
        var tab = $('.term-tab-btn[data-id="' + activeId + '"]', el);
        if (tab) { tab.focus(); }
      });
      var ro = new ResizeObserver(function () { var t = terms.get(activeId); if (t && t.opened) { try { t.fit.fit(); } catch (e) { /* hidden */ } } });
      ro.observe($(".term-body", el));
      el._ro = ro;
      renderBody();
      if (activeId && terms.has(activeId)) { show(activeId); }
      else if (terms.size) { show(Array.from(terms.keys())[0]); }
    },
    leave: function () {
      if (host && host._ro) { host._ro.disconnect(); }
      terms.forEach(function (t) { if (t.el.parentNode) { t.el.parentNode.removeChild(t.el); } });
      host = null;
    }
  };

  NB.on("conn", function () { if (host) { renderBody(); } });
  document.addEventListener("DOMContentLoaded", function () {
    NB.api("settings.schema").then(function (r) {
      if (r.ok) { settings.font = r.data.values["terminal.font_size"]; settings.scrollback = r.data.values["terminal.scrollback"]; }
    });
    NB.api("term.list").then(function (r) {                 // tabs from before a reload, with what they showed
      if (!r.ok) { return; }
      r.data.forEach(function (info) {
        var t = create(info);
        NB.api("term.history", { id: info.id }).then(function (h) { if (h.ok && h.data.data) { t.xterm.write(h.data.data); } });
        if (!activeId) { activeId = info.id; }
      });
      if (host && activeId) { renderBody(); show(activeId); }
    });
  });
})();
