/* Moved out of index.html so the site's Content-Security-Policy needs no 'unsafe-inline'. */
    const NOBAD_CONFIG = {
      downloads: {}   // e.g. files: "https://...". Add a URL only once a real, published build exists
    };

    // Products and their maintainers, shown in "Built in the open". Adding a product or a maintainer is one line here.
    const NOBAD_PRODUCTS = [
      { product: "NOBAD VPN", page: "/products/vpn/", maintainer: "@AryanGupta-234", status: "Available" },
      { product: "NOBAD File Bridge", page: "/products/file-bridge/", maintainer: "@harshRaj1601", status: "In development" },
    ];
    (() => {
      const body = document.getElementById("roster");
      if (!body) return;
      const cell = (row, child) => { const td = document.createElement("td"); td.append(child); row.append(td); };
      const link = (text, href) => { const a = document.createElement("a"); a.textContent = text; a.href = href; return a; };
      const rows = NOBAD_PRODUCTS.filter(p => /^@[A-Za-z0-9-]{1,39}$/.test(p.maintainer) && /^\/products\/[a-z0-9-]+\/$/.test(p.page)).map(p => {
        const tr = document.createElement("tr");
        cell(tr, link(p.product, p.page));
        const m = link(p.maintainer, "https://github.com/" + p.maintainer.slice(1));
        m.rel = "noopener";
        cell(tr, m);
        const st = document.createElement("span");
        st.className = "st " + (/^available$/i.test(p.status) ? "ok" : "dev");
        st.textContent = p.status;
        cell(tr, st);
        return tr;
      });
      if (rows.length) body.replaceChildren(...rows);
    })();

    // Current year is dynamic.
    document.getElementById("year").textContent = new Date().getFullYear();

    // Download controls only become active when a real release URL is configured.
    const toast = document.getElementById("toast");
    let toastTimer;
    function showToast(message) {
      toast.textContent = message;
      toast.classList.add("show");
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => toast.classList.remove("show"), 2800);
    }
    document.querySelectorAll("[data-product]").forEach(button => {
      const key = button.dataset.product;
      const url = NOBAD_CONFIG.downloads[key];
      if (url && /^https:\/\//i.test(url)) {
        button.setAttribute("aria-disabled", "false");
        button.addEventListener("click", () => window.open(url, "_blank", "noopener,noreferrer"));
        button.innerHTML = 'Download <span>↗</span>';
      } else {
        button.addEventListener("click", () => showToast("No public build is available yet."));
      }
    });

    // Scroll ring: the words turn only while the visitor scrolls down, easing to a stop
    // instead of jumping, and the orange arc shows how far down the page they are.
    (() => {
      const wheel = document.getElementById("scrollOrbit");
      const rotor = document.getElementById("scrollOrbitLayer");
      if (!wheel || !rotor) return;
      const root = document.documentElement;
      const progress = () => {
        const max = Math.max(1, root.scrollHeight - window.innerHeight);
        wheel.style.setProperty("--orbit-progress", (100 - Math.min(1, window.scrollY / max) * 100).toFixed(2));
      };
      progress();
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      let lastY = window.scrollY, target = 0, angle = 0, raf = 0, last = 0;
      const tick = t => {
        const dt = last ? Math.min(0.05, (t - last) / 1000) : 1 / 60;
        last = t;
        angle += (target - angle) * (1 - Math.exp(-6 * dt));
        if (Math.abs(target - angle) < 0.05) angle = target;
        rotor.style.transform = `rotate(${angle.toFixed(2)}deg)`;
        if (angle === target) { raf = 0; last = 0; return; }
        raf = requestAnimationFrame(tick);
      };
      window.addEventListener("scroll", () => {
        progress();
        const y = window.scrollY, delta = y - lastY;
        lastY = y;
        if (reduce || delta <= 0) return;
        target += delta * 0.3;
        if (!raf) raf = requestAnimationFrame(tick);
      }, { passive: true });
      window.addEventListener("resize", progress, { passive: true });
    })();

    // Scroll-aware navigation affordance.
    const navLinks = [...document.querySelectorAll(".nav-pill a")];
    // Only links to a section of this page ("#id" or "/#id") map to sections; "/products/vpn/" or "/support/" don't.
    const sectionId = link => { const m = /^\/?#([\w-]+)$/.exec(link.getAttribute("href") || ""); return m ? m[1] : null; };
    const observedSections = navLinks.map(sectionId).filter(Boolean).map(id => document.getElementById(id)).filter(Boolean);
    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (!entry.isIntersecting) return;
          navLinks.forEach(link => {
            if (sectionId(link) === entry.target.id) link.setAttribute("aria-current", "location");
            else link.removeAttribute("aria-current");
          });
        });
      }, { rootMargin: "-30% 0px -60% 0px" });
      observedSections.forEach(section => observer.observe(section));
    }

    // Scroll reveals, the card spotlight and the hero globe (paused for reduced motion).
    (() => {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      // Glass cards drift gently against the pointer, each at its own depth.
      const layer = document.getElementById("glassLayer");
      const hero = document.getElementById("top");
      if (layer && hero && !reduce && window.matchMedia("(pointer: fine)").matches) {
        const cards = [...layer.querySelectorAll(".glass")];
        let raf = 0;
        hero.addEventListener("pointermove", e => {
          cancelAnimationFrame(raf);
          raf = requestAnimationFrame(() => {
            const r = hero.getBoundingClientRect();
            const x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
            cards.forEach(c => {
              const d = +c.dataset.depth || 20;
              c.style.transform = `translate3d(${-x * d}px, ${-y * d}px, 0) rotateX(${y * 6}deg) rotateY(${-x * 8}deg)`;
            });
          });
        });
        hero.addEventListener("pointerleave", () => cards.forEach(c => { c.style.transform = ""; }));
      }
      const items = document.querySelectorAll(".rv");
      if (reduce || !("IntersectionObserver" in window)) { items.forEach(el => el.classList.add("in")); }
      else {
        const io = new IntersectionObserver(entries => entries.forEach(e => {
          if (!e.isIntersecting) return;
          e.target.classList.add("in");
          io.unobserve(e.target);
        }), { threshold: .15 });
        items.forEach(el => io.observe(el));
      }
      document.querySelectorAll(".product-card").forEach(card => {
        let raf = 0, x = 0, y = 0;
        card.addEventListener("pointermove", e => {
          x = e.clientX; y = e.clientY;
          if (raf) return;
          raf = requestAnimationFrame(() => {
            raf = 0;
            const r = card.getBoundingClientRect();
            card.style.setProperty("--mx", (x - r.left) + "px");
            card.style.setProperty("--my", (y - r.top) + "px");
          });
        });
      });
    })();
  
