// Services: systemd units on the connected server. Failed ones first; start, stop, restart, reload and boot
// on/off with sudo -n (the server's own refusal is shown, nothing is retried with a typed password). Stopping or
// restarting the SSH service warns first, because it can cut off this connection.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, esc = NB.esc;
  var host = null, inv = null, error = null, filter = "all", query = "", selected = null, detail = null, errorsOnly = false, loading = false;
  var FILTERS = [["all", "All"], ["running", "Running"], ["failed", "Failed"], ["stopped", "Stopped"]];

  function state(u) { return u.failed ? ["bad", "Failed"] : u.running ? ["ok", "Running"] : u.active === "activating" ? ["busy", "Starting"] : ["", "Stopped"]; }
  function isSsh(name) { return /^(ssh|sshd|openssh-server)(\.service)?$/.test(name); }

  function load() {
    if (NB.conn.status !== "connected") { inv = null; render(); return; }
    loading = true;
    render();
    NB.api("svc.list").then(function (r) {
      loading = false;
      if (!r.ok) { error = r.error; inv = null; render(); return; }
      error = null;
      inv = r.data;
      render();
      if (selected) { openUnit(selected); }
    });
  }
  function visible() {
    var q = query.toLowerCase();
    return (inv ? inv.services : []).filter(function (u) {
      if (filter === "running" && !u.running) { return false; }
      if (filter === "failed" && !u.failed) { return false; }
      if (filter === "stopped" && (u.running || u.failed)) { return false; }
      return !q || (u.name + " " + u.description).toLowerCase().indexOf(q) >= 0;
    });
  }
  function render() {
    if (!host) { return; }
    var head = '<div class="screen-head"><div><h1>Services</h1><p>' + (inv ? inv.total + " services · " + inv.running + " running · " + inv.failed + " failed · " + inv.enabled + " start at boot"
      : "Start, stop and read the logs of systemd services on the connected server.") + "</p></div>" +
      '<div class="head-actions"><button type="button" data-a="new">' + ICO("plus") + "New service</button><button type=\"button\" data-a=\"reload\" title=\"systemctl daemon-reload\">Reload unit files</button>" +
      '<button type="button" data-a="refresh" class="' + (loading ? "is-busy" : "") + '">' + ICO("refresh") + "Refresh</button></div></div>";
    if (NB.conn.status !== "connected") {
      host.innerHTML = head + '<div class="empty"><div class="empty-ico">' + ICO("services") + "</div><h2>Connect to a server</h2><p>Services lists the systemd units of the connected server over SSH.</p>" +
        '<div class="actions"><button type="button" class="pri" data-go="connections">' + ICO("servers") + "Connections</button></div></div>";
      return;
    }
    if (error && !inv) { host.innerHTML = head + '<p class="banner warn">' + ICO("warn") + "<span>" + esc(error) + "</span></p>"; return; }
    var rows = visible();
    host.innerHTML = head + (inv && !inv.root ? '<p class="faint sv-note">Actions run with <span class="mono">sudo -n</span>. If this server asks for a sudo password, actions fail with that reason; allow passwordless sudo for systemctl, or connect as a user who may manage services.</p>' : "") +
      '<div class="sv-grid"><section class="card sv-list"><div class="sv-tools"><input type="search" class="sv-search" placeholder="Search services…" aria-label="Search services" value="' + esc(query) + '">' +
      '<div class="seg sm" role="radiogroup" aria-label="Show">' + FILTERS.map(function (f) {
        var n = !inv ? "" : f[0] === "all" ? inv.total : f[0] === "running" ? inv.running : f[0] === "failed" ? inv.failed : inv.stopped;
        return '<button type="button" role="radio" data-filter="' + f[0] + '" aria-checked="' + (f[0] === filter) + '">' + f[1] + ' <span class="num faint">' + n + "</span></button>"; }).join("") + "</div></div>" +
      '<div class="sv-rows" role="listbox" aria-label="Services">' + (inv ? (rows.map(function (u) {
        var st = state(u), on = u.name === selected;
        return '<button type="button" role="option" class="sv-row' + (on ? " on" : "") + '" data-unit="' + esc(u.name) + '" aria-selected="' + on + '">' +
          '<span class="dot ' + st[0] + '" aria-hidden="true"></span><span class="sv-main"><b class="mono">' + esc(u.name.replace(/\.service$/, "")) + "</b><small>" + esc(u.description) + "</small></span>" +
          '<span class="chip ' + st[0] + '">' + st[1] + "</span>" + (u.enabled ? '<span class="chip">At boot</span>' : "<span></span>") + "</button>";
      }).join("") || '<p class="faint sv-empty">No service matches.</p>') : '<div class="pane-loading"><div class="skel" style="height:12px;width:70%"></div><div class="skel" style="height:12px;width:50%"></div></div>') + "</div></section>" +
      '<section class="card sv-detail" aria-live="polite"></section></div>';
    var s = $(".sv-search", host);
    s.addEventListener("input", function () { query = s.value; var pos = s.selectionStart; render(); var t = $(".sv-search", host); t.focus(); t.setSelectionRange(pos, pos); });
    renderDetail();
  }
  function openUnit(name) {
    selected = name;
    detail = null;
    if (host) { Array.prototype.forEach.call(host.querySelectorAll(".sv-row"), function (b) { var on = b.getAttribute("data-unit") === name; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); }); }
    renderDetail();
    NB.api("svc.details", { name: name, lines: 120, errors_only: errorsOnly }).then(function (r) {
      if (selected !== name) { return; }
      detail = r.ok ? r.data : { error: r.error };
      renderDetail();
    });
  }
  function fmtMem(v) { var n = Number(v); return n > 0 ? NB.humanSize(n) : "—"; }
  function renderDetail() {
    var box = host && $(".sv-detail", host);
    if (!box) { return; }
    var u = inv && inv.services.find(function (x) { return x.name === selected; });
    if (!u) { box.innerHTML = '<div class="vd-empty"><p class="muted">Choose a service to see its status and logs.</p></div>'; return; }
    var st = state(u);
    var acts = (u.running ? [["restart", "Restart"], ["reload", "Reload"], ["stop", "Stop"]] : [["start", "Start"]]).map(function (a) {
      return '<button type="button" class="sm' + (a[0] === "stop" ? " danger" : a[0] === "start" || a[0] === "restart" ? " pri" : "") + '" data-act="' + a[0] + '">' + a[1] + "</button>"; }).join("") +
      '<button type="button" class="sm ghost" data-act="' + (u.enabled ? "disable" : "enable") + '">' + (u.enabled ? "Don't start at boot" : "Start at boot") + "</button>";
    var p = detail && detail.props;
    box.innerHTML = '<div class="vd-head"><div><h2 class="mono">' + esc(u.name) + '</h2><span class="chip ' + st[0] + '">' + st[1] + "</span> <span class=\"faint\">" + esc(u.sub) + "</span></div></div>" +
      '<p class="muted sv-desc">' + esc(u.description) + "</p>" + '<div class="sv-acts">' + acts + "</div>" +
      (detail && detail.error ? '<p class="banner warn">' + ICO("warn") + "<span>" + esc(detail.error) + "</span></p>" : "") +
      (p ? '<dl class="dp-facts sv-facts"><div><dt>Main process</dt><dd class="num">' + esc(p.MainPID && p.MainPID !== "0" ? p.MainPID : "—") + "</dd></div>" +
        "<div><dt>Memory</dt><dd class=\"num\">" + fmtMem(p.MemoryCurrent) + "</dd></div><div><dt>Restarts when it stops</dt><dd>" + esc(p.Restart || "—") + "</dd></div>" +
        "<div><dt>Tasks</dt><dd class=\"num\">" + esc(p.TasksCurrent && p.TasksCurrent !== "[not set]" ? p.TasksCurrent : "—") + "</dd></div>" +
        '<div class="wide"><dt>Runs</dt><dd class="mono">' + esc((p.ExecStart.match(/argv\[\]=([^;]*)/) || [null, p.ExecStart])[1] || "—") + "</dd></div></dl>" : '<div class="skel" style="height:12px;width:60%"></div>') +
      '<div class="vp-head sv-logs-head"><b>Recent log</b><label class="check"><input type="checkbox" data-a="errors"' + (errorsOnly ? " checked" : "") + "><span>Errors only</span></label>" +
      '<button type="button" class="sm ghost" data-a="logs">' + ICO("refresh") + "Reload</button></div>" +
      (detail && detail.logs_note ? '<p class="faint">' + esc(detail.logs_note) + "</p>" : "") +
      '<div class="sv-log mono" tabindex="0" aria-label="Log lines">' + (detail && detail.logs ? (detail.logs.map(function (l) {
        return '<div class="' + (l.is_error ? "bad" : "") + '"><span class="faint">' + esc(l.timestamp) + "</span> " + esc(l.message) + "</div>"; }).join("") || '<p class="faint">No log lines.</p>') : "") + "</div>";
    var log = $(".sv-log", box);
    if (log) { log.scrollTop = log.scrollHeight; }
  }
  function act(action, btn) {
    var go = function () {
      btn.classList.add("is-busy");
      NB.api("svc.action", { name: selected, action: action }).then(function (r) {
        btn.classList.remove("is-busy");
        NB.toast(r.ok ? action.charAt(0).toUpperCase() + action.slice(1) + ": " + selected.replace(/\.service$/, "") : r.error, r.ok ? "ok" : "");
        load();
      });
    };
    if ((action === "stop" || action === "restart") && isSsh(selected)) {
      NB.confirm({ title: (action === "stop" ? "Stop" : "Restart") + " the SSH service?", danger: true, action: action === "stop" ? "Stop SSH" : "Restart SSH",
        text: "This app reaches the server through SSH. " + (action === "stop" ? "Stopping it cuts off this connection, and you may need another way in to start it again." : "Restarting it can drop this connection for a moment.") })
        .then(function (yes) { if (yes) { go(); } });
      return;
    }
    if (action === "stop") {
      NB.confirm({ title: "Stop " + selected.replace(/\.service$/, "") + "?", danger: true, action: "Stop", text: "Whatever this service does stops until it is started again." })
        .then(function (yes) { if (yes) { go(); } });
      return;
    }
    go();
  }
  function newUnit() {
    var f = document.createElement("form");
    f.className = "conn-form";
    f.setAttribute("novalidate", "");
    f.innerHTML = '<label class="field wide"><span>Name</span><input name="name" class="mono" autocomplete="off" spellcheck="false" placeholder="my-api…"></label>' +
      '<label class="field wide"><span>Unit file</span><textarea name="content" rows="12" class="mono sv-unit" spellcheck="false"></textarea></label>' +
      '<label class="check wide"><input type="checkbox" name="start" checked><span>Start it now and at every boot</span></label>' +
      '<p class="form-error" role="alert" hidden></p><div class="modal-actions"><button type="button" data-a="cancel">Cancel</button><button type="submit" class="pri">Install</button></div>';
    f.content.value = "[Unit]\nDescription=My API\nAfter=network.target\n\n[Service]\nType=simple\nUser=www-data\nWorkingDirectory=/srv/my-api\nExecStart=/srv/my-api/run\nRestart=on-failure\n\n[Install]\nWantedBy=multi-user.target\n";
    var m = NB.modal({ title: "New service", sub: "Saved as /etc/systemd/system/<name>.service, then systemd reloads its unit files.", body: f, className: "wide", initialFocus: "[name=name]" });
    f.addEventListener("click", function (e) { if (e.target.closest("[data-a=cancel]")) { m.close(); } });
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = $("button[type=submit]", f);
      btn.classList.add("is-busy");
      NB.api("svc.install", { name: f.name.value, content: f.content.value, start: f.start.checked }).then(function (r) {
        btn.classList.remove("is-busy");
        if (!r.ok) { var er = $(".form-error", f); er.textContent = r.error; er.hidden = false; return; }
        m.close();
        NB.toast("Installed " + f.name.value, "ok");
        load();
      });
    });
  }

  NB.on("conn", function () { inv = null; selected = null; detail = null; error = null; if (host) { load(); } });

  NB.screens.services = {
    ready: true,
    render: function (el) {
      host = el;
      render();
      load();
      el.addEventListener("click", function (e) {
        var b = e.target.closest("[data-a],[data-unit],[data-filter],[data-act],[data-go]");
        if (!b) { return; }
        if (b.hasAttribute("data-go")) { NB.go(b.getAttribute("data-go")); return; }
        if (b.hasAttribute("data-unit")) { openUnit(b.getAttribute("data-unit")); return; }
        if (b.hasAttribute("data-filter")) { filter = b.getAttribute("data-filter"); render(); return; }
        if (b.hasAttribute("data-act")) { act(b.getAttribute("data-act"), b); return; }
        var a = b.getAttribute("data-a");
        if (a === "refresh") { load(); }
        else if (a === "logs") { openUnit(selected); }
        else if (a === "errors") { errorsOnly = b.checked; openUnit(selected); }
        else if (a === "new") { newUnit(); }
        else if (a === "reload") { NB.api("svc.reload").then(function (r) { NB.toast(r.ok ? "systemd reloaded its unit files" : r.error, r.ok ? "ok" : ""); }); }
      });
    },
    leave: function () { host = null; }
  };
})();
