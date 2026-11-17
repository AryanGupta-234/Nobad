// Live logs: follow log files (tail -F) and systemd units (journalctl -f) on the connected server. Lines arrive
// in batches; the viewer keeps the last 10,000 per log, filters by level and text, and follows the end unless you
// scroll up. Streams keep running when you switch screens and stop with the connection.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, esc = NB.esc;
  var MAX = 10000, ROW = 22;
  var host = null, streams = [], presets = [], buffers = {}, active = null, level = "all", query = "", follow = true, list = null, view = [], skipped = {};

  function load() {
    return NB.api("logs.list").then(function (r) {
      if (!r.ok) { return; }
      streams = r.data.streams;
      presets = r.data.presets;
      streams.forEach(function (s) {
        if (!buffers[s.id]) {
          buffers[s.id] = [];
          NB.api("logs.tail", { id: s.id, count: MAX }).then(function (t) { if (t.ok) { buffers[s.id] = t.data.concat(buffers[s.id]).slice(-MAX); if (s.id === active) { refilter(); } } });
        }
      });
      if (!active && streams.length) { active = streams[streams.length - 1].id; }
      if (active && !streams.some(function (s) { return s.id === active; })) { active = streams.length ? streams[0].id : null; }
      render();
    });
  }
  function stream(id) { return streams.find(function (s) { return s.id === id; }); }
  function match(r) {
    if (level === "errors" && r.lvl !== "error") { return false; }
    if (level === "warnings" && r.lvl !== "error" && r.lvl !== "warn") { return false; }
    return !query || r.text.toLowerCase().indexOf(query) >= 0;
  }
  function refilter() {
    view = (buffers[active] || []).filter(match);
    if (list) {
      list.setCount(view.length);
      if (follow) { list.vp.scrollTop = list.vp.scrollHeight; }
    }
    var count = host && $(".lg-count", host);
    if (count) { count.textContent = view.length.toLocaleString() + " lines" + (skipped[active] ? " · " + skipped[active].toLocaleString() + " skipped while busy" : ""); }
  }
  function rowHtml(i) {
    var r = view[i];
    return '<div class="lg-row lv-' + esc(r.lvl) + '"><span class="lg-t faint">' + esc(r.t || "") + '</span><span class="lg-x">' + esc(r.text) + "</span></div>";
  }
  function status(s) {
    return s.status === "streaming" ? ["ok", "Following"] : s.status === "paused" ? ["warn", "Paused"] : s.status === "error" ? ["bad", "Stopped"] : s.status === "connecting" ? ["busy", "Starting"] : ["", "Stopped"];
  }
  function render() {
    if (!host) { return; }
    var connected = NB.conn.status === "connected";
    var s = active && stream(active);
    NB.frame(host).innerHTML = '<div class="screen-head"><div><h1>Live logs</h1><p>Follow log files and systemd services on the server as they are written.</p></div></div>' +
      (connected ? "" : '<p class="banner info">' + ICO("info") + "<span>Connect to an SSH server to follow its logs.</span></p>") +
      '<div class="lg-grid"><aside class="card lg-side"><div class="vp-head"><b>Logs</b></div><div class="lg-streams">' +
      (streams.length ? streams.map(function (x) {
        var st = status(x);
        return '<div class="lg-stream' + (x.id === active ? " on" : "") + '"><button type="button" class="lg-pick" data-pick="' + esc(x.id) + '" aria-current="' + (x.id === active) + '"><span class="dot ' + st[0] + '" aria-hidden="true"></span>' +
          '<span class="vi-main"><b>' + esc(x.name) + '</b><small class="mono">' + esc(x.path) + "</small></span></button>" +
          '<button type="button" class="icon ghost sm" data-close="' + esc(x.id) + '" aria-label="Close ' + esc(x.name) + '">' + ICO("close") + "</button></div>";
      }).join("") : '<p class="faint vp-empty">Nothing followed yet.</p>') + "</div>" +
      '<form class="lg-new" novalidate><b>Follow a log</b><select name="preset" aria-label="Common logs"><option value="">Common logs…</option>' +
      presets.map(function (p) { return '<option value="' + esc(p.id) + '">' + esc(p.name) + "</option>"; }).join("") + "</select>" +
      '<div class="seg sm" role="radiogroup" aria-label="Source"><button type="button" role="radio" data-src="file" aria-checked="true">File</button><button type="button" role="radio" data-src="journal" aria-checked="false">Service</button></div>' +
      '<input name="path" class="mono" autocomplete="off" spellcheck="false" placeholder="/var/log/nginx/error.log" aria-label="Log file or service">' +
      '<label class="check"><input type="checkbox" name="sudo"><span>Read with sudo</span></label>' +
      '<button type="submit" class="pri"' + (connected ? "" : " disabled") + ">" + ICO("play") + "Follow</button></form></aside>" +
      '<section class="card lg-view">' + (s ? '<div class="lg-bar"><span class="chip ' + status(s)[0] + '">' + status(s)[1] + '</span><span class="lg-count faint num"></span><span class="spacer"></span>' +
        '<input type="search" class="lg-search" placeholder="Find…" aria-label="Find in log" value="' + esc(query) + '">' +
        '<div class="seg sm" role="radiogroup" aria-label="Show">' + [["all", "All"], ["warnings", "Warnings"], ["errors", "Errors"]].map(function (l) {
          return '<button type="button" role="radio" data-level="' + l[0] + '" aria-checked="' + (l[0] === level) + '">' + l[1] + "</button>"; }).join("") + "</div>" +
        (s.status === "streaming" || s.status === "paused" ? '<button type="button" class="sm" data-a="pause">' + (s.status === "paused" ? "Resume" : "Pause") + "</button>" : "") +
        '<button type="button" class="sm ghost" data-a="clear">Clear view</button></div>' +
        (s.error ? '<p class="banner bad lg-err">' + ICO("warn") + "<span>" + esc(s.error) + "</span></p>" : "") +
        '<div class="lg-list mono" role="log" aria-label="' + esc(s.name) + '"></div>' +
        '<button type="button" class="sm lg-follow" data-a="follow"' + (follow ? " hidden" : "") + ">" + ICO("down") + "Jump to the newest line</button>"
        : '<div class="empty"><div class="empty-ico">' + ICO("logs") + "</div><h2>Choose a log to follow</h2><p>Pick a common log, type a file path, or choose a systemd service.</p></div>") + "</section></div>";
    var f = $(".lg-new", host), source = "file";
    f.addEventListener("click", function (e) {
      var b = e.target.closest("[data-src]");
      if (!b) { return; }
      source = b.getAttribute("data-src");
      Array.prototype.forEach.call(f.querySelectorAll("[data-src]"), function (x) { x.setAttribute("aria-checked", String(x === b)); });
      f.path.placeholder = source === "file" ? "/var/log/nginx/error.log" : "nginx.service";
    });
    f.preset.addEventListener("change", function () {
      var p = presets.find(function (x) { return x.id === f.preset.value; });
      if (!p) { return; }
      f.path.value = p.source_type === "journal" ? p.unit_name : p.target_path;
      f.sudo.checked = !!p.use_sudo;
    });
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      var p = presets.find(function (x) { return x.id === f.preset.value; });
      var spec = { source: source, name: p && (p.target_path === f.path.value || p.unit_name === f.path.value) ? p.name : "", sudo: f.sudo.checked };
      if (source === "file") { spec.path = f.path.value.trim(); } else { spec.unit = f.path.value.trim(); }
      var btn = $("button[type=submit]", f);
      btn.classList.add("is-busy");
      NB.api("logs.start", { log: spec }).then(function (r) {
        btn.classList.remove("is-busy");
        if (!r.ok) { NB.toast(r.error); return; }
        active = r.data.id;
        buffers[active] = buffers[active] || [];
        load();
      });
    });
    list = null;
    if (s) {
      var vp = $(".lg-list", host);
      list = new NB.VList(vp, { rowHeight: ROW, render: rowHtml, overscan: 30 });
      vp.addEventListener("scroll", function () {
        var atEnd = vp.scrollTop + vp.clientHeight >= vp.scrollHeight - ROW * 2;
        if (atEnd !== follow) { follow = atEnd; var b = $(".lg-follow", host); if (b) { b.hidden = follow; } }
      }, { passive: true });
      var q = $(".lg-search", host);
      q.addEventListener("input", function () { query = q.value.trim().toLowerCase(); refilter(); });
      refilter();
    }
  }

  NB.on("logs.lines", function (p) {
    var b = buffers[p.id] || (buffers[p.id] = []);
    Array.prototype.push.apply(b, p.rows);
    if (b.length > MAX) { b.splice(0, b.length - MAX); }
    if (p.skipped) { skipped[p.id] = (skipped[p.id] || 0) + p.skipped; }
    if (host && p.id === active) { refilter(); }
  });
  NB.on("logs.changed", function () { if (host) { load(); } });
  NB.on("conn", function () { if (host) { load(); } });

  NB.screens.logs = {
    ready: true,
    render: function (el) {
      host = el;
      render();
      load();
      el.addEventListener("click", function (e) {
        var b = e.target.closest("[data-a],[data-pick],[data-close],[data-level]");
        if (!b) { return; }
        var id;
        if ((id = b.getAttribute("data-pick"))) { active = id; follow = true; render(); return; }
        if ((id = b.getAttribute("data-close"))) {
          var x = stream(id);
          var go = function () { NB.api("logs.stop", { id: id, remove: true }).then(function () { delete buffers[id]; if (active === id) { active = null; } load(); }); };
          if (x) { go(); }
          return;
        }
        if (b.hasAttribute("data-level")) { level = b.getAttribute("data-level"); render(); return; }
        var a = b.getAttribute("data-a"), s = stream(active);
        if (a === "pause" && s) { NB.api("logs.pause", { id: active, paused: s.status !== "paused" }); }
        else if (a === "clear") { buffers[active] = []; skipped[active] = 0; refilter(); }
        else if (a === "follow") { follow = true; b.hidden = true; if (list) { list.vp.scrollTop = list.vp.scrollHeight; } }
      });
    },
    leave: function () { host = null; list = null; }
  };
})();
