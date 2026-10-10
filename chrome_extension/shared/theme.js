// Day / Night theme for the Lens, matching web_app/theme.js. Loaded in <head> so a saved
// choice applies before first paint; until the person chooses, the system setting wins.
(() => {
  const KEY = "eregion.theme";
  const root = document.documentElement;
  const prefersLight = matchMedia("(prefers-color-scheme: light)");
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "night") root.dataset.theme = saved;
  } catch { /* Storage is optional. */ }

  const current = () => root.dataset.theme || (prefersLight.matches ? "light" : "night");
  function sync() {
    const light = current() === "light";
    for (const toggle of document.querySelectorAll(".theme-toggle")) {
      toggle.dataset.state = light ? "light" : "night";
      toggle.querySelector(".night")?.setAttribute("aria-pressed", String(!light));
      toggle.querySelector(".day")?.setAttribute("aria-pressed", String(light));
    }
  }
  document.addEventListener("click", (event) => {
    const button = event.target.closest(".theme-toggle button");
    if (!button) return;
    root.dataset.theme = button.classList.contains("day") ? "light" : "night";
    try { localStorage.setItem(KEY, root.dataset.theme); } catch { /* The choice still applies to this panel. */ }
    sync();
  });
  prefersLight.addEventListener("change", sync);
  document.addEventListener("DOMContentLoaded", sync);
})();
