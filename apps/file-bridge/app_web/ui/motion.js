// Motion, ported from NOBAD VPN (app.js ptrFrame / ripple / lens, app_ext.js visual effects):
// * hover glow that follows the pointer on buttons (--bx/--by) and a soft spotlight on cards (--mx/--my),
//   updated at most once per frame;
// * a ripple from the press point on buttons;
// * a "lens" that slides between the active rail item and between dock tabs;
// * a short flash on a setting the palette jumped to;
// * "Visual effects" (body.fx): ambient glow in the background and frosted surfaces. Off by default, like VPN.
// Everything respects prefers-reduced-motion (motion.css and the checks below).
(function () {
  "use strict";
  var NB = window.NB, $ = NB.$, $$ = NB.$$;
  var calm = window.matchMedia("(prefers-reduced-motion: reduce)");

  // ---- pointer-following glow (one update per animation frame)
  var pending = null;
  function frame() {
    var e = pending;
    pending = null;
    if (!e || !e.target || !e.target.closest) { return; }
    var card = e.target.closest(".card");
    if (card) {
      var cr = card.getBoundingClientRect();
      card.style.setProperty("--mx", (e.clientX - cr.left) + "px");
      card.style.setProperty("--my", (e.clientY - cr.top) + "px");
    }
    var btn = e.target.closest("button");
    if (btn) {
      var br = btn.getBoundingClientRect();
      btn.style.setProperty("--bx", (e.clientX - br.left) + "px");
      btn.style.setProperty("--by", (e.clientY - br.top) + "px");
    }
  }
  document.addEventListener("pointermove", function (e) {
    if (!pending) { requestAnimationFrame(frame); }
    pending = e;
  }, { passive: true });

  // ---- ripple from the press point (clipped by its own wrapper, so rail markers outside the button stay visible)
  document.addEventListener("pointerdown", function (e) {
    if (calm.matches || e.button !== 0) { return; }
    var b = e.target.closest && e.target.closest("button");
    if (!b || b.disabled || b.classList.contains("sw") || b.closest(".winctl")) { return; }
    var r = b.getBoundingClientRect(), d = Math.max(r.width, r.height) * 2;
    var wrap = document.createElement("span");
    wrap.className = "rip-wrap";
    wrap.setAttribute("aria-hidden", "true");
    var s = document.createElement("i");
    s.className = "rip";
    s.style.cssText = "width:" + d + "px;height:" + d + "px;left:" + (e.clientX - r.left - d / 2) + "px;top:" + (e.clientY - r.top - d / 2) + "px";
    wrap.appendChild(s);
    b.appendChild(wrap);
    setTimeout(function () { wrap.remove(); }, 650);
  }, { passive: true });

  // ---- sliding lens behind the active item of a group
  function placeLens(container, lens, active) {
    if (!container || !lens) { return; }
    if (!active || active.offsetParent === null) { lens.style.opacity = "0"; return; }
    lens.style.opacity = "1";
    lens.style.width = active.offsetWidth + "px";
    lens.style.height = active.offsetHeight + "px";
    lens.style.transform = "translate(" + active.offsetLeft + "px," + active.offsetTop + "px)";
  }
  function ensureLens(container, cls) {
    var lens = container && container.querySelector(":scope > ." + cls);
    if (container && !lens) {
      lens = document.createElement("i");
      lens.className = "lens " + cls;
      lens.setAttribute("aria-hidden", "true");
      container.insertBefore(lens, container.firstChild);
    }
    return lens;
  }
  function updateLenses() {
    var rail = $("#rail"), bar = $(".dock-bar");
    placeLens(rail, ensureLens(rail, "rail-lens"), $(".rail-item[aria-current=page]", rail));
    placeLens(bar, ensureLens(bar, "dock-lens"), $(".dock-tab[aria-selected=true]", bar));
  }
  NB.updateLenses = function () { requestAnimationFrame(updateLenses); };
  // The rail and the dock change through clicks, keys and routing; one observer catches all of them.
  function watch() {
    var mo = new MutationObserver(NB.updateLenses);
    mo.observe($("#rail"), { subtree: true, attributes: true, attributeFilter: ["aria-current"] });
    mo.observe($(".dock-bar"), { subtree: true, attributes: true, attributeFilter: ["aria-selected"] });
    mo.observe($("#dock"), { attributes: true, attributeFilter: ["class"] });
    mo.observe($("#app"), { attributes: true, attributeFilter: ["class"] });
    window.addEventListener("resize", NB.updateLenses);
    var rail = $("#rail");
    rail.addEventListener("transitionend", NB.updateLenses);
    NB.updateLenses();
    setTimeout(NB.updateLenses, 300);
  }

  // ---- flash a row the user was sent to
  NB.flash = function (el) {
    if (!el) { return; }
    el.classList.remove("nb-flash");
    void el.offsetWidth;                  // restart the animation
    el.classList.add("nb-flash");
    setTimeout(function () { el.classList.remove("nb-flash"); }, 1700);
  };

  // ---- visual effects (setting web_ui.visual_effects)
  NB.setVisualEffects = function (on) { document.body.classList.toggle("fx", !!on); };
  NB.on("setting_changed", function (p) { if (p && p.id === "web_ui.visual_effects") { NB.setVisualEffects(p.value); } });

  document.addEventListener("DOMContentLoaded", function () {
    // shell.js renders the rail on DOMContentLoaded too; wait one frame so it exists.
    requestAnimationFrame(watch);
    NB.api("settings.schema").then(function (r) {
      if (r.ok) { NB.setVisualEffects(r.data.values["web_ui.visual_effects"]); }
    });
  });
})();
