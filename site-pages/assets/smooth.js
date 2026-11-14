// NOBAD smooth motion: a tiny inertia scroller (no library) and off-screen animation pausing.
// Mouse and trackpad only; touch devices keep native scrolling, and reduced-motion users get none of it.
(() => {
  "use strict";
  const root = document.documentElement;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = window.matchMedia("(pointer: fine)").matches;

  const style = document.createElement("style");
  style.textContent =
    "html.smooth-js{scroll-behavior:auto!important}" +
    ".is-off,.is-off *,.is-off *::before,.is-off *::after{animation-play-state:paused!important}";
  document.head.appendChild(style);

  // 1. Looping animations only run in sections that are on (or near) the screen.
  const pauseOffscreen = () => {
    if (!("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver(
      entries => entries.forEach(e => e.target.classList.toggle("is-off", !e.isIntersecting)),
      { rootMargin: "150px 0px" }
    );
    document.querySelectorAll("main > section, main > div, header.hero, .hero, .ticker, footer").forEach(el => io.observe(el));
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", pauseOffscreen);
  else pauseOffscreen();

  if (reduce || !finePointer) return;

  // 2. Inertia wheel scrolling: the wheel sets a target, each frame eases toward it.
  const EASE = 10;                 // higher is snappier
  let target = window.scrollY, current = window.scrollY, raf = 0, last = 0;
  const maxY = () => Math.max(0, root.scrollHeight - window.innerHeight);
  const clamp = y => Math.max(0, Math.min(maxY(), y));
  root.classList.add("smooth-js");

  const tick = t => {
    const dt = last ? Math.min(0.05, (t - last) / 1000) : 1 / 60;
    last = t;
    current += (target - current) * (1 - Math.exp(-EASE * dt));
    if (Math.abs(target - current) < 0.4) current = target;
    window.scrollTo(0, current);
    if (current === target) { raf = 0; last = 0; return; }
    raf = requestAnimationFrame(tick);
  };
  const run = () => { if (!raf) raf = requestAnimationFrame(tick); };

  // Leave the wheel alone over anything that scrolls by itself (menus, code blocks, tables).
  const innerScroller = (el, dy) => {
    for (; el && el !== document.body && el !== root; el = el.parentElement) {
      const oy = getComputedStyle(el).overflowY;
      if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight + 1) {
        if ((dy > 0 && el.scrollTop + el.clientHeight < el.scrollHeight - 1) || (dy < 0 && el.scrollTop > 0)) return true;
      }
    }
    return false;
  };

  window.addEventListener("wheel", e => {
    if (e.ctrlKey || e.defaultPrevented || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
    let dy = e.deltaY;
    if (e.deltaMode === 1) dy *= 16; else if (e.deltaMode === 2) dy *= window.innerHeight;
    if (innerScroller(e.target, dy)) return;
    e.preventDefault();
    if (!raf) target = current = window.scrollY;
    target = clamp(target + dy);
    run();
  }, { passive: false });

  // Keyboard, scrollbar dragging and find-in-page stay native; just stay in sync with them.
  window.addEventListener("scroll", () => { if (!raf) target = current = window.scrollY; }, { passive: true });
  window.addEventListener("resize", () => { target = clamp(target); }, { passive: true });

  // In-page links glide with the same easing (the skip link keeps its native jump and focus).
  document.addEventListener("click", e => {
    const a = e.target.closest && e.target.closest('a[href^="#"]');
    if (!a || a.classList.contains("skip-link") || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
    const id = decodeURIComponent(a.getAttribute("href").slice(1));
    const el = id ? document.getElementById(id) : null;
    if (!el) return;
    e.preventDefault();
    const pad = parseFloat(getComputedStyle(root).scrollPaddingTop) || 0;
    if (!raf) current = window.scrollY;
    target = clamp(el.getBoundingClientRect().top + window.scrollY - pad);
    if (location.hash !== "#" + id) history.pushState(null, "", "#" + id);
    run();
  });
})();
