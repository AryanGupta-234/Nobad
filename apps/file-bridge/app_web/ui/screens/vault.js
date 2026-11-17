// Credential vault: locked by default; secrets are fetched only for an explicit Reveal or Copy, hidden again after
// 30 s, and a copied secret is cleared from the clipboard after 30 s if it's still there.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, $$ = NB.$$, esc = NB.esc;
  var HIDE_AFTER = 30000;
  var host = null, state = null, kinds = [], projects = [], items = [], projectId = null, itemId = null, query = "";
  var revealTimers = [];

  function api(name, body) {
    return NB.api(name, body).then(function (r) {
      if (!r.ok && /locked/i.test(r.error || "")) { refresh(); }
      return r;
    });
  }
  function refresh() {
    return NB.api("vault.state").then(function (r) {
      if (!r.ok) { return; }
      state = r.data;
      kinds = r.data.kinds;
      if (host) { render(); }
    });
  }
  function clearReveals() { revealTimers.forEach(clearTimeout); revealTimers = []; }

  // ---------------------------------------------------------------- locked / create
  function strength(pw) {
    var s = 0;
    if (pw.length >= 12) { s++; }
    if (pw.length >= 16) { s++; }
    if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) { s++; }
    if (/\d/.test(pw)) { s++; }
    if (/[^A-Za-z0-9]/.test(pw) || /\s/.test(pw.trim())) { s++; }
    return Math.min(4, s);
  }
  function renderLocked() {
    var create = !state.configured;
    host.innerHTML = '<div class="vault-lock"><div class="card vault-card">' +
      '<div class="empty-ico">' + ICO("vault") + "</div>" +
      "<h1>" + (create ? "Create your credential vault" : "The vault is locked") + "</h1>" +
      "<p class=\"muted\">" + (create
        ? "Keep API keys, passwords and notes encrypted on this computer (Argon2id + AES-256-GCM). Only your master password opens it."
        : "Unlock it with your master password. It locks itself after " + state.auto_lock_minutes + " minutes without use.") + "</p>" +
      '<form class="vault-form" novalidate>' +
      '<label class="field"><span>Master password</span><input type="password" name="password" autocomplete="' + (create ? "new-password" : "current-password") + '" required></label>' +
      (create ? '<div class="meter" aria-hidden="true"><i></i><i></i><i></i><i></i></div>' +
        '<label class="field"><span>Repeat it</span><input type="password" name="confirm" autocomplete="new-password" required></label>' +
        '<p class="banner warn vault-warn">' + ICO("warn") + "<span>There's no way to recover the vault if you forget this password. Write it down somewhere safe.</span></p>" : "") +
      '<p class="form-error" role="alert" hidden></p>' +
      '<button type="submit" class="pri wide">' + ICO("vault") + (create ? "Create vault" : "Unlock") + "</button></form></div></div>";
    var f = $("form", host), err = $(".form-error", host);
    if (create) {
      f.password.addEventListener("input", function () {
        var n = strength(f.password.value);
        $$(".meter i", host).forEach(function (bar, i) { bar.className = i < n ? "on s" + n : ""; });
      });
    }
    if (state.retry_in) { err.textContent = "Too many wrong passwords. Try again in " + state.retry_in + " s."; err.hidden = false; }
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = $("button[type=submit]", f);
      btn.classList.add("is-busy");
      var body = { password: f.password.value };
      if (create) { body.confirm = f.confirm.value; }
      NB.api(create ? "vault.create" : "vault.unlock", body).then(function (r) {
        btn.classList.remove("is-busy");
        f.password.value = "";
        if (f.confirm) { f.confirm.value = ""; }
        if (!r.ok) { err.textContent = r.error; err.hidden = false; f.password.focus(); return; }
        state = Object.assign(state, r.data);
        render();
      });
    });
    f.password.focus();
  }

  // ---------------------------------------------------------------- unlocked
  function renderOpen() {
    host.innerHTML = '<div class="screen-head"><div><h1>Credential vault</h1><p>Unlocked. It locks itself after ' +
      (state.auto_lock_minutes ? state.auto_lock_minutes + " minutes without use." : "you close the app (auto-lock is off in Settings).") + "</p></div>" +
      '<div class="head-actions"><button type="button" data-a="new" class="pri">' + ICO("plus") + "New credential</button>" +
      '<button type="button" data-a="lock">' + ICO("vault") + "Lock now</button></div></div>" +
      '<div class="vault-grid"><aside class="card vault-projects"><div class="vp-head"><b>Projects</b>' +
      '<button type="button" class="icon ghost sm" data-a="new-project" aria-label="New project" title="New project">' + ICO("plus") + "</button></div>" +
      '<div class="vp-list" role="listbox" aria-label="Projects"></div></aside>' +
      '<section class="card vault-items"><input type="search" class="vault-search" placeholder="Search titles, users and hosts…" aria-label="Search credentials" autocomplete="off" spellcheck="false">' +
      '<div class="vi-list" role="listbox" aria-label="Credentials"></div></section>' +
      '<section class="card vault-detail" aria-live="polite"></section></div>';
    $(".vault-search", host).value = query;
    $(".vault-search", host).addEventListener("input", function (e) { query = e.target.value; loadItems(); });
    loadProjects();
  }
  function loadProjects() {
    return api("vault.projects").then(function (r) {
      if (!r.ok) { return; }
      projects = r.data;
      if (projectId && !projects.some(function (p) { return p.id === projectId; })) { projectId = null; }
      var total = projects.reduce(function (n, p) { return n + p.count; }, 0);
      $(".vp-list", host).innerHTML = '<button type="button" role="option" class="vp-item' + (projectId ? "" : " on") + '" data-p="" aria-selected="' + !projectId + '">' +
        "<span>All credentials</span><span class=\"num faint\">" + total + "</span></button>" +
        projects.map(function (p) {
          return '<button type="button" role="option" class="vp-item' + (p.id === projectId ? " on" : "") + '" data-p="' + esc(p.id) + '" aria-selected="' + (p.id === projectId) + '">' +
            "<span>" + esc(p.name) + '</span><span class="num faint">' + p.count + "</span></button>";
        }).join("") + (projects.length ? "" : '<p class="faint vp-empty">Projects group credentials, like one per website or client.</p>');
      loadItems();
    });
  }
  function loadItems() {
    return api("vault.items", { project_id: projectId, query: query }).then(function (r) {
      if (!r.ok) { return; }
      items = r.data;
      var list = $(".vi-list", host);
      if (!items.length) {
        list.innerHTML = '<div class="vi-empty"><p class="muted">' + (query ? "No credential matches that search." : projects.length ? "No credentials here yet." : "Create a project, then add your first credential.") + "</p>" +
          (projects.length ? "" : '<button type="button" class="pri" data-a="new-project">' + ICO("plus") + "New project</button>") + "</div>";
      } else {
        list.innerHTML = items.map(function (it) {
          return '<button type="button" role="option" class="vi-item' + (it.id === itemId ? " on" : "") + '" data-i="' + esc(it.id) + '" aria-selected="' + (it.id === itemId) + '">' +
            '<span class="vi-ico">' + ICO(kindIcon(it.kind)) + '</span><span class="vi-main"><b>' + esc(it.title) + "</b><small>" +
            esc(it.username || it.url_host || it.environment_key || it.kind_label) + '</small></span><span class="chip">' + esc(it.kind_label) + "</span></button>";
        }).join("");
      }
      if (itemId && items.some(function (i) { return i.id === itemId; })) { loadDetail(itemId); } else { itemId = null; renderDetail(null); }
    });
  }
  function kindIcon(kind) {
    return { server_login: "servers", ssh_secret: "terminal", database: "logs", api_key: "code", git_token: "code", env_var: "settings",
      secure_note: "doc", certificate_key: "vault" }[kind] || "vault";
  }
  function loadDetail(id) {
    itemId = id;
    $$(".vi-item", host).forEach(function (b) { var on = b.getAttribute("data-i") === id; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); });
    return api("vault.item", { id: id }).then(function (r) { if (r.ok) { renderDetail(r.data); } });
  }
  function field(label, value, opts) {
    opts = opts || {};
    if (!value && !opts.secret) { return ""; }
    return '<div class="vd-row"><dt>' + esc(label) + "</dt><dd>" +
      (opts.secret ? '<span class="mono secret" data-secret="' + opts.secret + '">••••••••••••</span>' : '<span class="mono">' + esc(value) + "</span>") +
      '<span class="vd-act">' + (opts.secret ? '<button type="button" class="sm ghost" data-reveal="' + opts.secret + '">Reveal</button>' : "") +
      (opts.copy ? '<button type="button" class="sm ghost" data-copy="' + esc(opts.copy) + '"' + (opts.secret ? "" : ' data-plain="' + esc(value) + '"') + ">Copy</button>" : "") + "</span></dd></div>";
  }
  function renderDetail(it) {
    clearReveals();
    var box = $(".vault-detail", host);
    if (!it) { box.innerHTML = '<div class="vd-empty"><p class="muted">Choose a credential to see its details.</p></div>'; return; }
    box.innerHTML = '<div class="vd-head"><div><h2>' + esc(it.title) + '</h2><span class="chip acc">' + esc(it.kind_label) + "</span></div>" +
      '<div class="vd-tools"><button type="button" class="sm" data-a="edit">Edit</button><button type="button" class="sm danger" data-a="delete">Delete</button></div></div>' +
      '<dl class="vd-fields">' + field("Username", it.username, { copy: "plain" }) + field("URL or host", it.url_host, { copy: "plain" }) +
      field("Variable name", it.environment_key, { copy: "plain" }) + field("Secret", "", { secret: "value", copy: "secret" }) +
      (it.has_notes ? field("Notes", "", { secret: "notes" }) : "") +
      (it.custom_fields.length ? field(it.custom_fields.length + " custom field" + (it.custom_fields.length === 1 ? "" : "s"), "", { secret: "fields" }) : "") + "</dl>" +
      '<p class="faint vd-note">Revealed values hide again after 30 seconds. Every reveal and copy is noted in the vault\'s activity log.</p>';
  }
  function reveal(what, btn) {
    var span = $('[data-secret="' + what + '"]', host);
    if (!span) { return; }
    if (span.classList.contains("shown")) { hide(span, btn); return; }
    api("vault.reveal", { id: itemId, what: what }).then(function (r) {
      if (!r.ok) { NB.toast(r.error); return; }
      var v = r.data.value;
      if (what === "fields") {
        span.textContent = "";
        Object.keys(v).forEach(function (k) {
          var line = document.createElement("div");
          line.textContent = k + " = " + v[k];
          span.appendChild(line);
        });
      } else { span.textContent = v || "(empty)"; }
      span.classList.add("shown");
      if (btn) { btn.textContent = "Hide"; }
      revealTimers.push(setTimeout(function () { hide(span, btn); }, HIDE_AFTER));
    });
  }
  function hide(span, btn) {
    span.textContent = "••••••••••••";
    span.classList.remove("shown");
    if (btn) { btn.textContent = "Reveal"; }
  }
  function copy(btn) {
    var write = function (text, secret) {
      navigator.clipboard.writeText(text).then(function () {
        if (!secret) { NB.toast("Copied", "ok"); return; }
        NB.toast("Copied. The clipboard is cleared in 30 seconds.", "ok");
        setTimeout(function () {
          navigator.clipboard.readText().then(function (now) { if (now === text) { navigator.clipboard.writeText(""); } }, function () {
            navigator.clipboard.writeText("");
          });
        }, HIDE_AFTER);
      }, function () { NB.toast("Couldn't copy to the clipboard."); });
    };
    if (btn.hasAttribute("data-plain")) { write(btn.getAttribute("data-plain"), false); return; }
    api("vault.reveal", { id: itemId, what: "copied" }).then(function (r) { if (r.ok) { write(r.data.value, true); } else { NB.toast(r.error); } });
  }

  // ---------------------------------------------------------------- new / edit
  function editForm(existing) {
    if (!projects.length) { NB.toast("Create a project first."); return newProject(); }
    var f = document.createElement("form");
    f.className = "conn-form vault-edit";
    f.setAttribute("novalidate", "");
    var pid = existing ? existing.project_id : (projectId || projects[0].id);
    f.innerHTML =
      '<label class="field"><span>Project</span><select name="project_id"' + (existing ? " disabled" : "") + ">" + projects.map(function (p) {
        return '<option value="' + esc(p.id) + '"' + (p.id === pid ? " selected" : "") + ">" + esc(p.name) + "</option>"; }).join("") + "</select></label>" +
      '<label class="field"><span>Type</span><select name="kind">' + kinds.map(function (k) {
        return '<option value="' + esc(k.value) + '"' + ((existing ? existing.kind : "login") === k.value ? " selected" : "") + ">" + esc(k.label) + "</option>"; }).join("") + "</select></label>" +
      '<label class="field wide"><span>Title</span><input name="title" required autocomplete="off" placeholder="Production database…"></label>' +
      '<label class="field"><span>Username</span><input name="username" autocomplete="off" spellcheck="false"></label>' +
      '<label class="field"><span>URL or host</span><input name="url_host" autocomplete="off" spellcheck="false" placeholder="db.example.com…"></label>' +
      '<label class="field wide"><span>Variable name <small class="muted">optional, for .env files</small></span><input name="environment_key" autocomplete="off" spellcheck="false" placeholder="DATABASE_URL…"></label>' +
      '<label class="field wide"><span>Secret</span><span class="input-row"><input name="secret" type="password" autocomplete="new-password" spellcheck="false"' +
        (existing ? ' placeholder="Unchanged. Type to replace it…"' : "") + '><button type="button" data-a="show">Show</button><button type="button" data-a="gen">Generate</button></span></label>' +
      '<label class="field wide"><span>Notes</span><textarea name="notes" rows="3" spellcheck="false"' + (existing && existing.has_notes ? ' placeholder="Unchanged. Type to replace them…"' : "") + "></textarea></label>" +
      '<label class="check wide"><input type="checkbox" name="favorite"' + (existing && existing.favorite ? " checked" : "") + "><span>Show at the top of the list</span></label>" +
      '<p class="form-error" role="alert" hidden></p>' +
      '<div class="modal-actions"><button type="button" data-a="cancel">Cancel</button><button type="submit" class="pri">' + (existing ? "Save changes" : "Add credential") + "</button></div>";
    if (existing) { ["title", "username", "url_host", "environment_key"].forEach(function (k) { f[k].value = existing[k] || ""; }); }
    var m = NB.modal({ title: existing ? "Edit credential" : "New credential", body: f, className: "wide", initialFocus: "[name=title]" });
    f.addEventListener("click", function (e) {
      var b = e.target.closest("[data-a]");
      if (!b) { return; }
      var a = b.getAttribute("data-a");
      if (a === "cancel") { m.close(); }
      else if (a === "show") { f.secret.type = f.secret.type === "password" ? "text" : "password"; b.textContent = f.secret.type === "password" ? "Show" : "Hide"; }
      else if (a === "gen") {
        NB.api("vault.generate", { length: 24 }).then(function (r) { if (r.ok) { f.secret.value = r.data.value; f.secret.type = "text"; $("[data-a=show]", f).textContent = "Hide"; } });
      }
    });
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      var body = { id: existing ? existing.id : null, project_id: f.project_id.value, kind: f.kind.value, title: f.title.value,
        username: f.username.value, url_host: f.url_host.value, environment_key: f.environment_key.value, favorite: f.favorite.checked };
      if (!existing || f.secret.value) { body.secret = f.secret.value; }
      if (!existing || f.notes.value) { body.notes = f.notes.value; }
      api("vault.item.save", body).then(function (r) {
        if (!r.ok) { var er = $(".form-error", f); er.textContent = r.error; er.hidden = false; return; }
        f.secret.value = "";
        m.close();
        itemId = r.data.id;
        NB.toast(existing ? "Saved" : "Added " + r.data.title, "ok");
        loadProjects();
      });
    });
  }
  function newProject() {
    NB.prompt({ title: "New project", label: "Project name", action: "Create project" }).then(function (name) {
      if (!name) { return; }
      api("vault.project.create", { name: name }).then(function (r) { if (!r.ok) { NB.toast(r.error); return; } projectId = r.data.id; loadProjects(); });
    });
  }

  function render() {
    clearReveals();
    if (!state) { host.innerHTML = '<div class="card"><div class="skel" style="height:14px;width:40%"></div></div>'; return; }
    if (state.unlocked) { renderOpen(); } else { renderLocked(); }
  }

  NB.screens.vault = {
    ready: true,
    render: function (el) {
      host = el;
      render();
      refresh();
      el.addEventListener("click", function (e) {
        var b = e.target.closest("[data-a],[data-p],[data-i],[data-reveal],[data-copy]");
        if (!b) { return; }
        if (b.hasAttribute("data-p")) { projectId = b.getAttribute("data-p") || null; itemId = null; loadProjects(); return; }
        if (b.hasAttribute("data-i")) { loadDetail(b.getAttribute("data-i")); return; }
        if (b.hasAttribute("data-reveal")) { reveal(b.getAttribute("data-reveal"), b); return; }
        if (b.hasAttribute("data-copy")) { copy(b); return; }
        var a = b.getAttribute("data-a");
        if (a === "lock") { NB.api("vault.lock").then(function (r) { if (r.ok) { state = Object.assign(state, r.data); render(); } }); }
        else if (a === "new") { editForm(null); }
        else if (a === "new-project") { newProject(); }
        else if (a === "edit") { api("vault.item", { id: itemId }).then(function (r) { if (r.ok) { editForm(r.data); } }); }
        else if (a === "delete") {
          var it = items.find(function (i) { return i.id === itemId; });
          NB.confirm({ title: "Delete “" + (it ? it.title : "this credential") + "”?", danger: true, action: "Delete",
            text: "The encrypted secret, notes and custom fields are removed from the vault. This can't be undone." })
            .then(function (yes) { if (yes) { api("vault.item.delete", { id: itemId }).then(function (r) { if (!r.ok) { NB.toast(r.error); } itemId = null; loadProjects(); }); } });
        }
      });
    },
    leave: function () { clearReveals(); host = null; }
  };
  NB.on("vault", function (s) {
    state = Object.assign(state || {}, s);
    if (s.reason === "idle") { NB.toast("The vault locked itself after " + s.auto_lock_minutes + " minutes without use."); }
    if (host) { render(); }
  });
})();
