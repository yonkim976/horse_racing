/* Race-scoped reading, comparison and replay. All personal state stays in this browser. */
(() => {
  "use strict";
  const root = document.querySelector("[data-race-workspace]");
  const node = document.getElementById("race-study-data");
  if (!root || !node) return;
  const siteHeader = document.querySelector(".site-header");
  if (siteHeader) {
    const measureHeader = () => root.style.setProperty("--ra-header-offset", siteHeader.getBoundingClientRect().height + "px");
    measureHeader();
    new ResizeObserver(measureHeader).observe(siteHeader);
  }
  let data;
  try { data = JSON.parse(node.textContent); } catch (_) { return; }
  if (!data.race || !Array.isArray(data.runners)) return;
  const runners = new Map(data.runners.map((r) => [Number(r.entry_id), r]));
  const key = "hr-race-study:v2:" + data.race.id;
  const escape = (value) => String(value ?? "—").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
  const shown = (value) => value == null || value === "" ? "—" : escape(value);
  const read = (name) => { try { return localStorage.getItem(name); } catch (_) { return null; } };
  const write = (name, value) => { try { localStorage.setItem(name, value); return true; } catch (_) { return false; } };
  const state = { selected: data.runners[0]?.entry_id, compare: [], sameDistance: false };
  try {
    const saved = JSON.parse(read(key) || "null");
    if (saved && typeof saved === "object") {
      if (runners.has(saved.selected)) state.selected = saved.selected;
      if (Array.isArray(saved.compare)) state.compare = [...new Set(saved.compare)].filter((id) => runners.has(id)).slice(0, 4);
      state.sameDistance = saved.sameDistance === true;
    }
  } catch (_) { /* A stale browser preference must not block records. */ }
  const hash = location.hash.match(/^#runner-(\d+)$/);
  if (hash && runners.has(Number(hash[1]))) state.selected = Number(hash[1]);
  root.classList.add("is-enhanced");
  const save = () => write(key, JSON.stringify(state));
  let toastTimer;
  function toast(message) {
    const el = root.querySelector("[data-analysis-toast]");
    el.textContent = message; el.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
  }
  function showTab(article, name) {
    if (!article) return;
    article.querySelectorAll("[data-record-tab]").forEach((b) => {
      const selected = b.dataset.recordTab === name;
      b.setAttribute("aria-selected", String(selected)); b.tabIndex = selected ? 0 : -1;
    });
    article.querySelectorAll("[data-record-pane]").forEach((pane) => { pane.hidden = pane.dataset.recordPane !== name; });
  }
  root.querySelectorAll("[data-dossier]").forEach((article) => {
    const runner = runners.get(Number(article.dataset.dossier));
    showTab(article, runner?.history_total ? "history" : "trials");
  });
  function selectRunner(id, tabName, emit = true, scroll = false) {
    const runner = runners.get(id);
    if (!runner) return;
    state.selected = id;
    root.querySelectorAll("[data-dossier]").forEach((article) => {
      article.classList.toggle("is-active", Number(article.dataset.dossier) === id);
    });
    root.querySelectorAll("[data-select-runner]").forEach((b) => {
      b.setAttribute("aria-pressed", String(Number(b.dataset.selectRunner) === id));
    });
    root.querySelectorAll("[data-field-entry]").forEach((row) => {
      row.classList.toggle("is-selected", Number(row.dataset.fieldEntry) === id);
    });
    if (tabName) showTab(root.querySelector('[data-dossier="' + id + '"]'), tabName);
    if (scroll) document.getElementById("runner-records").scrollIntoView({ behavior: "auto", block: "start" });
    save();
    if (emit) document.dispatchEvent(new CustomEvent("analysis:runner-select", { detail: { entryId: id, horseId: runner.horse_id } }));
  }
  root.addEventListener("click", (event) => {
    const select = event.target.closest("[data-select-runner]");
    if (select) {
      const fromOverview = Boolean(select.closest("[data-field-table], [data-comparison-panel]"));
      selectRunner(Number(select.dataset.selectRunner), select.dataset.openTab, true, fromOverview);
    }
    const tab = event.target.closest("[data-record-tab]");
    if (tab) showTab(tab.closest("[data-dossier]"), tab.dataset.recordTab);
  });
  root.addEventListener("keydown", (event) => {
    const tab = event.target.closest("[data-record-tab]");
    if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...tab.parentElement.querySelectorAll("[data-record-tab]")];
    let next = tabs.indexOf(tab) + (event.key === "ArrowRight" ? 1 : -1);
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    const target = tabs[(next + tabs.length) % tabs.length];
    showTab(target.closest("[data-dossier]"), target.dataset.recordTab); target.focus();
  });
  document.addEventListener("analysis:runner-select", (event) => {
    if (Number(event.detail?.entryId) === state.selected) return;
    // Keep the board under the pointer when the record panel above changes height.
    const board = document.getElementById("pace-workbench");
    const before = board.getBoundingClientRect().top;
    selectRunner(Number(event.detail?.entryId), null, false);
    const delta = board.getBoundingClientRect().top - before;
    if (delta) window.scrollBy({ top: delta, behavior: "instant" });
  });
  const sameDistance = root.querySelector("[data-same-distance]");
  sameDistance.checked = state.sameDistance;
  function filterHistory() {
    root.querySelectorAll("[data-dossier]").forEach((article) => {
      const rows = [...article.querySelectorAll("[data-history-distance]")];
      rows.forEach((row) => { row.hidden = state.sameDistance && Number(row.dataset.historyDistance) !== data.race.distance; });
      const count = article.querySelector("[data-history-count]");
      if (count) count.textContent = state.sameDistance
        ? data.race.distance + "m 기록 " + rows.filter((row) => !row.hidden).length + "건 · 불러온 최근 기록 안에서 필터링됩니다. 과거 이력이 더 있으면 60경주 펼치기를 이용하세요."
        : "날짜를 펼치면 코너 통과순위·기록과 출전 간격을 확인할 수 있습니다. 거리·주로 조건이 다른 총기록을 그대로 비교하지 마세요.";
    });
  }
  sameDistance.addEventListener("change", () => { state.sameDistance = sameDistance.checked; filterHistory(); renderComparison(); save(); });
  function miniHistory(runner) {
    const rows = (runner.history || []).filter((r) => !state.sameDistance || r.distance === data.race.distance).slice(0, 5);
    if (!rows.length) return '<p>해당 조건의 경주 이력이 없습니다.</p>';
    return rows.map((r) => '<div class="ra-mini-history"><span>' + escape(r.date.slice(2)) + ' · ' + escape(r.distance) + 'm</span><strong>' + escape(r.finish) + '</strong><span>' + escape(r.time) + '</span><small>초반 ' + shown(r.section_details?.S1F?.time) + ' · 종반 200m ' + shown(r.section_details?.G1F?.time) + (r.early_position ? ' · 초반 ' + Number(r.early_position) + '위' : '') + '</small></div>').join("");
  }
  function renderComparison() {
    const panel = root.querySelector("[data-comparison-panel]");
    const list = state.compare.map((id) => runners.get(id)).filter(Boolean);
    panel.hidden = !list.length;
    root.querySelector("[data-comparison-count]").textContent = list.length + "두";
    const content = root.querySelector("[data-comparison-content]");
    content.style.setProperty("--compare-count", Math.max(2, list.length));
    content.innerHTML = list.map((r) => {
      const t = r.trials?.[0]; const training = r.training_summary || {};
      return '<article class="ra-compare-card"><header><span class="ra-stone" data-number="' + Number(r.number) + '">' + Number(r.number) + '</span><div><h3>' + escape(r.horse) + '</h3><p>' + escape(r.style) + ' · ' + escape(r.jockey) + '</p></div></header>' +
        '<dl><dt>부담중량</dt><dd>' + escape(r.weight) + '</dd><dt>직전 출전 간격</dt><dd>' + (r.metrics?.last_start_days == null ? "—" : Number(r.metrics.last_start_days) + "일") +
        '</dd><dt>동일거리 출전</dt><dd>' + Number(r.same_distance_starts) + '전</dd><dt>동일거리 최고</dt><dd>' + shown(r.metrics?.same_distance_best) +
        '</dd><dt>최근 28일 조교</dt><dd>' + Number(training.sessions || 0) + '회 · ' + shown(training.minutes) + '분</dd><dt>기수와 정상완주 (365일)</dt><dd>' + Number(r.combination_stats?.starts || 0) + '전</dd></dl>' +
        '<h4>최근 경주 · 최신순' + (state.sameDistance ? ' / ' + data.race.distance + 'm' : '') + '</h4>' + miniHistory(r) +
        '<h4>최근 주행심사</h4>' + (t ? '<p>' + escape(t.date) + ' · ' + escape(t.distance) + 'm · ' + escape(t.judgement) + '</p><div class="ra-mini-history"><span>' + escape(t.finish) + '</span><strong>' + escape(t.time) + '</strong>' + replayLink(t.video_url, r.horse + ' · ' + t.date + ' 주행심사' + (t.horse_number ? ' · 당시 ' + t.horse_number + '번' : '')) + '</div><p>S1F ' + shown(t.section_details?.S1F?.time_ms ? t.section_details.S1F.time : t.section_details?.S1F?.display) + ' · G1F ' + shown(t.section_details?.G1F?.time_ms ? t.section_details.G1F.time : t.section_details?.G1F?.display) + '</p>' : '<p>연결된 자료 없음</p>') +
        '<button type="button" class="ra-button" data-select-runner="' + r.entry_id + '">상세 기록 열기</button></article>';
    }).join("");
    root.querySelectorAll("[data-compare-entry]").forEach((b) => { b.checked = state.compare.includes(Number(b.dataset.compareEntry)); });
  }
  root.querySelectorAll("[data-compare-entry]").forEach((box) => box.addEventListener("change", () => {
    const id = Number(box.dataset.compareEntry);
    if (box.checked && state.compare.length >= 4) { box.checked = false; toast("최대 4두까지 나란히 비교할 수 있습니다."); return; }
    state.compare = box.checked ? [...new Set([...state.compare, id])] : state.compare.filter((value) => value !== id);
    renderComparison(); save();
  }));
  root.querySelectorAll("[data-clear-comparison]").forEach((button) => button.addEventListener("click", () => { state.compare = []; renderComparison(); save(); }));
  const search = root.querySelector("[data-runner-search]");
  search.addEventListener("input", () => {
    const query = search.value.trim().toLocaleLowerCase();
    let count = 0;
    root.querySelectorAll("[data-field-entry]").forEach((row) => {
      row.hidden = !row.dataset.runnerName.toLocaleLowerCase().includes(query);
      if (!row.hidden) count += 1;
    });
    root.querySelector("[data-field-status]").textContent = query ? count + "두 검색됨 · 비교 선택은 유지됩니다." : "각질은 수집된 과거 초반 통과순위에 따른 추정입니다. 기록이 없는 항목은 ‘—’로 표시합니다.";
  });
  const sortDirections = {};
  root.querySelectorAll("[data-sort]").forEach((button) => button.addEventListener("click", () => {
    const field = button.dataset.sort; sortDirections[field] = !(sortDirections[field] ?? (field === "rating"));
    const direction = sortDirections[field] ? 1 : -1;
    const tbody = root.querySelector("[data-field-table] tbody");
    const rows = [...tbody.rows].sort((a, b) => {
      const av = Number.parseFloat(a.dataset[field]), bv = Number.parseFloat(b.dataset[field]);
      if (!Number.isFinite(av)) return Number.isFinite(bv) ? 1 : 0;
      if (!Number.isFinite(bv)) return -1;
      return (av - bv) * direction;
    });
    rows.forEach((row) => tbody.appendChild(row));
    button.closest("thead").querySelectorAll("th").forEach((th) => th.removeAttribute("aria-sort"));
    button.closest("th").setAttribute("aria-sort", direction === 1 ? "ascending" : "descending");
  }));
  function allowedVideo(value) {
    try { const u = new URL(value); return u.origin === "https://kraplayer.starplayer.net" && u.pathname === "/kra/vod/starplayer.php" ? u.href : null; } catch (_) { return null; }
  }
  function replayLink(url, title) {
    const safe = allowedVideo(url);
    return safe ? '<a class="ra-video-link" href="' + escape(safe) + '" target="_blank" rel="noopener noreferrer" data-analysis-video data-video-title="' + escape(title) + '">▶ 영상</a>' : '<span>—</span>';
  }
  const dock = root.querySelector("[data-video-dock]");
  let lastVideoTrigger;
  root.addEventListener("click", (event) => {
    const link = event.target.closest("[data-analysis-video]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const url = allowedVideo(link.href);
    if (!url) return;
    event.preventDefault(); lastVideoTrigger = link;
    const popup = window.open(url, "horse-race-analysis-video", "popup,width=1260,height=760,resizable=yes,scrollbars=yes");
    if (popup) { popup.opener = null; popup.focus(); return; }
    root.querySelector("[data-video-heading]").textContent = link.dataset.videoTitle || "공식 경주 영상";
    root.querySelector("[data-video-popup]").href = url;
    dock.hidden = false;
    root.querySelector("[data-close-video]").focus({ preventScroll: true });
  });
  function closeVideo() {
    dock.hidden = true;
    if (lastVideoTrigger?.isConnected) lastVideoTrigger.focus({ preventScroll: true });
  }
  root.querySelector("[data-close-video]").addEventListener("click", closeVideo);
  root.querySelector("[data-video-popup]").addEventListener("click", (event) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const url = allowedVideo(event.currentTarget.href); if (!url) return;
    const popup = window.open(url, "horse-race-analysis-video", "popup,width=1260,height=760,resizable=yes,scrollbars=yes");
    if (popup) { popup.opener = null; event.preventDefault(); }
  });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !dock.hidden) closeVideo(); });
  function trainingHtml(r) {
    const rows = r.training || [], starts = r.start_training || [];
    const main = rows.length ? '<div class="ra-table-scroll"><table><thead><tr><th>일자</th><th>조교시간</th><th>구보</th><th>습보</th><th>기승자 구분</th></tr></thead><tbody>' +
      rows.map((t) => '<tr><td>' + shown(t.date) + '</td><td>' + shown(t.duration_minutes) + '분</td><td>' + shown(t.canter_count) + '</td><td>' + shown(t.gallop_count) + '</td><td>' + shown(t.rider_type) + '</td></tr>').join("") + '</tbody></table></div>' :
      '<div class="ra-empty"><strong>최근 28일에 수집된 조교 기록이 없습니다.</strong><span>미수집 상태와 실제 조교 미실시는 구분할 수 없습니다.</span></div>';
    const start = starts.length ? '<div class="ra-panel-heading"><h2>출발조교</h2></div><div class="ra-table-scroll"><table><thead><tr><th>일자</th><th>기승자</th><th>비고</th></tr></thead><tbody>' +
      starts.map((t) => '<tr><td>' + shown(t.date) + '</td><td>' + shown(t.rider) + '</td><td>' + shown(t.remark) + '</td></tr>').join("") + '</tbody></table></div>' : '';
    return main + start;
  }
  const rate = (value) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) + "%" : "—";
  function statRow(label, value) {
    const width = typeof value === "number" && Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0;
    return '<div class="ra-stat-row"><span>' + label + '</span><div class="ra-stat-bar"><i style="width:' + width + '%"></i></div><strong>' + rate(value) + '</strong></div>';
  }
  data.runners.forEach((r) => {
    const training = root.querySelector('[data-training-content="' + r.entry_id + '"]');
    if (training) training.innerHTML = trainingHtml(r);
    const jockey = root.querySelector('[data-jockey-content="' + r.entry_id + '"]');
    if (jockey) {
      const j = r.jockey_stats || {}, c = r.combination_stats || {};
      jockey.innerHTML = '<div class="ra-jockey-grid"><section><h4>' + escape(r.jockey) + '</h4><p>대상 경주일 이전 365일 · 정상완주 ' + Number(j.starts || 0) + '전</p><p>우승 ' + Number(j.wins || 0) + '회 · 3위 이내 ' + Number(j.top3 || 0) + '회</p>' + statRow("우승률", j.win_rate) + statRow("3위 이내", j.top3_rate) + '</section>' +
        '<section><h4>' + escape(r.horse) + ' × ' + escape(r.jockey) + '</h4><p>같은 말·기수 조합 · 이전 365일 정상완주 ' + Number(c.starts || 0) + '전</p><p>우승 ' + Number(c.wins || 0) + '회 · 3위 이내 ' + Number(c.top3 || 0) + '회</p>' + statRow("우승률", c.win_rate) + statRow("3위 이내", c.top3_rate) + '</section></div><p class="ra-footnote">수집된 정상 완주만 집계하며 중지·실격 등은 제외합니다. 표본 수와 거리·등급 구성을 함께 확인하세요. 조합 이력이 없으면 비율을 추정해 채우지 않습니다.</p>';
    }
  });
  const memo = root.querySelector("[data-race-memo]");
  const memoState = root.querySelector("[data-race-memo-state]");
  const memoKey = "hr-race-study:note:" + data.race.id;
  memo.value = read(memoKey) || "";
  memo.addEventListener("input", () => {
    memoState.textContent = write(memoKey, memo.value) ? "이 브라우저에 저장됨" : "브라우저 저장 불가 · 내용을 복사해 보관하세요";
  });
  selectRunner(state.selected, null, false);
  filterHistory(); renderComparison();
})();
