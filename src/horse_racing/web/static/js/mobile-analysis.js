(() => {
  "use strict";
  const root = document.querySelector("[data-analysis-page]");
  if (!root) return;

  const form = root.querySelector("[data-auto-submit]");
  if (form) {
    form.addEventListener("change", (event) => {
      if (event.target.matches("input[type=date]")) form.submit();
    });
  }

  const dossiers = [...root.querySelectorAll("[data-dossier]")];
  if (!dossiers.length) return;

  const ids = dossiers.map((article) => Number(article.dataset.dossier));
  const params = new URLSearchParams(location.search);
  const hash = location.hash.match(/^#runner-(\d+)$/);
  const requested = Number(params.get("entry") || (hash ? hash[1] : 0));
  let selected = ids.includes(requested) ? requested : ids[0];
  let summaries = [];
  try {
    summaries = JSON.parse(document.getElementById("ma-pace-summaries")?.textContent || "[]");
  } catch (_) {
    summaries = [];
  }
  const summaryById = new Map(summaries.map((row) => [Number(row.entry_id), row]));

  function showTab(article, name) {
    if (!article || !name) return;
    article.querySelectorAll("[data-record-tab]").forEach((button) => {
      button.setAttribute("aria-selected", String(button.dataset.recordTab === name));
    });
    article.querySelectorAll("[data-record-pane]").forEach((pane) => {
      pane.hidden = pane.dataset.recordPane !== name;
    });
  }

  function updatePaceSummary(id) {
    const node = root.querySelector("[data-pace-summary]");
    const row = summaryById.get(id);
    if (!node || !row) return;
    node.textContent = `${row.number}번 ${row.horse} · 초반 ${row.early} · 중반 ${row.middle} · 종반 ${row.late}`;
  }

  function selectRunner(id, { scroll = false } = {}) {
    if (!ids.includes(id)) return;
    selected = id;
    dossiers.forEach((article) => {
      const on = Number(article.dataset.dossier) === id;
      article.classList.toggle("is-active", on);
      article.hidden = !on;
    });
    root.querySelectorAll("[data-select-runner]").forEach((button) => {
      button.setAttribute("aria-pressed", String(Number(button.dataset.selectRunner) === id));
      button.classList.toggle("is-selected", Number(button.dataset.selectRunner) === id);
    });
    updatePaceSummary(id);
    if (scroll) {
      document.getElementById("ma-records")?.scrollIntoView({ behavior: "auto", block: "start" });
    }
  }

  root.addEventListener("click", (event) => {
    const select = event.target.closest("[data-select-runner]");
    if (select) {
      const stay = Boolean(select.closest("[data-pace-board]"));
      selectRunner(Number(select.dataset.selectRunner), { scroll: !stay });
      return;
    }
    const tab = event.target.closest("[data-record-tab]");
    if (tab) showTab(tab.closest("[data-dossier]"), tab.dataset.recordTab);
  });

  selectRunner(selected, { scroll: ids.includes(requested) });
})();
