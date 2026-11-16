// NOBAD product pages: scroll reveal, console typing order, pointer spotlight and a light tilt on the hero panel.
// Pure decoration: without this script (or with reduced motion) everything is simply shown.
(() => {
  "use strict";
  const root = document.documentElement;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = window.matchMedia("(pointer: fine)").matches;

  // Console lines type in one after another.
  document.querySelectorAll(".p-panel-body").forEach(body => {
    let i = 0;
    body.querySelectorAll(":scope > .ln, :scope > .p-panes, :scope > .p-verdict").forEach(el => {
      el.classList.add("p-type");
      el.style.setProperty("--i", String(i++));
    });
  });

  // motion-init.js sets .p-js in <head>; without it (or with reduced motion) nothing is hidden or animated.
  if (reduce || !root.classList.contains("p-js")) return;

  // Consoles further down the page start typing only when they come into view.
  if ("IntersectionObserver" in window) {
    const later = document.querySelectorAll("main section .p-panel");
    const io = new IntersectionObserver(es => es.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add("p-on"); io.unobserve(e.target); }
    }), { threshold: 0.3 });
    later.forEach(p => { p.classList.add("p-wait"); io.observe(p); });
  }

  // Scroll reveal, staggered within each group of siblings.
  if ("IntersectionObserver" in window) {
    const groups = [".p-label", ".p-head", ".p-pillar", ".p-feat", ".p-step", ".p-trust-item", ".p-shot", ".p-status",
      ".p-faq details", ".p-list li", ".p-specs > div", ".p-chips", ".p-note", ".p-aside", ".p-intel .p-panel"];
    const items = document.querySelectorAll(groups.map(g => "main section " + g).join(","));
    const finish = el => { el.classList.remove("p-rv", "in"); el.style.removeProperty("--d"); };
    const io = new IntersectionObserver(entries => entries.forEach(e => {
      if (!e.isIntersecting) return;
      const el = e.target;
      io.unobserve(el);
      el.classList.add("in");
      // Hand the element back to its own hover transitions once it has arrived.
      el.addEventListener("transitionend", function done(ev) {
        if (ev.target !== el || ev.propertyName !== "opacity") return;
        el.removeEventListener("transitionend", done);
        finish(el);
      });
      setTimeout(() => finish(el), 1400);
    }), { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
    groups.forEach(g => {
      const own = g.split(/[ >]+/).pop();
      document.querySelectorAll("main section " + g).forEach(el => {
        const idx = [...el.parentElement.children].filter(c => c.matches(own)).indexOf(el);
        el.style.setProperty("--d", Math.min(Math.max(idx, 0), 6) * 0.06 + "s");
      });
    });
    items.forEach(el => { el.classList.add("p-rv"); io.observe(el); });
  }

  if (!fine) return;

  // A soft light follows the pointer across pillars and steps.
  document.querySelectorAll(".p-pillar, .p-step").forEach(card => {
    let raf = 0, x = 0, y = 0;
    card.addEventListener("pointermove", e => {
      x = e.clientX; y = e.clientY;
      if (raf) return;
      raf = requestAnimationFrame(() => {      // one read and one write per frame
        raf = 0;
        const r = card.getBoundingClientRect();
        card.style.setProperty("--mx", x - r.left + "px");
        card.style.setProperty("--my", y - r.top + "px");
      });
    });
  });

  // The hero console tilts a little toward the pointer, once its entrance animation is over.
  const panel = document.querySelector(".p-hero .p-panel");
  const hero = document.querySelector(".p-hero");
  if (panel && hero) {
    let ready = false, raf = 0;
    panel.addEventListener("animationend", e => { if (e.target === panel) { panel.style.animation = "none"; ready = true; } });
    hero.addEventListener("pointermove", e => {
      if (!ready || raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const r = panel.getBoundingClientRect();
        const x = (e.clientX - (r.left + r.width / 2)) / window.innerWidth;
        const y = (e.clientY - (r.top + r.height / 2)) / window.innerHeight;
        panel.style.transform = `perspective(1200px) rotateY(${(x * 7).toFixed(2)}deg) rotateX(${(-y * 7).toFixed(2)}deg)`;
      });
    });
    hero.addEventListener("pointerleave", () => { panel.style.transform = ""; });
  }
})();
