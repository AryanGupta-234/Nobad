// NOBAD title bar (frameless window): the header is the window's title bar. Ported from NOBAD VPN's app_ext.js.
// Window buttons, drag on empty header space (Windows' own move loop: snapping works), double-click to maximise,
// invisible resize edges (Windows' own resize loop), and a short fade before minimise/close.
(function () {
  "use strict";
  var NB = window.NB;
  var TB = { on: false, max: false };
  var ICONS = {
    min: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M1 6.5h10"/></svg>',
    max: '<svg viewBox="0 0 12 12" aria-hidden="true"><rect x="1.5" y="1.5" width="9" height="9" rx="1"/></svg>',
    res: '<svg viewBox="0 0 12 12" aria-hidden="true"><rect x="1.5" y="3.5" width="7" height="7" rx="1"/><path d="M3.5 3.5V2.5a1 1 0 0 1 1-1h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-1"/></svg>',
    close: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 2l8 8M10 2l-8 8"/></svg>'
  };

  function enable(state) {
    if (TB.on || !state || !state.frameless) { return; }
    var header = document.querySelector("header.top");
    if (!header) { return; }
    TB.on = true;
    document.body.classList.add("tb");

    var ctl = document.createElement("div");
    ctl.className = "winctl";
    ctl.setAttribute("role", "group");
    ctl.setAttribute("aria-label", "Window");
    ctl.innerHTML =
      '<button type="button" data-w="minimize" title="Minimize" aria-label="Minimize">' + ICONS.min + "</button>" +
      '<button type="button" data-w="maximize" title="Maximize" aria-label="Maximize">' + ICONS.max + "</button>" +
      '<button type="button" data-w="close" class="x" title="Close" aria-label="Close">' + ICONS.close + "</button>";
    header.appendChild(ctl);

    function setMax(on) {
      TB.max = !!on;
      document.body.classList.toggle("tb-max", TB.max);
      var b = ctl.querySelector('[data-w="maximize"]');
      b.innerHTML = TB.max ? ICONS.res : ICONS.max;
      b.title = TB.max ? "Restore" : "Maximize";
      b.setAttribute("aria-label", b.title);
    }
    function win(act, extra) {
      return NB.api("window.action", Object.assign({ do: act }, extra || {})).then(function (r) {
        if (r && r.ok && r.data && "maximized" in r.data) { setMax(r.data.maximized); }
        return r;
      });
    }

    // Minimise / close animation: the frameless window has no native caption, so Windows doesn't animate it.
    // The page fades and shrinks for 150 ms first, then settles back in when shown again (opacity + transform only).
    var calm = window.matchMedia("(prefers-reduced-motion: reduce)");
    var root = document.documentElement;
    var away = false;
    function leave() {
      return new Promise(function (resolve) {
        if (calm.matches) { resolve(); return; }
        root.classList.remove("nb-enter");
        root.classList.add("nb-leave");
        setTimeout(resolve, 150);
      });
    }
    function enter() {
      if (!away && !root.classList.contains("nb-leave")) { return; }
      away = false;
      root.classList.remove("nb-leave");
      if (calm.matches) { return; }
      root.classList.add("nb-enter");
      setTimeout(function () { root.classList.remove("nb-enter"); }, 260);
    }
    document.addEventListener("visibilitychange", function () { if (!document.hidden) { enter(); } });
    window.addEventListener("focus", function () { if (away) { enter(); } });

    ctl.addEventListener("click", function (e) {
      var b = e.target.closest("[data-w]");
      if (!b) { return; }
      var act = b.getAttribute("data-w");
      if (act === "minimize" || act === "close") {
        leave().then(function () { away = true; return win(act); }).then(function (r) {
          // if it didn't actually minimise or close, come straight back
          setTimeout(function () { if (!document.hidden && document.hasFocus()) { enter(); } }, 600);
          return r;
        });
      } else {
        win(act);
      }
    });

    // Drag on empty title-bar space (not on buttons, links, inputs or pills); double-click maximises like Windows.
    function interactive(el) {
      return el.closest("button,a,input,select,textarea,label,[role=button],kbd,.status-pill,.winctl");
    }
    header.addEventListener("mousedown", function (e) {
      if (e.button === 0 && e.detail === 1 && !interactive(e.target)) { win("drag"); }
    });
    header.addEventListener("dblclick", function (e) { if (!interactive(e.target)) { win("maximize"); } });

    // Invisible resize edges and corners.
    ["t", "b", "l", "r", "tl", "tr", "bl", "br"].forEach(function (edge) {
      var g = document.createElement("div");
      g.className = "rz rz-" + edge;
      g.setAttribute("aria-hidden", "true");
      g.addEventListener("mousedown", function (e) {
        if (e.button === 0 && !TB.max) { e.preventDefault(); win("resize", { edge: edge }); }
      });
      document.body.appendChild(g);
    });

    setMax(state.maximized);
    window.addEventListener("resize", function () {
      clearTimeout(TB.timer);
      TB.timer = setTimeout(function () { win("state"); }, 250);
    });
  }

  NB.titlebar = { enable: enable };
})();
