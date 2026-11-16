// Command palette (Ctrl+K): jump to a screen, run an action, or find a setting. Arrow keys + Enter, Esc closes.
(function () {
  "use strict";
  var NB = window.NB, esc = NB.esc;
  var settingsFields = null;

  function actions() {
    return [
      { group: "Actions", icon: "sun", label: "Switch between dark and light theme", run: NB.toggleTheme },
      { group: "Actions", icon: "window", label: "Show or hide the dock", hint: "Ctrl J", run: function () { NB.setDock(document.getElementById("dock").classList.contains("collapsed")); } },
      { group: "Actions", icon: "sidebar", label: "Collapse or expand the sidebar", hint: "Ctrl B", run: function () { document.getElementById("railToggle").click(); } },
      { group: "Actions", icon: "logs", label: "Show the activity log", run: function () { NB.setDock(true, "activity"); } }
    ];
  }
  function items() {
    var list = NB.SCREENS.map(function (s) {
      return { group: "Go to", icon: s.icon, label: s.label, hint: s.keys ? s.keys.replace("+", " ") : "", run: function () { NB.go(s.id); } };
    }).concat(actions());
    (settingsFields || []).forEach(function (f) {
      list.push({
        group: "Settings", icon: "settings", label: f.label, hint: f.groupLabel, keywords: (f.keywords || []).join(" ") + " " + f.description,
        run: function () { NB.go("settings", { field: f.id }); }
      });
    });
    return list;
  }
  function loadSettings() {
    if (settingsFields) { return; }
    NB.api("settings.schema").then(function (r) {
      if (!r.ok) { return; }
      var groups = {};
      r.data.groups.forEach(function (g) { groups[g.id] = g.label; });
      settingsFields = r.data.fields.map(function (f) { return Object.assign({ groupLabel: groups[f.group] }, f); });
    });
  }

  // Subsequence match with a bonus for word starts; label hits rank above keyword hits.
  function score(query, text) {
    if (!query) { return 1; }
    text = text.toLowerCase();
    var at = text.indexOf(query);
    if (at >= 0) { return 100 - at + (at === 0 || text[at - 1] === " " ? 30 : 0); }
    var qi = 0, s = 0;
    for (var i = 0; i < text.length && qi < query.length; i++) {
      if (text[i] === query[qi]) { s += i === 0 || text[i - 1] === " " ? 6 : 1; qi++; }
    }
    return qi === query.length ? s : 0;
  }

  function open() {
    loadSettings();
    var body = document.createElement("div");
    body.innerHTML =
      '<div class="palette-in">' + ICO("search") +
      '<input type="text" id="palInput" role="combobox" aria-expanded="true" aria-controls="palList" aria-autocomplete="list" ' +
      'placeholder="Search screens, actions and settings…" autocomplete="off" spellcheck="false" aria-label="Search"></div>' +
      '<div class="palette-list" id="palList" role="listbox" aria-label="Results"></div>' +
      '<div class="palette-foot"><span><kbd>↑</kbd> <kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span></div>';
    var m = NB.modal({ label: "Command palette", body: body, className: "palette", initialFocus: "#palInput" });
    var input = NB.$("#palInput", body), list = NB.$("#palList", body), shown = [], sel = 0;

    function draw() {
      var q = input.value.trim().toLowerCase();
      shown = items().map(function (it) {
        var s = Math.max(score(q, it.label) * 2, q && it.keywords ? score(q, it.keywords) : 0);
        return { it: it, s: s };
      }).filter(function (x) { return x.s > 0; }).sort(function (a, b) { return b.s - a.s; }).map(function (x) { return x.it; });
      if (!q) { shown = shown.filter(function (it) { return it.group !== "Settings"; }); }
      sel = Math.min(sel, Math.max(shown.length - 1, 0));
      if (!shown.length) { list.innerHTML = '<div class="pal-empty">No match. Try a screen, a setting or an action.</div>'; input.removeAttribute("aria-activedescendant"); return; }
      var html = "", group = null;
      shown.forEach(function (it, i) {
        if (q === "" && it.group !== group) { group = it.group; html += '<div class="pal-group" role="presentation">' + esc(group) + "</div>"; }
        html += '<div class="pal-item" role="option" id="pal-' + i + '" data-i="' + i + '" aria-selected="' + (i === sel) + '">' + ICO(it.icon) +
          "<span>" + esc(it.label) + "</span>" + (it.hint ? '<span class="hint">' + esc(it.hint) + "</span>" : "") + "</div>";
      });
      list.innerHTML = html;
      input.setAttribute("aria-activedescendant", "pal-" + sel);
      var active = NB.$("#pal-" + sel, list);
      if (active) { active.scrollIntoView({ block: "nearest" }); }
    }
    function run(i) {
      var it = shown[i];
      if (!it) { return; }
      m.close();
      it.run();
    }
    input.addEventListener("input", function () { sel = 0; draw(); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); sel = (sel + 1) % Math.max(shown.length, 1); draw(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); sel = (sel - 1 + shown.length) % Math.max(shown.length, 1); draw(); }
      else if (e.key === "Enter") { e.preventDefault(); run(sel); }
    });
    list.addEventListener("mousemove", function (e) {
      var row = e.target.closest(".pal-item");
      if (row && Number(row.getAttribute("data-i")) !== sel) { sel = Number(row.getAttribute("data-i")); draw(); }
    });
    list.addEventListener("click", function (e) {
      var row = e.target.closest(".pal-item");
      if (row) { run(Number(row.getAttribute("data-i"))); }
    });
    draw();
    // Settings load asynchronously the first time; redraw once they arrive.
    setTimeout(draw, 250);
  }

  NB.palette = { open: open };
})();
