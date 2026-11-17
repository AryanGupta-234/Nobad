// Editor: Monaco (bundled, no CDN) with tabs for server and local files, save with a "changed since you opened it"
// check, and a side-by-side compare before anything is overwritten. Models outlive the screen, so switching
// screens never loses edits.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, esc = NB.esc;
  var MONACO = "/static/vendor/monaco/vs";
  var tabs = new Map();          // id -> {info, model, savedVersion, view state}
  var activeId = null, host = null, editor = null, diff = null, monacoReady = null;

  // ---- Monaco loading (AMD loader from the bundled copy)
  function loadMonaco() {
    if (monacoReady) { return monacoReady; }
    monacoReady = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = MONACO + "/loader.js";
      s.onload = function () {
        window.require.config({ paths: { vs: MONACO } });
        window.require(["vs/editor/editor.main"], function () { defineThemes(); resolve(window.monaco); }, reject);
      };
      s.onerror = function () { reject(new Error("The editor files are missing.")); };
      document.head.appendChild(s);
    });
    return monacoReady;
  }
  function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function hex(v) { return /^#[0-9a-f]{6}$/i.test(v) ? v : "#111319"; }
  function defineThemes() {
    var m = window.monaco;
    m.editor.defineTheme("nobad-dark", { base: "vs-dark", inherit: true, rules: [], colors: {
      "editor.background": "#111319", "editor.lineHighlightBackground": "#171a22", "editorLineNumber.foreground": "#5c5f69",
      "editorLineNumber.activeForeground": "#a0a1aa", "editor.selectionBackground": "#1f6bf055", "editorCursor.foreground": "#6ea8ff",
      "editorIndentGuide.background1": "#ffffff12", "editorWidget.background": "#171a22", "editorWidget.border": "#ffffff1f",
      "diffEditor.insertedTextBackground": "#3bd69b22", "diffEditor.removedTextBackground": "#ff526822", "scrollbarSlider.background": "#ffffff1a"
    } });
    m.editor.defineTheme("nobad-light", { base: "vs", inherit: true, rules: [], colors: {
      "editor.background": "#ffffff", "editor.lineHighlightBackground": "#f3f5f8", "editorLineNumber.foreground": "#9aa1ad",
      "editorLineNumber.activeForeground": "#4e5665", "editor.selectionBackground": "#2563eb33", "editorCursor.foreground": "#1f5fd1",
      "diffEditor.insertedTextBackground": "#13865d1f", "diffEditor.removedTextBackground": "#cc29421c"
    } });
  }
  function themeName() { return document.documentElement.getAttribute("data-theme") === "light" ? "nobad-light" : "nobad-dark"; }
  NB.on("theme", function () { if (window.monaco) { window.monaco.editor.setTheme(themeName()); } });

  // ---- tabs
  function isDirty(t) { return t.model && t.model.getAlternativeVersionId() !== t.savedVersion; }
  function addTab(info, text) {
    var m = window.monaco;
    var uri = m.Uri.from({ scheme: "nbfb", authority: info.side, path: "/" + info.id + "/" + info.name });
    var model = m.editor.createModel(text, info.language || "plaintext", uri);
    var t = { info: info, model: model, savedVersion: model.getAlternativeVersionId(), view: null };
    model.onDidChangeContent(function () { renderTabs(); });
    tabs.set(info.id, t);
    return t;
  }
  NB.openEditor = function (side, path) {
    NB.go("editor");
    return loadMonaco().then(function () {
      return NB.api("edit.open", { side: side, path: path });
    }).then(function (r) {
      if (!r.ok) { NB.toast(r.error); return; }
      var t = tabs.get(r.data.id) || addTab(r.data, r.data.text);
      (r.data.warnings || []).forEach(function (w) { NB.toast(w); });
      show(t.info.id);
    }, function (e) { NB.toast("Couldn't load the editor: " + e.message); });
  };

  function show(id) {
    if (editor && activeId && tabs.has(activeId)) { tabs.get(activeId).view = editor.saveViewState(); }
    activeId = id;
    if (!host) { return; }
    leaveCompare();
    var t = tabs.get(id);
    renderBody();
    if (t && editor) {
      editor.setModel(t.model);
      if (t.view) { editor.restoreViewState(t.view); }
      editor.focus();
    }
    renderTabs();
    renderBar();
  }
  function closeTab(id) {
    var t = tabs.get(id);
    if (!t) { return; }
    var go = function () {
      NB.api("edit.close", { id: id });
      t.model.dispose();
      tabs.delete(id);
      if (activeId === id) { activeId = tabs.size ? Array.from(tabs.keys()).pop() : null; }
      if (activeId) { show(activeId); } else { renderBody(); renderTabs(); renderBar(); }
    };
    if (isDirty(t)) {
      NB.confirm({ title: "Close “" + t.info.name + "” without saving?", danger: true, action: "Close without saving",
        text: "Your changes to this file will be lost." }).then(function (yes) { if (yes) { go(); } });
    } else { go(); }
  }

  // ---- save, conflicts, compare
  function save(force) {
    var t = tabs.get(activeId);
    if (!t) { return; }
    var btn = host && $("[data-a=save]", host);
    if (btn) { btn.classList.add("is-busy"); }
    var text = t.model.getValue(), version = t.model.getAlternativeVersionId();
    NB.api("edit.save", { id: t.info.id, text: text, force: !!force }).then(function (r) {
      if (btn) { btn.classList.remove("is-busy"); }
      if (!r.ok) { NB.toast(r.error); return; }
      if (r.data.saved) {
        t.savedVersion = version;
        renderTabs();
        NB.toast(r.data.message + " " + t.info.name, "ok");
        return;
      }
      if (r.data.conflict) { conflict(t, r.data.message); } else { NB.toast(r.data.message); }
    });
  }
  function conflict(t, message) {
    var body = document.createElement("div"), where = t.info.side === "remote" ? "on the server" : "on disk";
    body.innerHTML = '<p class="muted">Someone or something changed “' + esc(t.info.name) + "” " + where +
      " after you opened it. Compare the two versions before you decide.</p>" +
      '<div class="modal-actions"><button type="button" data-a="cancel">Cancel</button><button type="button" data-a="reload">Reload theirs</button>' +
      '<button type="button" data-a="overwrite" class="danger">Overwrite with mine</button><button type="button" class="pri" data-a="compare">Compare</button></div>';
    var m = NB.modal({ title: message, body: body, initialFocus: "[data-a=compare]" });
    body.addEventListener("click", function (e) {
      var b = e.target.closest("[data-a]");
      if (!b) { return; }
      var a = b.getAttribute("data-a");
      m.close();
      if (a === "compare") { compare(); }
      else if (a === "overwrite") { save(true); }
      else if (a === "reload") { reload(); }
    });
  }
  function reload() {
    var t = tabs.get(activeId);
    if (!t) { return; }
    var go = function () {
      NB.api("edit.reload", { id: t.info.id }).then(function (r) {
        if (!r.ok) { NB.toast(r.error); return; }
        t.model.setValue(r.data.text);
        t.savedVersion = t.model.getAlternativeVersionId();
        leaveCompare();
        renderTabs();
        NB.toast("Reloaded " + t.info.name, "ok");
      });
    };
    if (isDirty(t)) {
      NB.confirm({ title: "Reload and lose your changes?", danger: true, action: "Reload", text: "The editor gets the current version and your unsaved changes are discarded." })
        .then(function (yes) { if (yes) { go(); } });
    } else { go(); }
  }
  function compare() {
    var t = tabs.get(activeId);
    if (!t || !host) { return; }
    NB.api("edit.latest", { id: t.info.id }).then(function (r) {
      if (!r.ok) { NB.toast(r.error); return; }
      var m = window.monaco, wrap = $(".ed-diff", host);
      $(".ed-main", host).hidden = true;
      wrap.hidden = false;
      if (diff) { diff.dispose(); }
      diff = m.editor.createDiffEditor(wrap, { theme: themeName(), automaticLayout: true, renderSideBySide: true, originalEditable: false,
        fontFamily: cssVar("--font-mono"), fontSize: 13, minimap: { enabled: false } });
      var original = m.editor.createModel(r.data.text, t.info.language);
      diff.setModel({ original: original, modified: t.model });
      host.classList.add("comparing");
      renderBar();
    });
  }
  function leaveCompare() {
    if (!host) { return; }
    if (diff) {
      var o = diff.getModel() && diff.getModel().original;
      diff.dispose();
      diff = null;
      if (o) { o.dispose(); }
    }
    var d = $(".ed-diff", host), main = $(".ed-main", host);
    if (d) { d.hidden = true; }
    if (main) { main.hidden = false; }
    host.classList.remove("comparing");
  }

  // ---- render
  function renderTabs() {
    var bar = host && $(".ed-tabs", host);
    if (!bar) { return; }
    bar.innerHTML = Array.from(tabs.values()).map(function (t) {
      var on = t.info.id === activeId, dirty = isDirty(t);
      return '<div class="term-tab ed-tab' + (on ? " on" : "") + '"><button type="button" role="tab" class="term-tab-btn" data-id="' + esc(t.info.id) +
        '" aria-selected="' + on + '" title="' + esc(t.info.path) + '">' + ICO(t.info.side === "remote" ? "servers" : "window") +
        "<span>" + esc(t.info.name) + "</span>" + (dirty ? '<i class="dirty" aria-label="unsaved changes"></i>' : "") + "</button>" +
        '<button type="button" class="icon ghost sm term-x" data-close="' + esc(t.info.id) + '" aria-label="Close ' + esc(t.info.name) + '">' + ICO("close") + "</button></div>";
    }).join("");
  }
  function renderBar() {
    var bar = host && $(".ed-bar", host), t = tabs.get(activeId);
    if (!bar) { return; }
    if (!t) { bar.innerHTML = ""; bar.hidden = true; return; }
    bar.hidden = false;
    var comparing = host.classList.contains("comparing");
    // dir=rtl trims the start of a long path ("…/example.com/config.php"); <bdi> keeps the path itself left-to-right
    bar.innerHTML = '<span class="ed-path mono" title="' + esc(t.info.path) + '"><bdi>' + esc(t.info.path) + "</bdi></span>" +
      '<span class="chip">' + esc(t.info.language) + "</span><span class=\"chip\">" + esc(t.info.encoding) + "</span>" +
      (comparing ? '<span class="chip acc">Left: current ' + (t.info.side === "remote" ? "on the server" : "on disk") + " · Right: yours</span>" : "") +
      '<span class="spacer"></span>' +
      (comparing ? '<button type="button" class="sm" data-a="back">Back to editing</button>' : '<button type="button" class="sm ghost" data-a="compare">Compare</button>') +
      '<button type="button" class="sm ghost" data-a="reload">Reload</button>' +
      '<button type="button" class="sm pri" data-a="save" aria-keyshortcuts="Control+S">' + ICO("check") + "Save</button>";
  }
  function renderBody() {
    var empty = $(".ed-empty", host), main = $(".ed-main", host);
    if (!tabs.size) {
      if (editor) { editor.setModel(null); }
      main.hidden = true;
      empty.hidden = false;
      empty.innerHTML = '<div class="empty"><div class="empty-ico">' + ICO("code") + "</div><h2>Open a file to edit it</h2>" +
        "<p>Select a file in Files and press Enter, or double-click it. Server files are checked before saving, so you never overwrite someone else's change by accident.</p>" +
        '<div class="actions"><button type="button" class="pri" data-go="files">' + ICO("files") + "Go to Files</button></div></div>";
      return;
    }
    empty.hidden = true;
    main.hidden = false;
    if (!editor && window.monaco) {
      editor = window.monaco.editor.create($(".ed-main", host), {
        theme: themeName(), automaticLayout: true, fontFamily: cssVar("--font-mono"), fontSize: 13, minimap: { enabled: true, scale: 1 },
        scrollBeyondLastLine: false, smoothScrolling: true, renderWhitespace: "selection", bracketPairColorization: { enabled: true },
        padding: { top: 10 }
      });
      editor.addCommand(window.monaco.KeyMod.CtrlCmd | window.monaco.KeyCode.KeyS, function () { save(false); });
    }
  }

  NB.screens.editor = {
    ready: true,
    render: function (el) {
      el.classList.add("screen-term", "screen-editor");
      el.innerHTML = '<div class="term-shell card ed-shell"><div class="term-tabs ed-tabs" role="tablist" aria-label="Open files"></div>' +
        '<div class="ed-bar" hidden></div><div class="ed-main" hidden></div><div class="ed-diff" hidden></div><div class="term-empty ed-empty" hidden></div></div>';
      host = el;
      el.addEventListener("click", function (e) {
        var b = e.target.closest("[data-a],[data-close],[data-go],.term-tab-btn");
        if (!b) { return; }
        if (b.hasAttribute("data-close")) { closeTab(b.getAttribute("data-close")); return; }
        if (b.hasAttribute("data-go")) { NB.go(b.getAttribute("data-go")); return; }
        if (b.classList.contains("term-tab-btn")) { show(b.getAttribute("data-id")); return; }
        var a = b.getAttribute("data-a");
        if (a === "save") { save(false); } else if (a === "compare") { compare(); } else if (a === "reload") { reload(); }
        else if (a === "back") { leaveCompare(); renderBar(); if (editor) { editor.focus(); } }
      });
      var start = function () { renderBody(); renderTabs(); renderBar(); if (activeId) { show(activeId); } };
      if (tabs.size || activeId) { loadMonaco().then(start, function (e) { NB.toast(e.message); }); } else { start(); }
    },
    leave: function () {
      if (editor && activeId && tabs.has(activeId)) { tabs.get(activeId).view = editor.saveViewState(); }
      leaveCompare();
      if (editor) { editor.dispose(); editor = null; }
      host = null;
    }
  };

  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && host) { e.preventDefault(); save(false); }
  });
  window.addEventListener("beforeunload", function (e) {
    var unsaved = Array.from(tabs.values()).some(isDirty);
    if (unsaved) { e.preventDefault(); e.returnValue = ""; }
  });
  // Files open in the editor; reopen tabs after a window reload (their text comes back from the app).
  document.addEventListener("DOMContentLoaded", function () {
    NB.api("edit.list").then(function (r) {
      if (!r.ok || !r.data.length) { return; }
      loadMonaco().then(function () {
        r.data.forEach(function (info) {
          NB.api("edit.text", { id: info.id }).then(function (x) {
            if (x.ok && !tabs.has(info.id)) { addTab(info, x.data.text); if (!activeId) { activeId = info.id; } if (host) { show(activeId); } }
          });
        });
      });
    });
  });
})();
