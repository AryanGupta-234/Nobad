// Server health: CPU, memory, disks, network and the busiest processes on the connected server.
// Sampling runs only while this screen is open (the page renews its watch every 10 s, and the app stops by itself
// when the renewals stop). Charts are single-series sparklines (the tile's title names the series) with a
// crosshair readout; meters carry status colour plus a written level, never colour alone.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, esc = NB.esc;
  var KEEP = 60, RENEW = 10000;
  var host = null, timer = null, interval = NB.uiState("health-interval") || 2, paused = false;
  var hist = { cpu: [], mem: [], rx: [], tx: [] }, last = null, error = null, dirs = null, procFilter = "";

  function pct(n) { return (Math.round(n * 10) / 10).toFixed(n >= 10 ? 0 : 1) + "%"; }
  function size(n) { return NB.humanSize(Math.max(0, Math.round(n || 0))); }
  function rate(n) { return size(n) + "/s"; }
  function uptime(s) {
    var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
    return (d ? d + "d " : "") + (d || h ? h + "h " : "") + m + "m";
  }
  function level(p) { return p >= 90 ? ["bad", "Critical"] : p >= 75 ? ["warn", "High"] : ["ok", "OK"]; }

  // ---------------------------------------------------------------- watch lease
  function watch(on) {
    if (NB.conn.status !== "connected") { return; }
    NB.api("health.watch", { on: on, interval: interval }).then(function (r) {
      if (!r.ok) { error = r.error; render(); }
    });
  }
  function start() {
    stop();
    if (paused) { return; }
    watch(true);
    timer = setInterval(function () { watch(true); }, RENEW);
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  // ---------------------------------------------------------------- sparkline (one series, 2px line, crosshair)
  function spark(key, values, max) {
    var w = 240, h = 48, n = values.length;
    if (n < 2) { return '<div class="hp-spark empty" aria-hidden="true"></div>'; }
    var top = max || Math.max.apply(null, values.concat([1])) * 1.15;
    var pts = values.map(function (v, i) { return [(i / (KEEP - 1)) * w + (KEEP - n) / (KEEP - 1) * w, h - 2 - (v / top) * (h - 6)]; });
    var d = pts.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join("");
    var lastP = pts[n - 1];
    return '<div class="hp-spark" data-spark="' + key + '"><svg viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none" aria-hidden="true">' +
      '<line class="hp-base" x1="0" y1="' + (h - 1) + '" x2="' + w + '" y2="' + (h - 1) + '"/>' +
      '<path class="hp-line" d="' + d + '"/><circle class="hp-now" cx="' + lastP[0].toFixed(1) + '" cy="' + lastP[1].toFixed(1) + '" r="3"/>' +
      '<line class="hp-cross" x1="0" y1="0" x2="0" y2="' + h + '" hidden/></svg><div class="hp-tip" hidden></div></div>';
  }
  function bindSparks() {
    Array.prototype.forEach.call(host.querySelectorAll("[data-spark]"), function (el) {
      var key = el.getAttribute("data-spark"), svg = el.querySelector("svg"), cross = el.querySelector(".hp-cross"), tip = el.querySelector(".hp-tip");
      var move = function (e) {
        var vals = hist[key], n = vals.length, box = svg.getBoundingClientRect();
        var x = Math.max(0, Math.min(box.width, e.clientX - box.left)), slot = Math.round(x / box.width * (KEEP - 1));
        var i = Math.max(0, Math.min(n - 1, slot - (KEEP - n)));
        var sx = ((i + KEEP - n) / (KEEP - 1)) * 240;
        cross.setAttribute("x1", sx); cross.setAttribute("x2", sx); cross.hidden = false;
        var ago = (n - 1 - i) * interval;
        tip.textContent = FMT[key](vals[i]) + " · " + (ago ? ago + " s ago" : "now");
        tip.hidden = false;
        tip.style.left = Math.min(box.width - 110, Math.max(0, (sx / 240) * box.width - 50)) + "px";
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerleave", function () { cross.hidden = true; tip.hidden = true; });
    });
  }
  var FMT = { cpu: pct, mem: pct, rx: rate, tx: rate };

  // ---------------------------------------------------------------- render
  function tile(label, value, sub, key, values, max) {
    return '<div class="card hp-tile"><span class="hp-label">' + label + '</span><b class="hp-value num">' + value + "</b>" +
      '<span class="hp-sub faint num">' + sub + "</span>" + spark(key, values, max) + "</div>";
  }
  function meter(name, used, total, extra) {
    var p = total ? used / total * 100 : 0, lv = level(p);
    return '<div class="hp-meter"><span class="hp-mname mono" title="' + esc(name) + '"><bdi>' + esc(name) + "</bdi></span>" +
      '<span class="hp-bar ' + lv[0] + '" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + Math.round(p) + '" aria-label="' + esc(name) + " " + Math.round(p) + '% used"><i style="width:' + Math.min(100, p).toFixed(1) + '%"></i></span>' +
      '<span class="hp-mval num">' + pct(p) + ' <span class="faint">' + size(used) + " of " + size(total) + "</span>" + (extra || "") + "</span>" +
      (lv[0] !== "ok" ? '<span class="chip ' + lv[0] + '">' + ICO("warn") + lv[1] + "</span>" : '<span></span>') + "</div>";
  }
  function render() {
    if (!host) { return; }
    var focused = document.activeElement && document.activeElement.classList.contains("hp-filter") ? document.activeElement.selectionStart : null;
    paint();
    var g = focused != null && $(".hp-filter", host);
    if (g) { g.focus(); g.setSelectionRange(focused, focused); }
  }
  // One persistent child of the screen: the entrance animation (.screen>*) plays once, not on every sample.
  function frame() {
    var f = host.querySelector(":scope > .hp-frame");
    if (!f) { host.innerHTML = '<div class="hp-frame"></div>'; f = host.firstChild; }
    return f;
  }
  function paint() {
    var head = '<div class="screen-head"><div><h1>Server health</h1><p>' + (last ? esc(last.os_name) + (last.kernel_version ? " · kernel " + esc(last.kernel_version) : "") + " · up " + uptime(last.uptime_seconds)
      : "CPU, memory, disks and the busiest processes on the connected server.") + "</p></div>" +
      '<div class="head-actions"><div class="seg sm" role="radiogroup" aria-label="Refresh every">' + [1, 2, 5, 10].map(function (s) {
        return '<button type="button" role="radio" data-int="' + s + '" aria-checked="' + (s === interval) + '">' + s + " s</button>"; }).join("") + "</div>" +
      '<button type="button" data-a="pause">' + (paused ? ICO("play") + "Resume" : "Pause") + "</button></div></div>";
    if (NB.conn.status !== "connected") {
      frame().innerHTML = head + '<div class="empty"><div class="empty-ico">' + ICO("pulse") + "</div><h2>Connect to a server</h2><p>Server health reads the connected Linux server over SSH, only while this screen is open.</p>" +
        '<div class="actions"><button type="button" class="pri" data-go="connections">' + ICO("servers") + "Connections</button></div></div>";
      return;
    }
    if (!last) {
      frame().innerHTML = head + (error ? '<p class="banner warn">' + ICO("warn") + "<span>" + esc(error) + "</span></p>" :
        '<div class="hp-tiles">' + [0, 1, 2, 3].map(function () { return '<div class="card hp-tile"><div class="skel" style="height:12px;width:40%"></div><div class="skel" style="height:26px;width:60%;margin-top:10px"></div></div>'; }).join("") + "</div>");
      return;
    }
    var s = last, memP = s.mem_total_bytes ? s.mem_used_bytes / s.mem_total_bytes * 100 : 0;
    var procs = s.processes.filter(function (p) { return !procFilter || (p.command + " " + p.user + " " + p.pid).toLowerCase().indexOf(procFilter) >= 0; });
    frame().innerHTML = head + (error ? '<p class="banner warn hp-err">' + ICO("warn") + "<span>" + esc(error) + " Retrying…</span></p>" : "") +
      '<div class="hp-tiles">' +
      tile("CPU", pct(s.cpu_percent), s.cpu_cores + " cores · load " + s.load_avg.map(function (x) { return x.toFixed(2); }).join(" "), "cpu", hist.cpu, 100) +
      tile("Memory", pct(memP), size(s.mem_used_bytes) + " of " + size(s.mem_total_bytes) + (s.swap_total_bytes ? " · swap " + size(s.swap_used_bytes) : ""), "mem", hist.mem, 100) +
      tile("Download", rate(s.net_rx_rate_bytes_per_sec), esc(s.net_interface || "network") + " · " + size(s.net_total_rx_bytes) + " total", "rx", hist.rx) +
      tile("Upload", rate(s.net_tx_rate_bytes_per_sec), esc(s.net_interface || "network") + " · " + size(s.net_total_tx_bytes) + " total", "tx", hist.tx) +
      "</div>" +
      '<div class="hp-cols"><section class="card hp-disks"><div class="vp-head"><b>Disks</b><button type="button" class="sm ghost" data-a="dirs">' + ICO("search") + "Find big folders</button></div>" +
      meter("Memory", s.mem_used_bytes, s.mem_total_bytes) +
      s.mounts.map(function (m) { return meter(m.mount_point, m.used_bytes, m.total_bytes); }).join("") +
      (dirs ? '<div class="hp-dirs"><b class="faint">Largest in /var and /home</b>' + (dirs.length ? dirs.map(function (d) {
        return '<div class="hp-dir"><span class="num">' + esc(d.size_formatted) + '</span><span class="mono" title="' + esc(d.path) + '"><bdi>' + esc(d.path) + '</bdi></span><span class="faint">' + esc(d.description) + "</span></div>"; }).join("")
        : '<p class="faint">Nothing readable there for this user.</p>') + "</div>" : "") + "</section>" +
      '<section class="card hp-procs"><div class="vp-head"><b>Busiest processes</b><input type="search" class="hp-filter" placeholder="Filter…" aria-label="Filter processes" value="' + esc(procFilter) + '"></div>' +
      '<table class="hp-table"><thead><tr><th scope="col">PID</th><th scope="col">User</th><th scope="col" class="r">CPU</th><th scope="col" class="r">Memory</th><th scope="col">Command</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody>' +
      procs.map(function (p) {
        return '<tr><td class="num">' + p.pid + "</td><td>" + esc(p.user) + '</td><td class="num r">' + pct(p.cpu_percent) + '</td><td class="num r">' + pct(p.mem_percent) +
          '</td><td class="mono hp-cmd" title="' + esc(p.command) + '">' + esc(p.command) + (p.status !== "Running" && p.status !== "Sleep" ? ' <span class="chip warn">' + esc(p.status) + "</span>" : "") +
          '</td><td><button type="button" class="sm ghost" data-kill="' + p.pid + '" data-cmd="' + esc(p.command) + '" aria-label="Stop process ' + p.pid + '">Stop</button></td></tr>';
      }).join("") + "</tbody></table></section></div>";
    bindSparks();
    var f = $(".hp-filter", host);
    f.addEventListener("input", function () { procFilter = f.value.trim().toLowerCase(); render(); });
  }
  function push(key, v) { hist[key].push(v); if (hist[key].length > KEEP) { hist[key].shift(); } }

  function kill(pid, cmd) {
    var body = document.createElement("div");
    body.innerHTML = '<p class="muted">Process <b class="num">' + pid + '</b> runs <span class="mono">' + esc(cmd) + "</span>. Stopping it asks it to quit; forcing it ends it at once and may lose unsaved work.</p>" +
      '<div class="modal-actions"><button type="button" data-a="no">Cancel</button><button type="button" class="danger" data-a="force">Force stop</button><button type="button" class="danger" data-a="term">Stop</button></div>';
    var m = NB.modal({ title: "Stop process " + pid + "?", body: body, initialFocus: "[data-a=no]" });
    body.addEventListener("click", function (e) {
      var b = e.target.closest("[data-a]");
      if (!b) { return; }
      m.close();
      if (b.getAttribute("data-a") === "no") { return; }
      NB.api("health.kill", { pid: pid, force: b.getAttribute("data-a") === "force" }).then(function (r) { NB.toast(r.ok ? r.data.message : r.error, r.ok ? "ok" : ""); });
    });
  }

  NB.on("health.sample", function (s) {
    last = s;
    error = null;
    push("cpu", s.cpu_percent);
    push("mem", s.mem_total_bytes ? s.mem_used_bytes / s.mem_total_bytes * 100 : 0);
    push("rx", s.net_rx_rate_bytes_per_sec);
    push("tx", s.net_tx_rate_bytes_per_sec);
    render();
  });
  NB.on("health.error", function (p) { error = p.message; render(); });
  NB.on("health.dirs", function (p) { dirs = p.dirs; render(); });
  NB.on("task_done", function (p) { if (p.key === "health.scan" && p.error) { NB.toast(p.error); } });
  NB.on("conn", function () { last = null; error = null; dirs = null; hist = { cpu: [], mem: [], rx: [], tx: [] }; if (host) { render(); start(); } });

  NB.screens.dashboard = {
    ready: true,
    render: function (el) {
      host = el;
      render();
      start();
      el.addEventListener("click", function (e) {
        var b = e.target.closest("[data-a],[data-int],[data-kill],[data-go]");
        if (!b) { return; }
        if (b.hasAttribute("data-go")) { NB.go(b.getAttribute("data-go")); return; }
        if (b.hasAttribute("data-int")) { interval = Number(b.getAttribute("data-int")); NB.uiState("health-interval", interval); start(); render(); return; }
        if (b.hasAttribute("data-kill")) { kill(Number(b.getAttribute("data-kill")), b.getAttribute("data-cmd")); return; }
        var a = b.getAttribute("data-a");
        if (a === "pause") { paused = !paused; if (paused) { stop(); NB.api("health.watch", { on: false }); } else { start(); } render(); }
        else if (a === "dirs") { b.classList.add("is-busy"); NB.api("health.scan").then(function (r) { if (!r.ok) { NB.toast(r.error); } }); }
      });
    },
    leave: function () { stop(); NB.api("health.watch", { on: false }); host = null; }
  };
})();
