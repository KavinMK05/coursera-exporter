/* ============================================================
   coursera-exporter docs — shared interactions
   ============================================================ */
(function () {
  "use strict";

  /* ---------- Theme toggle ---------- */
  var KEY = "theme";
  function applyTheme(t) {
    var dark =
      t === "dark" ||
      (t === "system" &&
        window.matchMedia &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.classList.toggle("light", !dark);
    var btn = document.querySelector("[data-theme-toggle]");
    if (btn) {
      btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
      btn.querySelector("[data-theme-icon-sun]").style.display = dark ? "block" : "none";
      btn.querySelector("[data-theme-icon-moon]").style.display = dark ? "none" : "block";
    }
  }
  var stored = localStorage.getItem(KEY) || "system";
  applyTheme(stored);
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
      if ((localStorage.getItem(KEY) || "system") === "system") applyTheme("system");
    });
  }
  var toggle = document.querySelector("[data-theme-toggle]");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var isDark = document.documentElement.classList.contains("dark");
      var next = isDark ? "light" : "dark";
      localStorage.setItem(KEY, next);
      applyTheme(next);
    });
  }

  /* ---------- Active sidebar link ---------- */
  var path = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".nav-item").forEach(function (a) {
    var href = a.getAttribute("href");
    if (href === path || (path === "index.html" && href === "index.html")) {
      a.classList.add("is-active");
      a.setAttribute("aria-current", "page");
    }
  });

  /* ---------- Mobile sidebar ---------- */
  var burger = document.querySelector("[data-burger]");
  var sidebar = document.querySelector("[data-sidebar]");
  var scrim = document.querySelector("[data-scrim]");
  function closeSidebar() {
    if (sidebar) sidebar.classList.remove("is-open");
    if (scrim) scrim.classList.remove("is-open");
  }
  if (burger && sidebar && scrim) {
    burger.addEventListener("click", function () {
      sidebar.classList.add("is-open");
      scrim.classList.add("is-open");
    });
    scrim.addEventListener("click", closeSidebar);
    sidebar.addEventListener("click", function (e) {
      if (e.target.closest(".nav-item")) closeSidebar();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeSidebar();
    });
  }

  /* ---------- Copy buttons ---------- */
  var toastTimer;
  function showToast(msg) {
    var toast = document.querySelector("[data-toast]");
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add("is-show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.classList.remove("is-show"); }, 1500);
  }
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var block = btn.closest(".codeblock");
      var code = block ? block.querySelector("code") : null;
      if (!code) return;
      var text = code.innerText.replace(/^\$\s/, "").replace(/^\$\s/gm, "");
      navigator.clipboard.writeText(text).then(function () { showToast("Copied!"); });
    });
  });

  /* ---------- TOC scroll-spy ---------- */
  var tocLinks = document.querySelectorAll("[data-toc] a");
  if (tocLinks.length) {
    var headings = Array.prototype.map.call(tocLinks, function (a) {
      return document.getElementById(a.getAttribute("href").slice(1));
    });
    if ("IntersectionObserver" in window) {
      var spy = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) {
            tocLinks.forEach(function (l) { l.classList.remove("is-active"); });
            var active = document.querySelector('[data-toc] a[href="#' + e.target.id + '"]');
            if (active) active.classList.add("is-active");
          }
        });
      }, { rootMargin: "-80px 0px -70% 0px" });
      headings.forEach(function (h) { if (h) spy.observe(h); });
    }
  }

  /* ---------- GitHub star count ---------- */
  var countEl = document.querySelector("[data-star-count]");
  if (countEl) {
    var CACHE = "gh-stars-cache";
    function render(n) {
      countEl.textContent = n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n);
    }
    try {
      var raw = localStorage.getItem(CACHE);
      if (raw) {
        var parsed = JSON.parse(raw);
        if (parsed && Date.now() - parsed.t < 3600000) { render(parsed.n); return; }
      }
    } catch (e) {}
    fetch("https://api.github.com/repos/KavinMK05/coursera-exporter")
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (d) {
        var n = d.stargazers_count || 0;
        render(n);
        try { localStorage.setItem(CACHE, JSON.stringify({ n: n, t: Date.now() })); } catch (e) {}
      })
      .catch(function () {});
  }
})();