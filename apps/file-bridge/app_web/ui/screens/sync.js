// Sync: keep a folder on this computer and one on the server in step. Every sync starts with a preview (dry run);
// nothing changes until "Sync now", conflicts need a choice per file, and replacing or deleting files is confirmed
// first. The app builds the plan again just before it runs and stops if anything changed meanwhile.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, $$ = NB.$$, esc = NB.esc;
  var ROW = 40;
  var MODES = [
    { id: "local_to_remote", label: "To the server", text: "Copies new and changed files to the server, and deletes files there that aren't on this computer." },
    { id: "remote_to_local", label: "To this computer", text: "Copies new and changed files from the server, and deletes files here that aren't on the server." },
    { id: "two_way", label: "Both ways", text: "Copies changes both ways. Once a saved job has synced, deletions are copied too. Files changed on both sides wait for your choice." }
  ];
  var CHOICE = { use_local: "Keep mine", use_remote: "Keep the server's", keep_both: "Keep both", skip: "Skip for now" };
  var FILTERS = [["changes", "Changes"], ["conflict", "Conflicts"], ["same", "Unchanged"], ["all", "All"]];

  var host = null, jobs = [], form = null, preview = null, entries = [], view = [], decisions = {}, filter = "changes";
  var list = null, progress = null, notice = null;

  function blank() {
    var remote = NB.conn.profile ? NB.uiState("path-remote-" + NB.conn.profile.id) : null;
    return { id: null, name: "", mode: "two_way", local: NB.uiState("path-local") || "", remote: remote || "", ignore: "node_modules, .git, vendor, __pycache__, .venv" };
  }
  function modeOf(id) { return MODES.find(function (m) { return m.id === id; }) || MODES[2]; }

  // ---------------------------------------------------------------- jobs
  function loadJobs() {
    return NB.api("sync.jobs").then(function (r) {
      if (!r.ok) { return; }
      jobs = r.data.jobs;
      renderJobs();
    });
  }
  function renderJobs() {
    var box = host && $(".sync-jobs-list", host);
    if (!box) { return; }
    var mine = NB.conn.profile ? NB.conn.profile.id : null;
    box.innerHTML = '<button type="button" class="vp-item' + (form.id ? "" : " on") + '" data-job="" aria-current="' + !form.id + '"><span>New sync job</span>' + ICO("plus") + "</button>" +
      jobs.map(function (j) {
        var other = j.profile_id && mine && j.profile_id !== mine;
        return '<button type="button" class="vp-item sync-job' + (j.id === form.id ? " on" : "") + '" data-job="' + esc(j.id) + '" aria-current="' + (j.id === form.id) + '">' +
          '<span class="vi-main"><b>' + esc(j.name) + "</b><small>" + esc(modeOf(j.mode).label) + (other ? " · another server" : "") + "</small></span></button>";
      }).join("") + (jobs.length ? "" : '<p class="faint vp-empty">Saved jobs remember their folders, and two-way jobs remember what was synced last time.</p>');
  }
  function pick(id) {
    var j = jobs.find(function (x) { return x.id === id; });
    form = j ? { id: j.id, name: j.name, mode: j.mode, local: j.local, remote: j.remote, ignore: j.ignore.join(", ") } : blank();
    clearPreview();
    renderForm();
    renderJobs();
  }

  // ---------------------------------------------------------------- form
  function renderForm() {
    var box = $(".sync-form", host), m = modeOf(form.mode);
    box.innerHTML = '<form novalidate class="sync-fields">' +
      '<label class="field"><span>Name</span><input name="name" autocomplete="off" placeholder="Website files…"></label>' +
      '<div class="field span2"><span id="syncDirLabel">Which way</span><div class="seg" role="radiogroup" aria-labelledby="syncDirLabel">' +
      MODES.map(function (x) { return '<button type="button" role="radio" data-mode="' + x.id + '" aria-checked="' + (x.id === form.mode) + '">' + esc(x.label) + "</button>"; }).join("") +
      '</div><p class="faint sync-mode-text">' + esc(m.text) + "</p></div>" +
      '<label class="field"><span>Folder on this computer</span><span class="input-row"><input name="local" class="mono" autocomplete="off" spellcheck="false" placeholder="C:\\Sites\\example…">' +
      '<button type="button" data-a="browse">Browse</button></span></label>' +
      '<label class="field"><span>Folder on the server</span><input name="remote" class="mono" autocomplete="off" spellcheck="false" placeholder="/var/www/example…"></label>' +
      '<label class="field"><span>Skip names <small class="muted">files or folders, comma separated</small></span><input name="ignore" class="mono" autocomplete="off" spellcheck="false"></label>' +
      '<p class="form-error wide" role="alert" hidden></p>' +
      '<div class="sync-actions wide">' + (form.id ? '<button type="button" class="ghost danger-tx" data-a="delete">Delete job</button>' : "") +
      '<span class="spacer"></span><button type="button" data-a="save">' + (form.id ? "Save changes" : "Save job") + "</button>" +
      '<button type="submit" class="pri" data-a="preview">' + ICO("eye") + "Preview</button></div></form>";
    var f = $("form", box);
    ["name", "local", "remote", "ignore"].forEach(function (k) {
      f[k].value = form[k] || "";
      f[k].addEventListener("input", function () { form[k] = f[k].value; if (preview) { stale(); } });
    });
    f.addEventListener("submit", function (e) { e.preventDefault(); startPreview($("[data-a=preview]", f)); });
  }
  function spec() { return { id: form.id, name: form.name, mode: form.mode, local: form.local, remote: form.remote, ignore: form.ignore }; }
  function formError(text) {
    var er = host && $(".sync-form .form-error", host);
    if (!er) { NB.toast(text); return; }
    er.textContent = text || "";
    er.hidden = !text;
  }
  function save() {
    NB.api("sync.save", { job: spec() }).then(function (r) {
      if (!r.ok) { formError(r.error); return; }
      formError("");
      form.id = r.data.id;
      NB.toast("Saved " + r.data.name, "ok");
      loadJobs().then(renderForm);
    });
  }
  function remove() {
    NB.confirm({ title: "Delete the sync job “" + (form.name || "Untitled sync") + "”?", danger: true, action: "Delete job",
      text: "Only the job and its memory of the last sync are removed. No files are touched." }).then(function (yes) {
      if (!yes) { return; }
      NB.api("sync.delete", { id: form.id }).then(function (r) {
        if (!r.ok) { NB.toast(r.error); return; }
        form = blank();
        clearPreview();
        loadJobs().then(renderForm);
      });
    });
  }

  // ---------------------------------------------------------------- preview
  function startPreview(btn) {
    if (NB.conn.status !== "connected") { formError("Connect to the server first."); return; }
    formError("");
    clearPreview();
    progress = { phase: "local", files: 0 };
    renderPreview();
    NB.task("sync.preview", btn, "Reading folders…");
    NB.api("sync.preview", { job: spec() }).then(function (r) {
      if (!r.ok) { NB.emit("task_done", { key: "sync.preview" }); progress = null; renderPreview(); formError(r.error); }
    });
  }
  function clearPreview() { preview = null; entries = []; view = []; decisions = {}; notice = null; progress = null; if (host) { renderPreview(); } }
  function stale() {
    preview = null;
    entries = [];
    notice = { kind: "info", text: "The job changed. Preview again to see what a sync would do." };
    renderPreview();
  }
  function rank(e) { return { conflict: 0, delete: 1, overwrite: 2, download: 3, upload: 3, keep_both: 2, skip: 9 }[e.action]; }
  function applyFilter() {
    view = entries.filter(function (e) {
      if (filter === "all") { return true; }
      if (filter === "same") { return e.action === "skip"; }
      if (filter === "conflict") { return e.action === "conflict"; }
      return e.action !== "skip";
    });
    if (list) { list.setCount(view.length); }
    var empty = host && $(".sync-empty", host);
    if (empty) {
      empty.hidden = !!view.length;
      empty.textContent = filter === "changes" ? "Nothing to do. Both folders already match." : "No files here.";
    }
  }
  function label(e) {
    var server = e.target === "remote";
    switch (e.action) {
      case "upload": return ["up", "Copy to server", "busy"];
      case "download": return e.replaces ? ["down", "Replace here", "warn"] : ["down", "Copy here", "busy"];
      case "overwrite": return ["up", "Replace on server", "warn"];
      case "delete": return ["close", server ? "Delete on server" : "Delete here", "bad"];
      case "conflict": return ["warn", "Conflict", "warn"];
      default: return ["check", "Unchanged", "ok"];
    }
  }
  function rowHtml(i) {
    var e = view[i], l = label(e), size = e.src != null ? e.src : e.dst;
    var right = "";
    if (e.action === "conflict") {
      var chosen = decisions[e.path] || "";
      right = '<span class="sync-choice"><select data-path="' + esc(e.path) + '" aria-label="What to do with ' + esc(e.path) + '">' +
        '<option value=""' + (chosen ? "" : " selected") + ">Choose…</option>" +
        e.choices.slice().sort(function (a, b) { return Object.keys(CHOICE).indexOf(a) - Object.keys(CHOICE).indexOf(b); }).map(function (c) {
          return '<option value="' + c + '"' + (c === chosen ? " selected" : "") + ">" + CHOICE[c] + "</option>";
        }).join("") + "</select>" +
        (e.choices.indexOf("keep_both") >= 0 ? '<button type="button" class="sm ghost" data-compare="' + esc(e.path) + '">Compare</button>' : "") + "</span>";
    } else {
      right = '<span class="num faint">' + (size != null ? NB.humanSize(size) : "") + "</span>";
    }
    return '<div class="sync-row' + (e.action === "conflict" && !decisions[e.path] ? " open" : "") + '" role="row">' +
      '<span class="chip ' + l[2] + '" role="cell">' + ICO(l[0]) + esc(l[1]) + "</span>" +
      '<span class="sync-path mono" role="cell" title="' + esc(e.path) + '"><bdi>' + esc(e.path) + "</bdi></span>" +
      '<span class="sync-why faint" role="cell">' + esc(e.reason) + "</span><span role=\"cell\" class=\"sync-right\">" + right + "</span></div>";
  }
  function stat(n, text, kind) { return '<span class="sync-stat st-' + kind + (n ? "" : " zero") + '"><b class="num">' + n.toLocaleString() + "</b> " + text + "</span>"; }
  function undecided() { return entries.filter(function (e) { return e.action === "conflict" && !decisions[e.path]; }).length; }
  function renderPreview() {
    var box = host && $(".sync-preview", host);
    if (!box) { return; }
    list = null;
    if (progress) {
      var what = progress.phase === "local" ? "Reading the folder on this computer…"
        : progress.phase === "checksums" ? "Comparing " + progress.files + " changed file" + (progress.files === 1 ? "" : "s") + " byte for byte…"
        : "Reading the server folder… " + (progress.files ? progress.files.toLocaleString() + " files in " + progress.folders.toLocaleString() + " folders" : "");
      box.hidden = false;
      box.innerHTML = '<div class="sync-busy" aria-live="polite"><div class="pane-loading"><div class="skel" style="height:12px;width:70%"></div><div class="skel" style="height:12px;width:45%"></div></div>' +
        '<p class="muted">' + esc(what) + '</p><button type="button" class="sm" data-a="cancel">Cancel</button></div>';
      return;
    }
    var banner = notice ? '<p class="banner ' + notice.kind + ' sync-notice">' + ICO(notice.kind === "ok" ? "check" : notice.kind === "warn" ? "warn" : "info") + "<span>" + esc(notice.text) + "</span></p>" : "";
    if (!preview) { box.hidden = !notice; box.innerHTML = banner; return; }
    var c = preview.counts, open = undecided();
    box.hidden = false;
    box.innerHTML = banner + '<div class="sync-head"><div class="sync-stats">' +
      stat(c.upload, "to the server", "busy") + stat(c.download, "to this computer", "busy") + stat(c.replace, "replaced", "warn") +
      stat(c.delete, "deleted", "bad") + stat(c.conflict, c.conflict === 1 ? "conflict" : "conflicts", "warn") + stat(c.same, "unchanged", "ok") +
      '<span class="faint num">' + (c.bytes ? NB.humanSize(c.bytes) + " to copy" : "") + "</span></div>" +
      '<div class="seg sm" role="radiogroup" aria-label="Show">' + FILTERS.map(function (f) {
        return '<button type="button" role="radio" data-filter="' + f[0] + '" aria-checked="' + (f[0] === filter) + '">' + f[1] + "</button>"; }).join("") + "</div></div>" +
      (c.conflict ? '<div class="sync-bulk"><span class="muted">' + (open ? open + " of " + c.conflict + " conflicts need a choice." : "Every conflict has a choice.") +
        '</span><span class="spacer"></span><span class="faint">For all conflicts:</span>' + ["use_local", "use_remote", "keep_both", "skip"].map(function (k) {
          return '<button type="button" class="sm ghost" data-all="' + k + '">' + CHOICE[k] + "</button>"; }).join("") + "</div>" : "") +
      (preview.mode === "two_way" && !preview.baseline ? '<p class="faint sync-hint">' + (preview.saved
        ? "First sync of this job: files that are on one side only are copied, never deleted. After this run, deletions are synced too."
        : "This job isn't saved, so deletions can't be followed: files on one side only are copied. Save the job to sync deletions next time.") + "</p>" : "") +
      '<div class="sync-list" role="table" aria-label="Sync preview"></div><p class="sync-empty muted" hidden></p>' +
      '<div class="sync-foot"><span class="faint">Built in ' + preview.seconds + ' s. Nothing has changed yet.</span><span class="spacer"></span>' +
      '<button type="button" data-a="again">' + ICO("refresh") + "Preview again</button>" +
      '<button type="button" class="pri" data-a="run"' + (open || !(c.upload + c.download + c.replace + c.delete + c.conflict) ? " disabled" : "") + ">" + ICO("sync") + "Sync now</button></div>";
    list = new NB.VList($(".sync-list", box), { rowHeight: ROW, render: rowHtml });
    applyFilter();
  }
  function setDecision(path, choice) {
    if (choice) { decisions[path] = choice; } else { delete decisions[path]; }
  }
  function decideAll(choice) {
    entries.forEach(function (e) {
      if (e.action !== "conflict") { return; }
      if (e.choices.indexOf(choice) >= 0) { decisions[e.path] = choice; }
      else if (!decisions[e.path]) { decisions[e.path] = "skip"; }        // e.g. "keep both" for a file deleted on one side
    });
    var top = list ? list.vp.scrollTop : 0;
    renderPreview();
    if (list) { list.vp.scrollTop = top; list.refresh(); }
  }
  function compare(path) {
    NB.api("sync.compare", { token: preview.token, path: path }).then(function (r) {
      if (!r.ok) { NB.toast(r.error); return; }
      NB.diffModal({ title: path, sub: "Left: this computer · Right: the server", left: r.data.local, right: r.data.remote, language: r.data.language })
        .catch(function (e) { NB.toast("Couldn't load the compare view: " + e.message); });
    });
  }
  function run(btn) {
    var c = preview.counts, replacing = c.replace, conflictsActing = 0;
    entries.forEach(function (e) { if (e.action === "conflict" && decisions[e.path] && decisions[e.path] !== "skip") { conflictsActing++; } });
    replacing += conflictsActing;
    var copies = c.upload + c.download;
    var go = function (confirmed) {
      NB.task("sync.run", btn, "Syncing…");
      NB.api("sync.run", { token: preview.token, decisions: decisions, confirmed: confirmed }).then(function (r) {
        if (!r.ok) { NB.emit("task_done", { key: "sync.run" }); NB.toast(r.error); return; }
        NB.openDock("transfers");
      });
    };
    if (!replacing && !c.delete) { go(false); return; }
    var parts = [];
    if (copies) { parts.push(copies + " file" + (copies === 1 ? " is" : "s are") + " copied"); }
    if (replacing) { parts.push(replacing + (replacing === 1 ? " is" : " are") + " replaced"); }
    if (c.delete) { parts.push(c.delete + (c.delete === 1 ? " is" : " are") + " deleted"); }
    NB.confirm({ title: "Sync “" + (preview.job.name || "Untitled sync") + "” now?", danger: true, action: "Sync now",
      text: parts.join(", ") + ". Replaced and deleted files aren't backed up first." }).then(function (yes) { if (yes) { go(true); } });
  }

  NB.on("sync.progress", function (p) { if (progress) { progress = p; renderPreview(); } });
  NB.on("task_done", function (p) {          // a preview that stopped with an error: show it next to the form
    if (p.key === "sync.preview" && p.error && progress) { progress = null; renderPreview(); formError(p.error); }
  });
  NB.on("sync.preview", function (p) {
    progress = null;
    if (p.cancelled) { notice = null; renderPreview(); return; }
    var kept = p.changed ? decisions : {};
    NB.api("sync.entries", { token: p.token }).then(function (r) {
      if (!r.ok) { NB.toast(r.error); return; }
      preview = Object.assign({}, p, { mode: p.job.mode });
      entries = r.data.slice().sort(function (a, b) { return rank(a) - rank(b) || (a.path < b.path ? -1 : 1); });
      decisions = {};
      entries.forEach(function (e) { if (e.action === "conflict" && kept[e.path] && e.choices.indexOf(kept[e.path]) >= 0) { decisions[e.path] = kept[e.path]; } });
      notice = p.changed ? { kind: "warn", text: "Files changed since the preview, so nothing was synced. Check this new preview and sync again." } : null;
      if (filter !== "all" && !entries.some(function (e) { return e.action !== "skip"; })) { filter = "changes"; }
      renderPreview();
    });
  });
  NB.on("sync.result", function (p) {
    var bits = [];
    if (p.copied) { bits.push(p.copied + " transfer" + (p.copied === 1 ? "" : "s") + " done"); }
    if (p.deleted_remote) { bits.push(p.deleted_remote + " deleted on the server"); }
    if (p.deleted_local) { bits.push(p.deleted_local + " deleted here"); }
    preview = null;
    entries = [];
    notice = p.ok ? { kind: "ok", text: "Synced: " + (bits.join(", ") || "nothing needed to change") + "." + (p.baseline ? " The job remembers this state for next time." : "") }
      : { kind: "warn", text: p.message + " Preview again to see where things stand." };
    NB.toast(p.ok ? "Sync finished" : p.message, p.ok ? "ok" : "");
    renderPreview();
    var box = host && $(".sync-preview", host);
    if (box) { box.scrollIntoView({ block: "nearest" }); }
  });
  NB.on("conn", function () { if (preview) { clearPreview(); } if (host) { renderJobs(); } });

  NB.screens.sync = {
    ready: true,
    render: function (el) {
      host = el;
      if (!form) { form = blank(); }
      el.innerHTML = '<div class="screen-head"><div><h1>Sync folders</h1><p>Keep a folder on this computer and one on the server in step. ' +
        "Every sync starts with a preview, and nothing changes until you press Sync now.</p></div></div>" +
        '<div class="sync-grid"><aside class="card vault-projects sync-jobs"><div class="vp-head"><b>Sync jobs</b></div><div class="vp-list sync-jobs-list"></div></aside>' +
        '<div class="sync-main"><section class="card sync-form"></section><section class="card sync-preview" aria-label="Preview" hidden></section></div></div>';
      renderForm();
      renderJobs();
      renderPreview();
      loadJobs();
      el.addEventListener("click", function (e) {
        var b = e.target.closest("[data-a],[data-mode],[data-job],[data-filter],[data-all],[data-compare]");
        if (!b) { return; }
        if (b.hasAttribute("data-job")) { pick(b.getAttribute("data-job")); return; }
        if (b.hasAttribute("data-mode")) { form.mode = b.getAttribute("data-mode"); if (preview) { stale(); } renderForm(); return; }
        if (b.hasAttribute("data-filter")) {
          filter = b.getAttribute("data-filter");
          $$("[data-filter]", host).forEach(function (x) { x.setAttribute("aria-checked", String(x === b)); });
          applyFilter();
          return;
        }
        if (b.hasAttribute("data-all")) { decideAll(b.getAttribute("data-all")); return; }
        if (b.hasAttribute("data-compare")) { compare(b.getAttribute("data-compare")); return; }
        var a = b.getAttribute("data-a");
        if (a === "browse") {
          NB.api("window.pick", { kind: "folder", start: form.local }).then(function (r) {
            if (r.ok && r.data.paths && r.data.paths.length) { form.local = r.data.paths[0]; renderForm(); if (preview) { stale(); } }
            else if (r.ok && r.data.available === false) { NB.toast("Type the folder path; the folder picker needs the app window."); }
          });
        }
        else if (a === "save") { save(); }
        else if (a === "delete") { remove(); }
        else if (a === "cancel") { NB.api("sync.cancel"); }
        else if (a === "again") { startPreview(b); }
        else if (a === "run") { run(b); }
      });
      el.addEventListener("change", function (e) {
        var s = e.target.closest("select[data-path]");
        if (!s) { return; }
        setDecision(s.getAttribute("data-path"), s.value);
        s.closest(".sync-row").classList.toggle("open", !s.value);
        var open = undecided(), c = preview.counts;
        var bulk = $(".sync-bulk .muted", host);
        if (bulk) { bulk.textContent = open ? open + " of " + c.conflict + " conflicts need a choice." : "Every conflict has a choice."; }
        $("[data-a=run]", host).disabled = !!open;
      });
    },
    leave: function () { host = null; list = null; }
  };
})();
