// Runs in <head> before first paint, so the page never flashes the wrong theme.
// The saved choice is mirrored to localStorage by core.js; the database setting stays the source of truth.
(function () {
  var pref = "dark";
  try { pref = localStorage.getItem("nbfb-theme") || "dark"; } catch (e) { /* storage blocked */ }
  var dark = pref === "system" ? !window.matchMedia("(prefers-color-scheme: light)").matches : pref !== "light";
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
})();
