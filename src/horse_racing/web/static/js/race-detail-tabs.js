(() => {
  const root = document.querySelector("[data-race-detail-workspace]");
  if (!root) return;
  const nav = root.querySelector(".race-detail-tabs");
  const links = [...nav.querySelectorAll("[data-race-detail-tab]")];
  const availableTabs = new Set(links.map(link => link.dataset.raceDetailTab));
  const panes = new Map([...root.querySelectorAll("[data-race-detail-pane]")]
    .map(pane => [pane.dataset.raceDetailPane, pane]));
  const activate = key => {
    if (!availableTabs.has(key)) key = "result";
    panes.forEach((pane, name) => { pane.hidden = name !== key; });
    links.forEach(link => {
      if (link.dataset.raceDetailTab === key) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    root.dispatchEvent(new CustomEvent("race-detail-pane-shown", { detail:key }));
  };
  const restore = () => {
    const url = new URL(window.location.href);
    let target = null;
    try { target = document.getElementById(decodeURIComponent(url.hash.slice(1))); } catch { /* Invalid fragment. */ }
    const anchoredPane = target?.closest("[data-race-detail-pane]");
    activate(anchoredPane?.dataset.raceDetailPane || url.searchParams.get("tab") || "result");
    if (anchoredPane) requestAnimationFrame(() => target.scrollIntoView({ block:"start" }));
  };
  links.forEach(link => link.addEventListener("click", event => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const url = new URL(link.href);
    history.pushState(null, "", url);
    activate(link.dataset.raceDetailTab);
    // Keep the selected pane in view when switching from a long panel.
    if (nav.getBoundingClientRect().top < 0) nav.scrollIntoView({ block:"start" });
  }));
  window.addEventListener("popstate", restore);
  window.addEventListener("hashchange", restore);
  const header = document.querySelector(".site-header");
  const measureHeader = () => root.style.setProperty("--race-detail-header-offset", `${Math.ceil(header?.getBoundingClientRect().height || 0)}px`);
  if (header && typeof ResizeObserver === "function") new ResizeObserver(measureHeader).observe(header);
  else window.addEventListener("resize", measureHeader, { passive:true });
  measureHeader();
  restore();
})();
