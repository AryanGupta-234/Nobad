// Deployments: build (optional), preview what changes on the server, then deploy with a backup, the job's
// commands and health checks, and automatic rollback when any step fails. Each stage lights up in the pipeline as
// the app reports it. History lists every run with its stages; backups and releases can be restored.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, $$ = NB.$$, esc = NB.esc;
  var ROW = 40;
  var STEPS = [
    ["build", "Build", "code", ["building"]],
    ["compare", "Compare", "eye", ["validating", "previewing"]],
    ["lock", "Lock", "vault", ["locking"]],
    ["backup", "Back up", "download", ["backing_up", "preparing_release"]],
    ["upload", "Upload", "upload", ["transferring", "deleting", "chmod"]],
    ["commands", "Commands", "terminal", ["post_deploy", "switching_release", "cache_clear", "restart"]],
    ["check", "Check", "pulse", ["health_check"]],
    ["done", "Live", "check", ["completed", "pruning_backups", "pruning_releases"]]
  ];
  var SECTIONS = [["where", "What and where"], ["build", "Build"], ["server", "On the server"], ["checks", "Checks and backups"]];
  var STATUS = { success: ["ok", "Deployed"], failed: ["bad", "Failed"], cancelled: ["warn", "Cancelled"], rolled_back: ["warn", "Rolled back"],
    rollback_failed: ["bad", "Rollback failed"], running: ["busy", "Running"] };

  var host = null, jobs = [], templates = [], form = null, section = "where", preview = null, entries = [], list = null;
  var pipe = null, output = "", hist = { runs: [], artifacts: [] }, openRun = null, notice = null;

  function blank() {
    var remote = NB.conn.profile ? NB.uiState("path-remote-" + NB.conn.profile.id) : "";
    return { id: null, name: "", template: "Generic Folder", mode: "upload_only", strategy: "in_place", project: "", build_folder: "",
      remote: remote || "", ignore: ".git, .DS_Store, __pycache__", run_build: false, build_command: "", chmod_enabled: false, chmod_mode: "755",
      post_command: "", cache_command: "", restart_command: "", backup_dir: "", backup_retention: 5, release_retention: 5,
      health: { command: "", url: "", origin: "desktop", attempts: 3, timeout: 10, interval: 2, min: 200, max: 399, expect: "", verify_tls: true } };
  }
  function copyJob(j) { var f = JSON.parse(JSON.stringify(j)); f.ignore = (j.ignore || []).join(", "); return f; }
  function when(iso) { if (!iso) { return ""; } var d = new Date(iso); return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }); }

  // ---------------------------------------------------------------- jobs
  function loadJobs() {
    return NB.api("deploy.jobs").then(function (r) {
      if (!r.ok) { return; }
      jobs = r.data.jobs;
      templates = r.data.templates;
      renderJobs();
    });
  }
  function renderJobs() {
    var box = host && $(".dp-jobs-list", host);
    if (!box) { return; }
    var mine = NB.conn.profile ? NB.conn.profile.id : null;
    box.innerHTML = '<button type="button" class="vp-item' + (form.id ? "" : " on") + '" data-job="" aria-current="' + !form.id + '"><span>New deployment</span>' + ICO("plus") + "</button>" +
      jobs.map(function (j) {
        var other = j.profile_id && mine && j.profile_id !== mine;
        return '<button type="button" class="vp-item sync-job' + (j.id === form.id ? " on" : "") + '" data-job="' + esc(j.id) + '" aria-current="' + (j.id === form.id) + '">' +
          '<span class="vi-main"><b>' + esc(j.name) + '</b><small class="mono">' + esc(j.remote) + (other ? " · another server" : "") + "</small></span></button>";
      }).join("") + (jobs.length ? "" : '<p class="faint vp-empty">A deployment remembers its folders, commands and checks, and keeps a history of every run.</p>');
  }
  function pick(id) {
    var j = jobs.find(function (x) { return x.id === id; });
    form = j ? copyJob(j) : blank();
    preview = null; entries = []; pipe = null; output = ""; notice = null; openRun = null;
    renderForm(); renderJobs(); renderRun(); loadHistory();
  }

  // ---------------------------------------------------------------- form
  function inp(name, label, opts) {
    opts = opts || {};
    return '<label class="field' + (opts.wide ? " wide" : "") + '"><span>' + label + (opts.hint ? ' <small class="muted">' + opts.hint + "</small>" : "") + "</span>" +
      (opts.browse ? '<span class="input-row">' : "") + '<input name="' + name + '"' + (opts.mono !== false ? ' class="mono"' : "") + (opts.type ? ' type="' + opts.type + '"' : "") +
      (opts.min != null ? ' min="' + opts.min + '" max="' + opts.max + '"' : "") + ' autocomplete="off" spellcheck="false"' + (opts.ph ? ' placeholder="' + esc(opts.ph) + '"' : "") + ">" +
      (opts.browse ? '<button type="button" data-browse="' + name + '">Browse</button></span>' : "") + "</label>";
  }
  function seg(name, label, options) {
    return '<div class="field"><span id="dpl-' + name + '">' + label + '</span><div class="seg" role="radiogroup" aria-labelledby="dpl-' + name + '">' +
      options.map(function (o) { return '<button type="button" role="radio" data-set="' + name + '" data-val="' + o[0] + '" aria-checked="' + (get(name) === o[0]) + '">' + o[1] + "</button>"; }).join("") + "</div></div>";
  }
  function check(name, label) { return '<label class="check wide"><input type="checkbox" name="' + name + '"' + (get(name) ? " checked" : "") + "><span>" + label + "</span></label>"; }
  function get(name) { var p = name.split("."); return p.length > 1 ? form[p[0]][p[1]] : form[name]; }
  function set(name, value) { var p = name.split("."); if (p.length > 1) { form[p[0]][p[1]] = value; } else { form[name] = value; } }
  function sectionHtml() {
    if (section === "where") {
      return inp("name", "Name", { mono: false, ph: "Shop website…" }) +
        '<label class="field"><span>Start from</span><select name="template">' + templates.map(function (t) {
          return '<option' + (t.name === form.template ? " selected" : "") + ">" + esc(t.name) + "</option>"; }).join("") + "</select></label>" +
        inp("build_folder", "Folder to upload", { browse: true, ph: "C:\\Projects\\shop\\dist…" }) + inp("remote", "Folder on the server", { ph: "/var/www/shop…" }) +
        seg("mode", "Files only on the server", [["upload_only", "Keep them"], ["mirror", "Delete them"]]) +
        seg("strategy", "How files go live", [["in_place", "In place"], ["atomic_release", "New release"]]) +
        inp("ignore", "Skip names", { wide: true, hint: "files or folders, comma separated" }) +
        '<p class="faint wide dp-explain">' + (form.strategy === "atomic_release"
          ? "Each deploy goes into a new release folder; the live folder switches to it only when everything is ready, so visitors never see a half-uploaded site. Rollback switches back."
          : "Files are replaced where they are, after a backup of the folder. If a step fails, the backup is restored.") + "</p>";
    }
    if (section === "build") {
      return check("run_build", "Build on this computer before every preview and deploy") +
        inp("project", "Project folder", { browse: true, hint: "where the build command runs" }) + inp("build_command", "Build command", { ph: "npm run build…" }) +
        '<p class="faint wide dp-explain">The build runs on this computer, and its output shows below while it runs. The folder to upload is usually the build\'s output, like dist.</p>';
    }
    if (section === "server") {
      return inp("post_command", "After upload", { wide: true, ph: "npm ci --omit=dev…" }) + inp("cache_command", "Clear caches", { ph: "php artisan cache:clear…" }) +
        inp("restart_command", "Restart", { ph: "systemctl restart shop…" }) +
        check("chmod_enabled", "Set permissions on the uploaded folder") + inp("chmod_mode", "Permissions", { hint: "octal, like 755" }) +
        '<p class="faint wide dp-explain">Commands run in the folder on the server, in this order. If one fails, the deploy is rolled back.</p>';
    }
    return inp("health.command", "Check command", { hint: "runs on the server; must exit 0", ph: "curl -fsS localhost:3000/health…" }) +
      inp("health.url", "Web address", { ph: "https://shop.example.com/health…" }) +
      seg("health.origin", "Check the address from", [["desktop", "This computer"], ["remote", "The server"]]) +
      inp("health.expect", "Page must contain", { mono: false, hint: "optional" }) +
      inp("health.min", "Good status from", { type: "number", min: 100, max: 599 }) + inp("health.max", "to", { type: "number", min: 100, max: 599 }) +
      inp("health.attempts", "Attempts", { type: "number", min: 1, max: 10 }) + inp("health.timeout", "Timeout (s)", { type: "number", min: 1, max: 300 }) +
      inp("health.interval", "Wait between attempts (s)", { type: "number", min: 0, max: 60 }) +
      check("health.verify_tls", "Check the site's HTTPS certificate") +
      (form.health.verify_tls ? "" : '<p class="banner warn wide">' + ICO("warn") + "<span>Without the certificate check, a wrong or intercepted server can still pass the check.</span></p>") +
      inp("backup_dir", "Backup folder on the server", { hint: "optional; outside the target", ph: "next to the target, in .rfm-backups" }) +
      inp("backup_retention", "Backups to keep", { type: "number", min: 1, max: 50 }) + inp("release_retention", "Releases to keep", { type: "number", min: 1, max: 50 });
  }
  function renderForm() {
    var box = $(".dp-form", host);
    box.innerHTML = '<div class="dp-tabs" role="tablist" aria-label="Deployment settings">' + SECTIONS.map(function (s) {
      return '<button type="button" role="tab" data-section="' + s[0] + '" aria-selected="' + (s[0] === section) + '">' + s[1] + "</button>"; }).join("") + "</div>" +
      '<form novalidate class="sync-fields dp-fields" role="tabpanel">' + sectionHtml() + '<p class="form-error wide" role="alert" hidden></p>' +
      '<div class="sync-actions wide">' + (form.id ? '<button type="button" class="ghost danger-tx" data-a="delete">Delete</button>' : "") +
      '<span class="spacer"></span><button type="button" data-a="save">' + (form.id ? "Save changes" : "Save") + "</button>" +
      '<button type="submit" class="pri" data-a="preview">' + ICO("eye") + "Preview</button></div></form>";
    var f = $("form", box);
    $$("input:not([type=checkbox])", f).forEach(function (i) {
      var v = get(i.name);
      i.value = v == null ? "" : v;
      i.addEventListener("input", function () { set(i.name, i.type === "number" ? (i.value === "" ? "" : Number(i.value)) : i.value); staleIfPreview(); });
    });
    $$("input[type=checkbox]", f).forEach(function (i) {
      i.addEventListener("change", function () { set(i.name, i.checked); staleIfPreview(); if (i.name === "health.verify_tls") { renderForm(); } });
    });
    var t = $("select[name=template]", f);
    if (t) { t.addEventListener("change", function () { applyTemplate(t.value); }); }
    f.addEventListener("submit", function (e) { e.preventDefault(); startPreview($("[data-a=preview]", f)); });
  }
  function applyTemplate(name) {
    var t = templates.find(function (x) { return x.name === name; });
    form.template = name;
    if (t) {
      form.build_command = t.build_command; form.post_command = t.post_command; form.restart_command = t.restart_command;
      form.ignore = t.ignore.join(", "); form.run_build = !!t.build_command;
      if (t.build_folder && form.project) { form.build_folder = form.project.replace(/[\\/]+$/, "") + (form.project.indexOf("\\") >= 0 ? "\\" : "/") + t.build_folder; }
    }
    renderForm();
  }
  function formError(text) {
    var er = host && $(".dp-form .form-error", host);
    if (!er) { if (text) { NB.toast(text); } return; }
    er.textContent = text || "";
    er.hidden = !text;
  }
  function staleIfPreview() { if (preview) { preview = null; entries = []; notice = { kind: "info", text: "Settings changed. Preview again before deploying." }; renderRun(); } }
  function save() {
    NB.api("deploy.save", { job: form }).then(function (r) {
      if (!r.ok) { formError(r.error); return; }
      formError("");
      form.id = r.data.id;
      NB.toast("Saved " + r.data.name, "ok");
      loadJobs().then(function () { renderForm(); loadHistory(); });
    });
  }
  function remove() {
    NB.confirm({ title: "Delete the deployment “" + (form.name || "Untitled deployment") + "”?", danger: true, action: "Delete",
      text: "Only the saved settings are removed. Nothing on the server changes, and its backups stay where they are." }).then(function (yes) {
      if (!yes) { return; }
      NB.api("deploy.delete", { id: form.id }).then(function (r) { if (!r.ok) { NB.toast(r.error); return; } pick(""); loadJobs(); });
    });
  }

  // ---------------------------------------------------------------- pipeline
  function stepOf(stage) { var s = STEPS.find(function (x) { return x[3].indexOf(stage) >= 0; }); return s ? s[0] : null; }
  function newPipe(phase) { return { phase: phase, active: null, done: {}, failed: null, rolling: false, message: "", level: "info" }; }
  function onStage(p) {
    if (!pipe) { pipe = newPipe(p.phase); }
    if (p.phase === "run" && pipe.phase !== "run") { pipe = Object.assign(newPipe("run"), { done: pipe.done }); }
    var step = stepOf(p.stage);
    if (p.stage === "rolling_back") { pipe.rolling = true; pipe.failed = pipe.active; }
    else if (p.stage === "failed" || p.stage === "cancelled") { pipe.failed = pipe.failed || pipe.active; }
    else if (step) {
      if (pipe.active && pipe.active !== step) { pipe.done[pipe.active] = true; }
      pipe.active = step;
      if (step === "done") { pipe.done.done = true; }
    }
    pipe.message = p.message; pipe.level = p.level;
    renderPipe();
  }
  function renderPipe() {
    var box = host && $(".dp-pipe", host);
    if (!box) { return; }
    if (!pipe) { box.hidden = true; return; }
    box.hidden = false;
    var steps = STEPS.filter(function (s) { return s[0] !== "build" || form.run_build; });
    box.innerHTML = '<ol class="dp-steps" aria-label="Deployment progress">' + steps.map(function (s) {
      var st = pipe.failed === s[0] ? "failed" : pipe.done[s[0]] ? "done" : pipe.active === s[0] ? (pipe.failed ? "done" : "active") : "todo";
      return '<li class="dp-step ' + st + '"><span class="dp-dot">' + ICO(st === "done" ? "check" : st === "failed" ? "close" : s[2]) + "</span><span>" + s[1] + "</span>" +
        '<span class="sr-only">' + { done: "done", failed: "failed", active: "in progress", todo: "waiting" }[st] + "</span></li>";
    }).join("") + "</ol>" +
      '<p class="dp-msg ' + (pipe.rolling ? "warn" : pipe.level === "error" ? "bad" : "") + '" aria-live="polite">' + (pipe.rolling ? ICO("warn") + "<span>Rolling back: </span>" : "") + esc(pipe.message || "") + "</p>" +
      (output ? '<details class="dp-out"' + (pipe.active === "build" ? " open" : "") + '><summary>Build output</summary><pre class="mono">' + esc(output.slice(-20000)) + "</pre></details>" : "");
    var pre = $(".dp-out pre", box);
    if (pre) { pre.scrollTop = pre.scrollHeight; }
  }

  // ---------------------------------------------------------------- preview and deploy
  function startPreview(btn) {
    if (NB.conn.status !== "connected") { formError("Connect to the server first."); return; }
    formError("");
    preview = null; entries = []; notice = null; output = "";
    pipe = newPipe("preview");
    renderRun();
    NB.task("deploy.preview", btn, form.run_build ? "Building…" : "Comparing…");
    NB.api("deploy.preview", { job: form }).then(function (r) {
      if (!r.ok) { NB.emit("task_done", { key: "deploy.preview" }); pipe = null; renderRun(); formError(r.error); }
    });
  }
  function label(e) {
    if (e.action === "upload") { return ["up", "Add", "busy"]; }
    if (e.action === "overwrite") { return ["up", "Replace", "warn"]; }
    if (e.action === "delete") { return ["close", "Delete", "bad"]; }
    return ["check", /^Preserved/.test(e.reason) ? "Kept" : "Unchanged", "ok"];
  }
  function rowHtml(i) {
    var e = entries[i], l = label(e), size = e.src != null ? e.src : e.dst;
    return '<div class="sync-row dp-row" role="row"><span class="chip ' + l[2] + '" role="cell">' + ICO(l[0]) + esc(l[1]) + "</span>" +
      '<span class="sync-path mono" role="cell" title="' + esc(e.path) + '"><bdi>' + esc(e.path) + '</bdi></span><span class="sync-why faint" role="cell">' + esc(e.reason) +
      '</span><span class="sync-right num faint" role="cell">' + (size != null ? NB.humanSize(size) : "") + "</span></div>";
  }
  function stat(n, text, kind) { return '<span class="sync-stat st-' + kind + (n ? "" : " zero") + '"><b class="num">' + n.toLocaleString() + "</b> " + text + "</span>"; }
  function renderRun() {
    renderPipe();
    var box = host && $(".dp-preview", host);
    if (!box) { return; }
    list = null;
    var banner = notice ? '<div class="banner ' + notice.kind + ' sync-notice">' + ICO(notice.kind === "ok" ? "check" : notice.kind === "info" ? "info" : "warn") +
      "<div><b>" + esc(notice.title || "") + "</b><span>" + esc(notice.text) + "</span>" + (notice.details ? '<pre class="mono dp-details">' + esc(notice.details) + "</pre>" : "") + "</div></div>" : "";
    if (!preview) { box.hidden = !notice; box.innerHTML = banner; return; }
    var c = preview.counts, changes = c.upload + c.replace + c.delete;
    var cmds = preview.commands.map(function (x) { return '<li class="mono">' + esc(x.command) + "</li>"; }).join("");
    var checks = [];
    if (preview.health.command) { checks.push("a command on the server"); }
    if (preview.health.url) { checks.push(preview.health.url + " from " + (preview.health.origin === "remote" ? "the server" : "this computer")); }
    box.hidden = false;
    box.innerHTML = banner + '<div class="sync-head"><div class="sync-stats">' + stat(c.upload, "to add", "busy") + stat(c.replace, "to replace", "warn") +
      stat(c.delete, "to delete", "bad") + stat(c.same, "unchanged or kept", "ok") + '<span class="faint num">' + (c.bytes ? NB.humanSize(c.bytes) + " to upload" : "") + "</span></div></div>" +
      '<dl class="dp-facts"><div><dt>Target</dt><dd class="mono">' + esc(preview.remote_root) + (preview.target_exists ? "" : ' <span class="chip acc">new folder</span>') + "</dd></div>" +
      "<div><dt>Backup</dt><dd" + (preview.backup ? ' class="mono">' + esc(preview.backup) : ">The folder is new, so a rollback removes it.") + "</dd></div>" +
      "<div><dt>Commands</dt><dd>" + (cmds ? "<ol>" + cmds + "</ol>" : "None") + "</dd></div>" +
      "<div><dt>Checks</dt><dd>" + (checks.length ? esc(checks.join(" and ")) : "None. Without a check, a broken site still counts as deployed.") + "</dd></div></dl>" +
      '<div class="sync-list" role="table" aria-label="Files"></div>' +
      '<div class="sync-foot"><span class="faint">Nothing on the server has changed yet. The plan is checked again under the deployment lock.</span><span class="spacer"></span>' +
      '<button type="button" data-a="again">' + ICO("refresh") + "Preview again</button>" +
      '<button type="button" class="pri" data-a="deploy"' + (changes || preview.commands.length ? "" : " disabled") + ">" + ICO("deploy") + "Deploy</button></div>";
    list = new NB.VList($(".sync-list", box), { rowHeight: ROW, render: rowHtml });
    list.setCount(entries.length);
  }
  function deploy(btn, breakLock, token) {
    var c = preview ? preview.counts : null;
    var go = function () {
      pipe = Object.assign(newPipe("run"), { done: pipe ? pipe.done : {} });
      notice = null;
      renderPipe();
      NB.task("deploy.run", btn, "Deploying…");
      NB.api("deploy.run", { token: token || preview.token, confirmed: true, break_stale_lock: !!breakLock }).then(function (r) {
        if (!r.ok) { NB.emit("task_done", { key: "deploy.run" }); NB.toast(r.error); return; }
        NB.openDock("transfers");
      });
    };
    if (breakLock) { go(); return; }
    var parts = [c.upload + " to add", c.replace + " to replace"];
    if (c.delete) { parts.push(c.delete + " to delete"); }
    NB.confirm({ title: "Deploy “" + (preview.job.name || "Untitled deployment") + "” to " + preview.remote_root + "?", danger: !!(c.replace || c.delete),
      action: "Deploy", text: "Files: " + parts.join(", ") + ". " + (preview.backup ? "A backup is made first. " : "") +
        (preview.commands.length ? preview.commands.length + " command" + (preview.commands.length === 1 ? " runs" : "s run") + " on the server. " : "") +
        "If any step or check fails, the deploy is rolled back." }).then(function (yes) { if (yes) { go(); } });
  }
  function onResult(p) {
    var stale = p.stale_lock;
    if (pipe) { pipe.rolling = false; pipe.message = p.ok ? (p.kind === "rollback" ? "Rollback completed." : "Deployment completed.") : p.message; pipe.level = p.ok ? "info" : p.rolled_back ? "warning" : "error"; }
    if (p.ok) {
      if (pipe) { pipe.done[pipe.active] = true; pipe.active = "done"; pipe.done.done = true; }
      notice = { kind: "ok", title: p.kind === "rollback" ? "Rolled back" : "Deployed",
        text: p.kind === "rollback" ? "The earlier version is live again." : p.uploads + " added, " + p.overwrites + " replaced" + (p.deletes ? ", " + p.deletes + " deleted" : "") + "." +
          (p.health ? " Check: " + p.health.message : "") };
      preview = null; entries = [];
    } else if (p.preview_changed) {
      notice = { kind: "warn", title: "Nothing was deployed", text: "Files changed after the preview. Preview again and check the new plan." };
      preview = null; entries = [];
    } else {
      notice = { kind: p.rollback_error ? "bad" : "warn", title: p.rolled_back ? "Rolled back" : p.cancelled ? "Cancelled" : "Didn't finish",
        text: p.message + (p.rolled_back ? " The site was put back the way it was." : "") + (p.rollback_error ? " Rolling back also failed: " + p.rollback_error : "") + (p.fix ? " " + p.fix : ""),
        details: p.details };
      if (pipe && !pipe.failed) { pipe.failed = pipe.active; }
    }
    if (p.job_id && !form.id) { form.id = p.job_id; loadJobs().then(renderForm); }
    renderRun();
    loadHistory();
    var box = host && $(".dp-preview", host);
    if (box) { box.scrollIntoView({ block: "nearest" }); }
    if (stale) {
      NB.confirm({ title: "Remove the old deployment lock?", danger: true, action: "Remove lock and retry",
        text: "The server has a deployment lock that is more than two hours old, probably left by a run that crashed. Remove it only if no one else is deploying right now." })
        .then(function (yes) {
          if (!yes) { return; }
          if (p.kind === "rollback") { rollback(p.artifact_id, true); } else if (p.token) { deploy(null, true, p.token); }
        });
    }
  }

  // ---------------------------------------------------------------- history and rollback
  function loadHistory() {
    if (!form.id) { hist = { runs: [], artifacts: [] }; renderHistory(); return; }
    NB.api("deploy.history", { id: form.id }).then(function (r) { if (r.ok) { hist = r.data; renderHistory(); } });
  }
  function renderHistory() {
    var box = host && $(".dp-history", host);
    if (!box) { return; }
    if (!form.id) { box.hidden = true; return; }
    box.hidden = false;
    var restoreKind = form.strategy === "atomic_release" ? "release" : "backup";
    box.innerHTML = '<div class="dp-hist-cols"><section><div class="vp-head"><b>History</b></div>' +
      (hist.runs.length ? '<div class="dp-runs">' + hist.runs.map(function (r) {
        var s = STATUS[r.status] || ["", r.status], on = r.id === openRun;
        return '<div class="dp-run' + (on ? " open" : "") + '"><button type="button" class="dp-run-btn" data-run="' + esc(r.id) + '" aria-expanded="' + on + '">' +
          '<span class="chip ' + s[0] + '">' + s[1] + "</span><span>" + (r.action === "manual_rollback" ? "Restore" : "Deploy") + '</span><span class="faint num">' + when(r.started) +
          '</span><span class="faint num" title="' + (r.action === "deploy" ? r.uploads + " added, " + r.overwrites + " replaced, " + r.deletes + " deleted" : "") + '">' +
          (r.action === "deploy" ? (r.uploads + r.overwrites + r.deletes) + " file" + (r.uploads + r.overwrites + r.deletes === 1 ? "" : "s") : "") + "</span>" +
          '<span class="faint num">' + (r.seconds != null ? Math.round(r.seconds) + " s" : "") + "</span></button>" +
          (on ? '<div class="dp-stages" data-stages="' + esc(r.id) + '"><p class="faint">' + esc(r.message || "") + "</p></div>" : "") + "</div>";
      }).join("") + "</div>" : '<p class="faint">No runs yet.</p>') + "</section>" +
      '<section><div class="vp-head"><b>' + (restoreKind === "release" ? "Releases" : "Backups") + '</b><button type="button" class="sm ghost" data-a="scan">' + ICO("refresh") + "Scan server</button></div>" +
      (hist.artifacts.filter(function (a) { return a.kind === restoreKind; }).map(function (a) {
        return '<div class="dp-art"><span class="mono" title="' + esc(a.path) + '"><bdi>' + esc(a.path.split("/").pop()) + '</bdi></span><span class="faint num">' + when(a.created) + "</span>" +
          (a.active ? '<span class="chip ok">Live</span>' : '<button type="button" class="sm" data-restore="' + esc(a.id) + '">Restore</button>') + "</div>";
      }).join("") || '<p class="faint">None recorded. Backups appear after a deploy, or scan the server.</p>') + "</section></div>";
    if (openRun) { loadStages(openRun); }
  }
  function loadStages(id) {
    NB.api("deploy.stages", { run: id }).then(function (r) {
      var box = host && $('[data-stages="' + id + '"]', host);
      if (!r.ok || !box) { return; }
      box.insertAdjacentHTML("beforeend", "<ol>" + r.data.map(function (s) {
        return '<li class="' + (s.level === "error" ? "bad" : s.level === "warning" ? "warn" : "") + '"><b>' + esc(s.stage.replace(/_/g, " ")) + "</b> " + esc(s.message) +
          (s.seconds != null ? ' <span class="faint num">' + s.seconds + " s</span>" : "") + (s.output ? '<pre class="mono">' + esc(s.output) + "</pre>" : "") + "</li>";
      }).join("") + "</ol>");
    });
  }
  function rollback(artifactId, breakLock) {
    var a = hist.artifacts.find(function (x) { return x.id === artifactId; });
    var go = function () {
      pipe = newPipe("run");
      notice = null;
      renderPipe();
      NB.task("deploy.run", null);
      NB.api("deploy.rollback", { id: form.id, artifact: artifactId, confirmed: true, break_stale_lock: !!breakLock }).then(function (r) { if (!r.ok) { NB.toast(r.error); pipe = null; renderPipe(); } });
    };
    if (breakLock) { go(); return; }
    NB.confirm({ title: "Restore " + (a ? a.path.split("/").pop() : "this version") + "?", danger: true, action: "Restore",
      text: "What is live now is kept first, then this " + (a && a.kind === "release" ? "release goes live" : "backup is restored") + ". The restart, cache and health check commands run afterwards." })
      .then(function (yes) { if (yes) { go(); } });
  }

  // ---------------------------------------------------------------- events
  NB.on("deploy.stage", function (p) { if (host) { onStage(p); } else { pipe = pipe || newPipe(p.phase); } });
  NB.on("deploy.output", function (p) { output += p.data; if (output.length > 60000) { output = output.slice(-40000); } if (host) { renderPipe(); } });
  NB.on("deploy.preview", function (p) {
    if (p.cancelled) { pipe = null; renderRun(); return; }
    NB.api("deploy.entries", { token: p.token }).then(function (r) {
      if (!r.ok) { NB.toast(r.error); return; }
      preview = p;
      entries = r.data.slice().sort(function (a, b) {
        var ra = { delete: 0, overwrite: 1, upload: 2 }[a.action], rb = { delete: 0, overwrite: 1, upload: 2 }[b.action];
        return (ra == null ? 9 : ra) - (rb == null ? 9 : rb) || (a.path < b.path ? -1 : 1);
      });
      if (pipe) { pipe.done.build = true; pipe.done.compare = true; pipe.active = null; pipe.message = "Preview ready. Nothing on the server has changed."; }
      renderRun();
    });
  });
  NB.on("deploy.result", function (p) { onResult(p); });
  NB.on("deploy.history", function () { loadHistory(); });
  NB.on("task_done", function (p) {
    if (p.key === "deploy.preview" && p.error) { if (pipe) { pipe.failed = pipe.active || "compare"; pipe.message = p.error; pipe.level = "error"; } renderRun(); formError(p.error); }
    if (p.key === "deploy.scan") { var b = host && $("[data-a=scan]", host); if (b) { b.classList.remove("is-busy"); } if (!p.error) { NB.toast("Scanned the server", "ok"); } }
  });
  NB.on("conn", function () { if (preview) { preview = null; entries = []; renderRun(); } if (host) { renderJobs(); } });

  NB.screens.deploy = {
    ready: true,
    render: function (el) {
      host = el;
      if (!form) { form = blank(); }
      el.innerHTML = '<div class="screen-head"><div><h1>Deployments</h1><p>Upload a site or app with a backup first, run its commands, check that it works, and roll back by itself if anything fails.</p></div>' +
        '<div class="head-actions"><button type="button" data-a="cancel" class="ghost">Cancel running task</button></div></div>' +
        '<div class="sync-grid"><aside class="card vault-projects sync-jobs"><div class="vp-head"><b>Deployments</b></div><div class="vp-list dp-jobs-list"></div></aside>' +
        '<div class="sync-main"><section class="card sync-form dp-form"></section><section class="card dp-pipe" hidden></section>' +
        '<section class="card sync-preview dp-preview" aria-label="Preview" hidden></section><section class="card dp-history" hidden></section></div></div>';
      loadJobs().then(function () { renderForm(); });
      renderForm(); renderJobs(); renderRun(); loadHistory();
      el.addEventListener("click", function (e) {
        var b = e.target.closest("[data-a],[data-job],[data-section],[data-set],[data-browse],[data-run],[data-restore]");
        if (!b) { return; }
        if (b.hasAttribute("data-job")) { pick(b.getAttribute("data-job")); return; }
        if (b.hasAttribute("data-section")) { section = b.getAttribute("data-section"); renderForm(); $("[data-section=" + section + "]", host).focus(); return; }
        if (b.hasAttribute("data-set")) { set(b.getAttribute("data-set"), b.getAttribute("data-val")); staleIfPreview(); renderForm(); return; }
        if (b.hasAttribute("data-browse")) {
          var name = b.getAttribute("data-browse");
          NB.api("window.pick", { kind: "folder", start: get(name) }).then(function (r) {
            if (r.ok && r.data.paths && r.data.paths.length) { set(name, r.data.paths[0]); renderForm(); staleIfPreview(); }
            else if (r.ok && r.data.available === false) { NB.toast("Type the folder path; the folder picker needs the app window."); }
          });
          return;
        }
        if (b.hasAttribute("data-run")) { var id = b.getAttribute("data-run"); openRun = openRun === id ? null : id; renderHistory(); return; }
        if (b.hasAttribute("data-restore")) { rollback(b.getAttribute("data-restore"), false); return; }
        var a = b.getAttribute("data-a");
        if (a === "save") { save(); }
        else if (a === "delete") { remove(); }
        else if (a === "again") { startPreview(b); }
        else if (a === "deploy") { deploy(b, false); }
        else if (a === "cancel") { NB.api("deploy.cancel").then(function () { NB.toast("Cancelling. A deploy that already started is rolled back."); }); }
        else if (a === "scan") {
          b.classList.add("is-busy");
          NB.api("deploy.scan", { id: form.id }).then(function (r) { if (!r.ok) { b.classList.remove("is-busy"); NB.toast(r.error); } });
        }
      });
    },
    leave: function () { host = null; list = null; }
  };
})();
