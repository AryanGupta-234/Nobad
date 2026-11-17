// Playbooks: ready-made maintenance scripts and your own snippets, run on the connected server with live output.
// Values are checked by the app before anything runs (nothing typed can become a command). A script that uses sudo
// asks once per run: the password (answered only to the app's own prompt) or "without a password" (sudo -n).
// Destructive playbooks show the exact script and need a confirmation.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, $$ = NB.$$, esc = NB.esc;
  var host = null, recipes = [], selected = null, values = {}, filter = "all", query = "", running = null, out = "", last = null, xterm = null, fit = null, history = [];
  var SAFETY = { safe: ["ok", "Safe"], sudo: ["warn", "Uses sudo"], destructive: ["bad", "Deletes things"] };
  var FILTERS = [["all", "All"], ["mine", "Mine"], ["security", "Security"], ["maintenance", "Maintenance"], ["network", "Network"], ["docker", "Docker"], ["database", "Database"]];

  function load() {
    return NB.api("pb.list").then(function (r) {
      if (!r.ok) { return; }
      recipes = r.data.recipes;
      running = r.data.running;
      if (!selected || !recipes.some(function (x) { return x.id === selected; })) { selected = recipes.length ? recipes[0].id : null; values = {}; }
      render();
      loadHistory();
    });
  }
  function loadHistory() {
    NB.api("pb.history", { id: selected }).then(function (r) { if (r.ok) { history = r.data; renderHistory(); } });
  }
  function recipe() { return recipes.find(function (x) { return x.id === selected; }); }
  function visible() {
    var q = query.toLowerCase();
    return recipes.filter(function (r) {
      if (filter === "mine" && !r.custom) { return false; }
      if (filter !== "all" && filter !== "mine" && r.category !== filter) { return false; }
      return !q || (r.title + " " + r.description).toLowerCase().indexOf(q) >= 0;
    }).sort(function (a, b) { return (b.favorite - a.favorite) || (b.custom - a.custom); });
  }
  function when(iso) { var d = new Date(iso); return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }); }

  function field(v) {
    var val = values[v.key] != null ? values[v.key] : v.default_value, id = "pbv-" + v.key;
    if (v.var_type === "boolean") {
      return '<label class="check"><input type="checkbox" data-var="' + esc(v.key) + '"' + (String(val) === "true" ? " checked" : "") + "><span>" + esc(v.label) + "</span></label>";
    }
    var input = v.var_type === "choice" ? '<select id="' + id + '" data-var="' + esc(v.key) + '">' + v.options.map(function (o) { return "<option" + (o === val ? " selected" : "") + ">" + esc(o) + "</option>"; }).join("") + "</select>"
      : '<input id="' + id + '" data-var="' + esc(v.key) + '"' + (v.var_type === "number" ? ' type="number" min="0"' : ' class="mono" autocomplete="off" spellcheck="false"') + ' value="' + esc(val) + '">';
    return '<label class="field" for="' + id + '"><span>' + esc(v.label) + (v.description ? ' <small class="muted">' + esc(v.description) + "</small>" : "") + "</span>" + input + "</label>";
  }
  function render() {
    if (!host) { return; }
    var r = recipe(), connected = NB.conn.status === "connected";
    NB.frame(host).innerHTML = '<div class="screen-head"><div><h1>Playbooks</h1><p>Ready-made maintenance scripts and your own snippets, run on the connected server with live output.</p></div>' +
      '<div class="head-actions"><button type="button" data-a="new">' + ICO("plus") + "New snippet</button></div></div>" +
      (connected ? "" : '<p class="banner info">' + ICO("info") + "<span>Connect to an SSH server to run playbooks.</span></p>") +
      '<div class="pb-grid"><aside class="card pb-list"><input type="search" class="pb-search" placeholder="Search playbooks…" aria-label="Search playbooks" value="' + esc(query) + '">' +
      '<div class="pb-filters">' + FILTERS.map(function (f) { return '<button type="button" class="sm' + (f[0] === filter ? " on" : " ghost") + '" data-filter="' + f[0] + '" aria-pressed="' + (f[0] === filter) + '">' + f[1] + "</button>"; }).join("") + "</div>" +
      '<div class="pb-items" role="listbox" aria-label="Playbooks">' + visible().map(function (x) {
        var s = SAFETY[x.safety] || SAFETY.safe, on = x.id === selected;
        return '<button type="button" role="option" class="pb-item' + (on ? " on" : "") + '" data-pick="' + esc(x.id) + '" aria-selected="' + on + '"><span class="vi-main"><b>' + (x.favorite ? "★ " : "") + esc(x.title) + "</b>" +
          "<small>" + (x.last ? (x.last.status === "success" ? "Last run OK · " : "Last run " + x.last.status + " · ") + when(x.last.at) : x.custom ? "Your snippet" : "Not run yet") + '</small></span><span class="chip ' + s[0] + '">' + s[1] + "</span></button>";
      }).join("") + "</div></aside>" +
      '<section class="pb-main">' + (r ? detailHtml(r, connected) : '<div class="card empty"><p>Choose a playbook.</p></div>') +
      '<div class="card pb-run"' + (out || running ? "" : " hidden") + '><div class="pb-run-head"><b>' + (running ? "Running " + esc(running.title) + "…" : last ? esc(last.title) : "Output") + "</b>" +
      (running ? '<span class="chip busy">Running</span><span class="spacer"></span><button type="button" class="sm danger" data-a="cancel">Stop</button>'
        : last ? '<span class="chip ' + (last.ok ? "ok" : last.status === "cancelled" ? "warn" : "bad") + '">' + (last.ok ? "Done" : last.status === "cancelled" ? "Stopped" : "Failed, exit " + last.exit_code) + '</span><span class="faint num">' + (last.ms / 1000).toFixed(1) + " s</span>" : "") +
      '</div><div class="pb-term"></div></div><div class="card pb-history"></div></section></div>';
    var s = $(".pb-search", host);
    s.addEventListener("input", function () { query = s.value; var pos = s.selectionStart; render(); var t = $(".pb-search", host); t.focus(); t.setSelectionRange(pos, pos); });
    $$("[data-var]", host).forEach(function (i) {
      i.addEventListener(i.type === "checkbox" ? "change" : "input", function () { values[i.getAttribute("data-var")] = i.type === "checkbox" ? (i.checked ? "true" : "false") : i.value; });
    });
    mountTerm();
    renderHistory();
  }
  function detailHtml(r, connected) {
    var s = SAFETY[r.safety] || SAFETY.safe;
    return '<div class="card pb-detail"><div class="vd-head"><div><h2>' + esc(r.title) + '</h2><span class="chip ' + s[0] + '">' + s[1] + "</span> <span class=\"chip\">" + esc(r.category) + "</span>" +
      (r.estimate ? ' <span class="faint">' + esc(r.estimate) + "</span>" : "") + "</div>" +
      (r.custom ? '<div class="vd-tools"><button type="button" class="sm ghost" data-a="star">' + (r.favorite ? "Unstar" : "Star") + '</button><button type="button" class="sm" data-a="edit">Edit</button><button type="button" class="sm ghost danger-tx" data-a="delete">Delete</button></div>'
        : '<div class="vd-tools"><button type="button" class="sm ghost" data-a="copy">Save a copy</button></div>') + "</div>" +
      '<p class="muted pb-desc">' + esc(r.description) + "</p>" +
      (r.steps.length ? '<ol class="pb-steps">' + r.steps.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ol>" : "") +
      (r.variables.length ? '<div class="pb-vars">' + r.variables.map(field).join("") + "</div>" : "") +
      '<div class="pb-acts"><button type="button" data-a="review">' + ICO("eye") + "Review script</button><span class=\"spacer\"></span>" +
      '<button type="button" class="pri" data-a="run"' + (connected && !running ? "" : " disabled") + ">" + ICO("play") + "Run</button></div></div>";
  }
  function mountTerm() {
    var box = host && $(".pb-term", host);
    if (!box || !window.Terminal) { return; }
    if (xterm) { xterm.dispose(); }
    xterm = new window.Terminal({ fontFamily: getComputedStyle(document.documentElement).getPropertyValue("--font-mono"), fontSize: 12, scrollback: 5000,
      disableStdin: true, cursorBlink: false, theme: NB.termTheme ? NB.termTheme() : undefined, convertEol: false });
    var FitCls = window.FitAddon && (window.FitAddon.FitAddon || window.FitAddon);
    fit = FitCls ? new FitCls() : null;
    if (fit) { xterm.loadAddon(fit); }
    xterm.open(box);
    if (out) { xterm.write(out); }
    requestAnimationFrame(function () { try { if (fit) { fit.fit(); } } catch (e) { /* hidden */ } });
  }
  function renderHistory() {
    var box = host && $(".pb-history", host);
    if (!box) { return; }
    box.hidden = !history.length;
    box.innerHTML = '<div class="vp-head"><b>Earlier runs</b></div>' + history.slice(0, 10).map(function (h) {
      var st = h.status === "success" ? ["ok", "OK"] : h.status === "cancelled" ? ["warn", "Stopped"] : ["bad", "Failed"];
      return '<details class="pb-hist"><summary><span class="chip ' + st[0] + '">' + st[1] + '</span><span class="faint num">' + when(h.at) + '</span><span class="faint num">' + (h.ms / 1000).toFixed(1) + " s</span>" +
        (h.status === "failed" ? '<span class="faint num">exit ' + h.exit_code + "</span>" : "") + '</summary><pre class="mono">' + esc(h.output.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "").replace(/\r/g, "")) + "</pre></details>";
    }).join("");
  }

  // ---------------------------------------------------------------- run
  function review(then) {
    NB.api("pb.render", { id: selected, values: values }).then(function (r) {
      if (!r.ok) { NB.toast(r.error); return; }
      then(r.data.script);
    });
  }
  function showScript(script, opts) {
    return new Promise(function (resolve) {
      var body = document.createElement("div");
      body.innerHTML = '<pre class="mono pb-script"></pre>' + (opts.extra || "") +
        '<div class="modal-actions"><button type="button" data-a="no">' + (opts.action ? "Cancel" : "Close") + "</button>" +
        (opts.action ? '<button type="button" class="' + (opts.danger ? "danger" : "pri") + '" data-a="yes">' + esc(opts.action) + "</button>" : "") + "</div>";
      $(".pb-script", body).textContent = script;
      var done = false;
      var m = NB.modal({ title: opts.title, sub: opts.sub, body: body, className: "wide pb-modal", initialFocus: "[data-a=no]", onClose: function () { if (!done) { resolve(null); } } });
      body.addEventListener("click", function (e) {
        var b = e.target.closest("[data-a]");
        if (!b) { return; }
        done = true;
        var res = b.getAttribute("data-a") === "yes" ? body : null;
        resolve(res);
        m.close();
      });
    });
  }
  function run() {
    var r = recipe();
    if (!r) { return; }
    review(function (script) {
      var usesSudo = /(^|[^\w-])sudo([^\w-]|$)/.test(script), danger = r.safety === "destructive";
      if (!usesSudo && !danger) { go({}); return; }
      var extra = usesSudo ? '<fieldset class="choice pb-sudo"><legend class="faint">This script uses sudo</legend>' +
        '<label><input type="radio" name="sudo" value="password" checked><span><b>Type the sudo password</b><span class="muted">Used once, for this run. It only answers sudo\'s own prompt and is never saved.</span>' +
        '<input type="password" name="password" autocomplete="off" aria-label="Sudo password"></span></label>' +
        '<label><input type="radio" name="sudo" value="none"><span><b>Run without a password</b><span class="muted">For servers with passwordless sudo. If sudo asks for one, that step fails at once.</span></span></label></fieldset>' : "";
      showScript(script, { title: "Run “" + r.title + "”?", sub: danger ? "This playbook deletes things on the server. This is exactly what will run." : "This is exactly what will run on the server.",
        action: "Run", danger: danger, extra: extra }).then(function (body) {
        if (!body) { return; }
        var opts = { confirmed: danger };
        if (usesSudo) {
          opts.sudo = $("input[name=sudo]:checked", body).value;
          opts.password = opts.sudo === "password" ? $("input[name=password]", body).value : "";
        }
        go(opts);
      });
      if (usesSudo) { setTimeout(function () { var p = $(".modal input[name=password]"); if (p) { p.focus(); } }, 0); }
    });
  }
  function go(opts) {
    out = "";
    last = null;
    NB.api("pb.run", Object.assign({ id: selected, values: values }, opts)).then(function (r) {
      opts.password = "";
      if (!r.ok) { NB.toast(r.error); return; }
    });
  }

  NB.on("pb.started", function (p) { running = p; out = ""; render(); });
  NB.on("pb.out", function (p) { out += p.data; if (out.length > 400000) { out = out.slice(-300000); } if (xterm) { xterm.write(p.data); } });
  NB.on("pb.done", function (p) {
    var r = recipes.find(function (x) { return x.id === p.id; });
    last = Object.assign({ title: r ? r.title : "Playbook" }, p);
    running = null;
    NB.toast(p.ok ? "Playbook finished" : p.message, p.ok ? "ok" : "");
    load();
  });
  NB.on("conn", function () { if (host) { render(); } });
  NB.on("theme", function () { if (xterm && NB.termTheme) { xterm.options.theme = NB.termTheme(); } });

  function editor(existing) {
    var f = document.createElement("form");
    f.className = "conn-form";
    f.setAttribute("novalidate", "");
    f.innerHTML = '<label class="field wide"><span>Name</span><input name="title" autocomplete="off"></label>' +
      '<label class="field wide"><span>What it does <small class="muted">optional</small></span><input name="description" autocomplete="off"></label>' +
      '<label class="field wide"><span>Script <small class="muted">bash; use {{NAME}} for values you fill in before each run</small></span><textarea name="script" rows="12" class="mono sv-unit" spellcheck="false"></textarea></label>' +
      '<label class="field"><span>Safety</span><select name="safety"><option value="safe">Safe</option><option value="sudo">Uses sudo</option><option value="destructive">Deletes things</option></select></label>' +
      '<p class="form-error wide" role="alert" hidden></p><div class="modal-actions wide"><button type="button" data-a="cancel">Cancel</button><button type="submit" class="pri">Save snippet</button></div>';
    if (existing) { f.title.value = existing.title; f.description.value = existing.description; f.script.value = existing.script; f.safety.value = existing.safety; }
    else { f.script.value = "set -e\necho \"Disk use on {{MOUNT}}:\"\ndf -h {{MOUNT}}\n"; }
    var m = NB.modal({ title: existing && existing.custom ? "Edit snippet" : "New snippet", body: f, className: "wide", initialFocus: "[name=title]" });
    f.addEventListener("click", function (e) { if (e.target.closest("[data-a=cancel]")) { m.close(); } });
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      NB.api("pb.save", { recipe: { id: existing && existing.custom ? existing.id : null, title: f.title.value, description: f.description.value, script: f.script.value, safety: f.safety.value } }).then(function (r) {
        if (!r.ok) { var er = $(".form-error", f); er.textContent = r.error; er.hidden = false; return; }
        m.close();
        selected = r.data.id;
        values = {};
        load();
      });
    });
  }

  NB.screens.playbooks = {
    ready: true,
    render: function (el) {
      host = el;
      render();
      load();
      el.addEventListener("click", function (e) {
        var b = e.target.closest("[data-a],[data-pick],[data-filter]");
        if (!b || b.disabled) { return; }
        if (b.hasAttribute("data-pick")) { selected = b.getAttribute("data-pick"); values = {}; render(); loadHistory(); return; }
        if (b.hasAttribute("data-filter")) { filter = b.getAttribute("data-filter"); render(); return; }
        var a = b.getAttribute("data-a"), r = recipe();
        if (a === "run") { run(); }
        else if (a === "review") { review(function (script) { showScript(script, { title: r.title, sub: "This is exactly what would run, with the values above." }); }); }
        else if (a === "cancel") { NB.api("pb.cancel"); }
        else if (a === "new") { editor(null); }
        else if (a === "edit" || a === "copy") { editor(a === "copy" ? Object.assign({}, r, { title: r.title + " (copy)", custom: false }) : r); }
        else if (a === "star") { NB.api("pb.favorite", { id: selected }).then(load); }
        else if (a === "delete") {
          NB.confirm({ title: "Delete the snippet “" + r.title + "”?", danger: true, action: "Delete", text: "Its run history stays." }).then(function (yes) {
            if (yes) { NB.api("pb.delete", { id: selected }).then(function () { selected = null; load(); }); }
          });
        }
      });
    },
    leave: function () { if (xterm) { xterm.dispose(); xterm = null; } host = null; }
  };
})();
