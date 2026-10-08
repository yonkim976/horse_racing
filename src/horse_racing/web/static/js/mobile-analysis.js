(() => {
  "use strict";
  const root = document.querySelector("[data-analysis-page]");
  if (!root) return;

  function revealActiveRoundChip() {
    const nav = root.querySelector(".ma-rounds");
    const chip = nav?.querySelector("a.active");
    if (!nav || !chip) {
      return;
    }
    const navBox = nav.getBoundingClientRect();
    const chipBox = chip.getBoundingClientRect();
    if (chipBox.left >= navBox.left + 8 && chipBox.right <= navBox.right - 8) {
      return;
    }
    const offset = chipBox.left - navBox.left - (navBox.width - chipBox.width) / 2;
    nav.scrollTo({
      left: Math.max(0, nav.scrollLeft + offset),
      behavior: "auto",
    });
  }

  revealActiveRoundChip();
  requestAnimationFrame(revealActiveRoundChip);
  window.addEventListener("pageshow", revealActiveRoundChip);

  const form = root.querySelector("[data-auto-submit]");
  if (form) {
    form.addEventListener("change", (event) => {
      if (event.target.matches("input[type=date]")) form.submit();
    });
  }

  const dossiers = [...root.querySelectorAll("[data-dossier]")];
  if (!dossiers.length) return;

  const recordStore = root.querySelector("[data-record-store]");
  const ids = dossiers.map((article) => Number(article.dataset.dossier));
  const params = new URLSearchParams(location.search);
  const hash = location.hash.match(/^#(?:entry|runner)-(\d+)$/);
  const requested = Number(params.get("entry") || (hash ? hash[1] : 0));
  let selected = ids.includes(requested) ? requested : ids[0];
  let expanded = null;
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
    node.textContent = `${row.number}번 ${row.horse} · 초반 ${row.early} · 코너 ${row.middle} · 종반 ${row.late}`;
  }

  function selectRunner(id) {
    if (!ids.includes(id)) return;
    selected = id;
    root.querySelectorAll("[data-select-runner]").forEach((button) => {
      if (!button.matches("[data-runner-card]")) {
        button.setAttribute("aria-pressed", String(Number(button.dataset.selectRunner) === id));
        button.classList.toggle("is-selected", Number(button.dataset.selectRunner) === id);
      }
    });
    updatePaceSummary(id);
  }

  function closeRunner(id) {
    const article = dossiers.find((row) => Number(row.dataset.dossier) === id);
    const card = root.querySelector(`[data-runner-card][data-select-runner="${id}"]`);
    if (article) {
      article.hidden = true;
      article.classList.remove("is-active");
      recordStore?.append(article);
    }
    card?.setAttribute("aria-expanded", "false");
    card?.classList.remove("is-selected");
    if (expanded === id) expanded = null;
  }

  function openRunner(id, { scroll = false } = {}) {
    if (!ids.includes(id)) return;
    dossiers.forEach((article) => {
      const articleId = Number(article.dataset.dossier);
      if (articleId !== id) closeRunner(articleId);
    });
    const article = dossiers.find((row) => Number(row.dataset.dossier) === id);
    const card = root.querySelector(`[data-runner-card][data-select-runner="${id}"]`);
    const shell = card?.closest("[data-runner-shell]");
    if (!article || !card || !shell) return;
    shell.append(article);
    article.hidden = false;
    article.classList.add("is-active");
    card.setAttribute("aria-expanded", "true");
    card.classList.add("is-selected");
    expanded = id;
    if (scroll) card.scrollIntoView({ behavior: "auto", block: "start" });
  }

  root.addEventListener("click", (event) => {
    const reason = event.target.closest("[data-open-reason]");
    if (reason) {
      openReason(Number(reason.dataset.openReason), reason);
      return;
    }
    const select = event.target.closest("[data-select-runner]");
    if (select) {
      const id = Number(select.dataset.selectRunner);
      selectRunner(id);
      if (select.matches("[data-runner-card]")) {
        if (expanded === id) closeRunner(id);
        else openRunner(id);
      }
      return;
    }
    const tab = event.target.closest("[data-record-tab]");
    if (tab) showTab(tab.closest("[data-dossier]"), tab.dataset.recordTab);
  });

  selectRunner(selected);
  if (ids.includes(requested)) openRunner(requested, { scroll: true });

  const reasonSheet = root.querySelector("[data-reason-sheet]");
  const reasonNode = document.getElementById("ma-reason-data");
  let reasons = {};
  try {
    reasons = JSON.parse(reasonNode?.textContent || "{}");
  } catch (error) {
    reasons = {};
  }

  let reasonTrigger = null;

  function openReason(id, trigger) {
    const item = reasons[String(id)];
    if (!reasonSheet || !item) return;
    reasonTrigger = trigger || null;
    const number = reasonSheet.querySelector("[data-reason-num]");
    const title = reasonSheet.querySelector("[data-reason-title]");
    const sub = reasonSheet.querySelector("[data-reason-sub]");
    const list = reasonSheet.querySelector("[data-reason-list]");
    if (number) {
      number.textContent = String(item.number);
      number.className = `ma-reason-num silk-${item.number}`;
    }
    if (title) title.textContent = item.horse || "왜 이 확률";
    if (sub) {
      const bits = [
        item.pct ? `3위 안 ${item.pct}` : "",
        item.role && item.role !== "예측없음" ? item.role : "",
      ].filter(Boolean);
      sub.textContent = bits.join(" · ");
    }
    if (list) {
      list.replaceChildren(...(item.lines || []).map((line) => {
        const row = document.createElement("li");
        row.textContent = line;
        return row;
      }));
    }
    reasonSheet.hidden = false;
    document.body.classList.add("reason-open");
    reasonSheet.querySelector(".ma-reason-close")?.focus();
  }

  function closeReason() {
    if (!reasonSheet || reasonSheet.hidden) return;
    reasonSheet.hidden = true;
    document.body.classList.remove("reason-open");
    reasonTrigger?.focus();
    reasonTrigger = null;
  }

  reasonSheet?.querySelectorAll("[data-reason-close]").forEach((button) => {
    button.addEventListener("click", closeReason);
  });
  document.addEventListener("keydown", (event) => {
    if (!reasonSheet || reasonSheet.hidden) return;
    if (event.key === "Escape") {
      closeReason();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...reasonSheet.querySelectorAll("button:not([tabindex='-1'])")];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
})();
