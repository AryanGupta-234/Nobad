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

  // Page switches: an orange progress line, plus a fade where the browser has no cross-page view transitions.
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const html = document.documentElement;
    const native = "onpagereveal" in window;
    if (!native) html.classList.add("nb-fade");
    const bar = document.createElement("div");
    bar.className = "nb-progress";
    bar.setAttribute("aria-hidden", "true");
    document.body.appendChild(bar);
    document.addEventListener("click", e => {
      const a = e.target.closest && e.target.closest("a[href]");
      if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (a.target && a.target !== "_self") return;
      if (a.hasAttribute("download")) return;
      const url = new URL(a.href, location.href);
      if (url.origin !== location.origin) return;
      if (url.pathname === location.pathname && url.search === location.search) return; // same page, a #section
      bar.classList.add("run");
      if (native) return;
      e.preventDefault();
      html.classList.add("nb-leaving");
      setTimeout(() => { location.href = url.href; }, 200);
    });
    // Coming back with the Back button restores the page from cache: clear the leaving state.
    window.addEventListener("pageshow", () => { html.classList.remove("nb-leaving"); bar.classList.remove("run"); });
  }
})();
