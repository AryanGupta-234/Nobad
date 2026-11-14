// Shared page chrome for every NOBAD page: the mobile menu, the deeper glass once the page scrolls, and the footer year.
(() => {
  "use strict";
  const nav = document.querySelector(".site-nav");
  if (nav) {
    const mark = () => nav.classList.toggle("scrolled", window.scrollY > 40);
    mark();
    window.addEventListener("scroll", mark, { passive: true });

    const toggle = document.getElementById("menuToggle");
    const pill = document.getElementById("navPill");
    if (toggle && pill) {
      const set = open => {
        pill.classList.toggle("open", open);
        toggle.setAttribute("aria-expanded", String(open));
        toggle.textContent = open ? "CLOSE −" : "MENU +";
      };
      toggle.addEventListener("click", () => set(!pill.classList.contains("open")));
      pill.querySelectorAll("a").forEach(a => a.addEventListener("click", () => set(false)));
      window.addEventListener("keydown", e => { if (e.key === "Escape") set(false); });
    }
  }
  document.querySelectorAll("[data-year]").forEach(el => { el.textContent = new Date().getFullYear(); });
})();
