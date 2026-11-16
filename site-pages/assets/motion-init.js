// NOBAD product pages: loaded first in <head>, before anything is drawn. It marks <html class="p-js"> so the
// entrance and scroll-reveal states in product.css apply only when JavaScript runs and motion is welcome.
// Without it (no JS, or prefers-reduced-motion) every block is simply shown.
(() => {
  "use strict";
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  document.documentElement.classList.add("p-js");
})();
