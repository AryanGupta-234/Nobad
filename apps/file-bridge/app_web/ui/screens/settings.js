// Settings: drawn from the server's schema (app_web/settings_store.py). Every change is validated and saved there
// at once; each row reports "Saved" or the reason it couldn't be saved.
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, $$ = NB.$$, esc = NB.esc;

  function control(f, value) {
    var id = "set-" + f.id.replace(/\./g, "-");
    if (f.kind === "bool") {
      return '<button type="button" class="sw" role="switch" id="' + id + '" data-id="' + esc(f.id) + '" aria-checked="' + (value === true) +
        '" aria-labelledby="' + id + '-label" aria-describedby="' + id + '-desc ' + id + '-state"></button>';
    }
    if (f.kind === "choice" && f.choices.length <= 3) {
      return '<div class="seg" role="radiogroup" aria-labelledby="' + id + '-label" data-id="' + esc(f.id) + '">' +
        f.choices.map(function (c) {
          return '<button type="button" role="radio" data-value="' + esc(c.value) + '" aria-checked="' + (c.value === value) + '"' +
            ' tabindex="' + (c.value === value ? "0" : "-1") + '">' + esc(c.label) + "</button>";
        }).join("") + "</div>";
    }
    if (f.kind === "choice") {
      return '<select id="' + id + '" name="' + esc(f.id) + '" data-id="' + esc(f.id) + '">' + f.choices.map(function (c) {
        return '<option value="' + esc(c.value) + '"' + (c.value === value ? " selected" : "") + ">" + esc(c.label) + "</option>";
      }).join("") + "</select>";
    }
    if (f.kind === "int") {
      return '<input type="number" id="' + id + '" name="' + esc(f.id) + '" data-id="' + esc(f.id) + '" inputmode="numeric" min="' + f.min + '" max="' + f.max +
        '" step="1" value="' + esc(value) + '" aria-describedby="' + id + '-desc ' + id + '-state">';
    }
    return '<input type="text" id="' + id + '" name="' + esc(f.id) + '" data-id="' + esc(f.id) + '" value="' + esc(value) + '" placeholder="' + esc(f.placeholder) +
      '" spellcheck="false" autocomplete="off" aria-describedby="' + id + '-desc ' + id + '-state">';
  }

  function row(f, value) {
    var id = "set-" + f.id.replace(/\./g, "-");
    var labelTag = (f.kind === "choice" && f.choices.length <= 3) || f.kind === "bool"
      ? '<span class="set-label" id="' + id + '-label">' + esc(f.label) + "</span>"
      : '<label for="' + id + '" id="' + id + '-label">' + esc(f.label) + "</label>";
    var hint = f.kind === "int" ? " From " + f.min + " to " + f.max + "." : "";
    return '<div class="set-row" data-row="' + esc(f.id) + '" data-search="' +
      esc((f.label + " " + f.description + " " + (f.keywords || []).join(" ")).toLowerCase()) + '">' +
      "<div>" + labelTag + '<div class="set-desc" id="' + id + '-desc">' + esc(f.description + hint) + "</div></div>" +
      '<div class="set-ctl">' + control(f, value) + '<div class="set-state" id="' + id + '-state" aria-live="polite"></div></div></div>';
  }

  function save(el, id, value) {
    var r = el.closest(".set-row"), state = $(".set-state", r), input = $("input", r);
    state.className = "set-state";
    state.textContent = "Saving…";
    NB.api("settings.set", { id: id, value: value }).then(function (res) {
      if (res.ok) {
        state.className = "set-state saved";
        state.textContent = "Saved";
        if (input) { input.removeAttribute("aria-invalid"); input.value = res.data.value; }
        if (id === "web_ui.theme") { NB.applyTheme(res.data.value); }
        setTimeout(function () { if (state.textContent === "Saved") { state.textContent = ""; } }, 2000);
      } else {
        state.className = "set-state error";
        state.textContent = res.error || "Couldn't save.";
        if (input) { input.setAttribute("aria-invalid", "true"); }
      }
    });
  }

  function bind(root, values) {
    $$(".seg", root).forEach(function (seg) {
      var id = seg.getAttribute("data-id"), radios = $$("[role=radio]", seg);
      function pick(btn) {
        radios.forEach(function (b) { var on = b === btn; b.setAttribute("aria-checked", on); b.tabIndex = on ? 0 : -1; });
        btn.focus();
        save(seg, id, btn.getAttribute("data-value"));
      }
      seg.addEventListener("click", function (e) { var b = e.target.closest("[role=radio]"); if (b && b.getAttribute("aria-checked") !== "true") { pick(b); } });
      seg.addEventListener("keydown", function (e) {
        var i = radios.indexOf(document.activeElement);
        if (i < 0 || (e.key !== "ArrowRight" && e.key !== "ArrowLeft")) { return; }
        e.preventDefault();
        pick(radios[(i + (e.key === "ArrowRight" ? 1 : radios.length - 1)) % radios.length]);
      });
    });
    $$(".sw[data-id]", root).forEach(function (sw) {
      sw.addEventListener("click", function () {
        var next = sw.getAttribute("aria-checked") !== "true";
        sw.setAttribute("aria-checked", String(next));
        save(sw, sw.getAttribute("data-id"), next);
      });
    });
    $$("select[data-id]", root).forEach(function (sel) {
      sel.addEventListener("change", function () { save(sel, sel.getAttribute("data-id"), sel.value); });
    });
    $$("input[data-id]", root).forEach(function (input) {
      var id = input.getAttribute("data-id");
      function commit() {
        var v = input.type === "number" ? input.value : input.value;
        if (String(v) !== String(values[id])) { values[id] = v; save(input, id, v); }
      }
      input.addEventListener("change", commit);
      input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); commit(); } });
    });
  }

  function filter(root, q) {
    q = q.trim().toLowerCase();
    var any = false;
    $$(".set-group", root).forEach(function (g) {
      var visible = 0;
      $$(".set-row", g).forEach(function (r) {
        var hit = !q || r.getAttribute("data-search").indexOf(q) >= 0;
        r.hidden = !hit;
        if (hit) { visible++; }
      });
      g.hidden = visible === 0;
      if (visible) { any = true; }
    });
    $(".settings-none", root).hidden = any;
  }

  NB.screens.settings = {
    ready: true,
    render: function (el, _screen, opts) {
      el.innerHTML = '<div class="screen-head"><div><h1>Settings</h1><p>Changes are saved as soon as you make them, and the classic window uses them too.</p></div></div>' +
        '<div class="card"><div class="skel" style="height:14px;width:40%"></div><div class="skel" style="height:14px;width:70%;margin-top:12px"></div></div>';
      NB.api("settings.schema").then(function (r) {
        if (!r.ok) { el.querySelector(".card").innerHTML = '<p class="muted">' + esc(r.error) + "</p>"; return; }
        var d = r.data, values = d.values;
        var nav = d.groups.map(function (g) { return '<a href="#" data-group="' + esc(g.id) + '">' + esc(g.label) + "</a>"; }).join("");
        var groups = d.groups.map(function (g) {
          var fields = d.fields.filter(function (f) { return f.group === g.id; });
          return '<section class="card set-group" id="group-' + esc(g.id) + '" aria-labelledby="group-' + esc(g.id) + '-h">' +
            '<h2 id="group-' + esc(g.id) + '-h">' + esc(g.label) + "</h2>" + fields.map(function (f) { return row(f, values[f.id]); }).join("") + "</section>";
        }).join("");
        el.innerHTML = '<div class="screen-head"><div><h1>Settings</h1><p>Changes are saved as soon as you make them, and the classic window uses them too.</p></div></div>' +
          '<div class="settings"><nav class="settings-nav" aria-label="Setting groups"><input type="search" class="settings-search" id="setSearch" ' +
          'placeholder="Find a setting…" aria-label="Find a setting" autocomplete="off" spellcheck="false">' + nav + "</nav>" +
          '<div class="settings-groups">' + groups + '<div class="card settings-none" hidden>No setting matches. Try another word.</div></div></div>';
        bind(el, values);
        $("#setSearch", el).addEventListener("input", function (e) { filter(el, e.target.value); });
        $$(".settings-nav a", el).forEach(function (a) {
          a.addEventListener("click", function (e) {
            e.preventDefault();
            $$(".settings-nav a", el).forEach(function (x) { x.removeAttribute("aria-current"); });
            a.setAttribute("aria-current", "true");
            var g = $("#group-" + a.getAttribute("data-group"), el);
            g.scrollIntoView({ block: "start", behavior: "smooth" });
            var first = $("input,select,[role=radio][tabindex='0']", g);
            if (first) { first.focus({ preventScroll: true }); }
          });
        });
        if (opts && opts.field) {
          var target = $('[data-row="' + opts.field + '"]', el);
          if (target) {
            target.scrollIntoView({ block: "center" });
            if (NB.flash) { NB.flash(target); }
            var c = $("input,select,[role=radio][tabindex='0']", target);
            if (c) { c.focus({ preventScroll: true }); }
          }
        }
      });
    }
  };
})();
