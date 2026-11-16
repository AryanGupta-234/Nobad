// Core helpers shared by every screen: DOM shortcuts, esc(), api(), toast, modal, the event stream and theme.
// Rule (NOBAD AGENTS.md): any text that came from a server, a file or the user goes through esc() before it is
// placed in innerHTML; prefer textContent where possible.
(function () {
  "use strict";
  var NB = (window.NB = {});
  NB.screens = {};          // screen modules register here (screens/*.js load before shell.js)

  NB.$ = function (sel, root) { return (root || document).querySelector(sel); };
  NB.$$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  NB.esc = function (value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  // ---- API: POST /api/<name> -> {ok, error?, data?}
  NB.api = function (name, body) {
    return fetch("/api/" + encodeURIComponent(name), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
      credentials: "same-origin"
    }).then(function (res) {
      if (res.status === 401) { return { ok: false, error: "This window lost its session. Restart NOBAD File Bridge." }; }
      return res.json().catch(function () { return { ok: false, error: "Unexpected reply from the app." }; });
    }, function () {
      return { ok: false, error: "Can't reach the app. It may have stopped." };
    });
  };

  // ---- small pub/sub for bus events and UI events
  var listeners = {};
  NB.on = function (type, fn) { (listeners[type] = listeners[type] || []).push(fn); };
  NB.emit = function (type, payload) {
    (listeners[type] || []).forEach(function (fn) {
      try { fn(payload); } catch (e) { console.error("Listener for " + type + " failed", e); }
    });
  };

  // ---- event stream (SSE). EventSource reconnects on its own; we only report the state.
  NB.connectEvents = function () {
    var source = new EventSource("/events");
    source.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      NB.emit(msg.type, msg.payload);
    };
    source.onopen = function () { NB.emit("stream", "open"); };
    source.onerror = function () { NB.emit("stream", "lost"); };
    return source;
  };

  // ---- long tasks: mark a button busy until task_done {key, error} arrives
  var busy = {};
  NB.task = function (key, button, label) {
    if (button) {
      busy[key] = { button: button, text: button.innerHTML };
      button.classList.add("is-busy");
      button.setAttribute("aria-busy", "true");
      if (label) { button.textContent = label; }
    }
  };
  NB.on("task_done", function (p) {
    var entry = p && busy[p.key];
    if (entry) {
      entry.button.classList.remove("is-busy");
      entry.button.removeAttribute("aria-busy");
      entry.button.innerHTML = entry.text;
      delete busy[p.key];
    }
    if (p && p.error) { NB.toast("Stopped: " + p.error); }
  });

  // ---- toast
  var toastTimer = null;
  NB.toast = function (text, kind) {
    var el = NB.$("#toast");
    el.textContent = text;
    el.className = "show" + (kind === "ok" ? " ok" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.className = el.className.replace("show", "").trim(); }, 4500);
  };

  // ---- modal: focus trap, Esc closes, focus returns to where it was
  NB.modal = function (opts) {
    var previous = document.activeElement;
    var ov = document.createElement("div");
    ov.className = "ov";
    var box = document.createElement("div");
    box.className = "modal" + (opts.className ? " " + opts.className : "");
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    if (opts.title) {
      var h = document.createElement("h2");
      h.id = "modal-title-" + Date.now();
      h.textContent = opts.title;
      box.appendChild(h);
      box.setAttribute("aria-labelledby", h.id);
    } else if (opts.label) {
      box.setAttribute("aria-label", opts.label);
    }
    if (opts.sub) {
      var s = document.createElement("p");
      s.className = "modal-sub";
      s.textContent = opts.sub;
      box.appendChild(s);
    }
    if (opts.body) { box.appendChild(opts.body); }
    ov.appendChild(box);
    document.body.appendChild(ov);

    function focusables() {
      return NB.$$('button:not(:disabled),input:not(:disabled),select,a[href],[tabindex]:not([tabindex="-1"])', box);
    }
    function close() {
      ov.remove();
      document.removeEventListener("keydown", onKey, true);
      if (previous && previous.focus) { previous.focus(); }
      if (opts.onClose) { opts.onClose(); }
    }
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(); return; }
      if (e.key === "Tab") {
        var f = focusables();
        if (!f.length) { return; }
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    ov.addEventListener("mousedown", function (e) { if (e.target === ov) { close(); } });
    document.addEventListener("keydown", onKey, true);
    var target = (opts.initialFocus && NB.$(opts.initialFocus, box)) || focusables()[0];
    if (target) { target.focus(); }
    return { close: close, box: box };
  };

  // ---- confirm / prompt (NOBAD dialogs instead of the browser's)
  NB.confirm = function (o) {
    return new Promise(function (resolve) {
      var body = document.createElement("div"), done = false;
      body.innerHTML = '<div class="modal-actions"><button type="button" data-a="no">Cancel</button>' +
        '<button type="button" class="' + (o.danger ? "danger" : "pri") + '" data-a="yes"></button></div>';
      body.querySelector("[data-a=yes]").textContent = o.action || "OK";
      var m = NB.modal({ title: o.title, sub: o.text, body: body, initialFocus: "[data-a=no]",
        onClose: function () { if (!done) { resolve(false); } } });
      body.querySelector("[data-a=no]").addEventListener("click", function () { m.close(); });
      body.querySelector("[data-a=yes]").addEventListener("click", function () { done = true; m.close(); resolve(true); });
    });
  };
  NB.prompt = function (o) {
    return new Promise(function (resolve) {
      var body = document.createElement("form"), done = false;
      body.innerHTML = '<label class="field"><span></span><input type="text" name="v" required autocomplete="off" spellcheck="false"></label>' +
        '<div class="modal-actions"><button type="button" data-a="no">Cancel</button><button type="submit" class="pri"></button></div>';
      body.querySelector("span").textContent = o.label;
      body.querySelector("[type=submit]").textContent = o.action || "OK";
      body.v.value = o.value || "";
      var m = NB.modal({ title: o.title, body: body, initialFocus: "input",
        onClose: function () { if (!done) { resolve(null); } } });
      if (o.value) { var dot = o.value.lastIndexOf("."); body.v.setSelectionRange(0, dot > 0 ? dot : o.value.length); }
      body.addEventListener("submit", function (e) { e.preventDefault(); done = true; var v = body.v.value.trim(); m.close(); resolve(v); });
      body.querySelector("[data-a=no]").addEventListener("click", function () { m.close(); });
    });
  };

  // ---- context menu: arrow keys, Enter, Esc; entries are [id, label, shortcut] or ["-"]
  NB.contextMenu = function (x, y, entries, onPick) {
    var old = document.getElementById("ctxMenu");
    if (old) { old.remove(); }
    var previous = document.activeElement;
    var menu = document.createElement("div");
    menu.id = "ctxMenu";
    menu.className = "ctx";
    menu.setAttribute("role", "menu");
    menu.innerHTML = entries.map(function (e) {
      if (e[0] === "-") { return '<div class="ctx-sep" role="separator"></div>'; }
      return '<button type="button" role="menuitem" data-id="' + NB.esc(e[0]) + '"><span>' + NB.esc(e[1]) + "</span>" +
        (e[2] ? "<kbd>" + NB.esc(e[2]) + "</kbd>" : "") + "</button>";
    }).join("");
    document.body.appendChild(menu);
    var w = menu.offsetWidth, h = menu.offsetHeight;
    menu.style.left = Math.min(x, window.innerWidth - w - 8) + "px";
    menu.style.top = Math.min(y, window.innerHeight - h - 8) + "px";
    var items = NB.$$("[role=menuitem]", menu);
    function close() { menu.remove(); document.removeEventListener("mousedown", outside, true); if (previous && previous.focus) { previous.focus(); } }
    function outside(e) { if (!menu.contains(e.target)) { close(); } }
    document.addEventListener("mousedown", outside, true);
    menu.addEventListener("click", function (e) {
      var b = e.target.closest("[data-id]");
      if (b) { close(); onPick(b.getAttribute("data-id")); }
    });
    menu.addEventListener("keydown", function (e) {
      var i = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
      else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); close(); }
    });
    if (items[0]) { items[0].focus(); }
  };

  // ---- theme: "dark" | "light" | "system"
  var media = window.matchMedia("(prefers-color-scheme: light)");
  NB.themePref = "dark";
  try { NB.themePref = localStorage.getItem("nbfb-theme") || "dark"; } catch (e) { /* storage blocked */ }
  NB.applyTheme = function (pref) {
    NB.themePref = pref || "dark";
    try { localStorage.setItem("nbfb-theme", NB.themePref); } catch (e) { /* storage blocked */ }
    var dark = NB.themePref === "system" ? !media.matches : NB.themePref !== "light";
    var apply = function () { document.documentElement.setAttribute("data-theme", dark ? "dark" : "light"); };
    if (document.startViewTransition && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document.startViewTransition(apply);
    } else {
      apply();
    }
    NB.emit("theme", NB.themePref);
  };
  media.addEventListener("change", function () { if (NB.themePref === "system") { NB.applyTheme("system"); } });

  // ---- persisted UI state (layout only; never secrets)
  NB.uiState = function (key, value) {
    var store = {};
    try { store = JSON.parse(localStorage.getItem("nbfb-ui") || "{}"); } catch (e) { store = {}; }
    if (arguments.length === 1) { return store[key]; }
    store[key] = value;
    try { localStorage.setItem("nbfb-ui", JSON.stringify(store)); } catch (e) { /* storage blocked */ }
    return value;
  };
})();
