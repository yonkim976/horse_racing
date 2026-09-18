/* A private, editable concept board. No invented race simulation or result prediction. */
(() => {
  "use strict";
  const root = document.querySelector("[data-analysis-pace]");
  const dataNode = document.getElementById("analysis-pace-data");
  if (!root || !dataNode) return;

  const STAGES = ["early", "middle", "late"];
  const STAGE_LABELS = { early: "초반 직선", middle: "중반 코너", late: "종반 직선" };
  const COLORS = ["#f6f3e8", "#263b33", "#b94c47", "#3b71ac", "#dfbd4f", "#557d56", "#bd8561", "#9b739b", "#4d8991", "#aa687f", "#717e45", "#6c79a4"];
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const find = (selector) => root.querySelector(selector);
  const board = find(".analysis-pace-board");
  const stonesHost = find("[data-ap-stones]");
  const rosterHost = find("[data-ap-roster]");
  const saveStatus = find("[data-ap-save-state]");
  const selectionStatus = find("[data-ap-selection]");
  const error = find("[data-ap-error]");
  const tabs = Array.from(root.querySelectorAll("[data-ap-stage]"));
  let payload;
  try { payload = JSON.parse(dataNode.textContent); } catch (_) { /* See the visible error below. */ }
  if (!payload || !payload.race || !Number.isSafeInteger(payload.race.id) || !Array.isArray(payload.runners)) {
    error.textContent = "전개도 자료를 불러오지 못했습니다. 출전마 기록은 아래에서 확인해 주세요.";
    error.hidden = false;
    return;
  }
  const race = payload.race;
  function parseEvidence(value, defaultLabel) {
    return {
      normalized: value && finite(value.normalized) && value.normalized >= 0 && value.normalized <= 1 ? value.normalized : null,
      samples: value && Number.isSafeInteger(value.samples) ? Math.max(0, value.samples) : 0,
      label: String(value && value.label || defaultLabel).slice(0, 80),
    };
  }
  const seen = new Set();
  const runners = payload.runners.filter((runner) => {
    if (!runner || runner.scratched || !Number.isSafeInteger(runner.entry_id) || !Number.isSafeInteger(runner.number) || runner.number < 1 || seen.has(runner.entry_id)) return false;
    seen.add(runner.entry_id);
    return true;
  }).slice(0, 24).map((runner) => ({
    id: runner.entry_id,
    horseId: runner.horse_id,
    number: runner.number,
    name: String(runner.name || runner.horse || "이름 미상").slice(0, 80),
    style: String(runner.style || "각질 미분류").slice(0, 40),
    sample: Number.isSafeInteger(runner.early_sample) ? Math.max(0, runner.early_sample) : 0,
    early: finite(runner.early_normalized) && runner.early_normalized >= 0 && runner.early_normalized <= 1 ? runner.early_normalized : null,
    stages: Object.fromEntries(STAGES.map((stage) => [stage, parseEvidence(runner.stages && runner.stages[stage], STAGE_LABELS[stage])])),
  })).sort((a, b) => a.number - b.number);
  function stageEvidence(runner, stage) {
    const evidence = runner.stages[stage];
    if (evidence.normalized !== null && evidence.samples > 0) return { ...evidence, fallback: false };
    const early = runner.stages.early.normalized !== null && runner.stages.early.samples > 0 ? runner.stages.early : { normalized: runner.early, samples: runner.sample, label: "S1F 초반" };
    if (early.normalized !== null && early.samples > 0) return { ...early, fallback: stage !== "early" };
    return { normalized: null, samples: 0, label: evidence.label, fallback: false };
  }
  const hasEvidence = (runner, stage) => stageEvidence(runner, stage).normalized !== null;
  const runnerById = new Map(runners.map((runner) => [runner.id, runner]));
  const fingerprint = runners.map((runner) => runner.id).join(",");
  const storageKey = `horse-racing:analysis-pace:v2:${race.id}`;
  const legacyStorageKey = `horse-racing:analysis-pace:v1:${race.id}`;
  const meet = String(race.meet || ({ 1: "서울", 2: "제주", 3: "부경", 4: "영천" })[race.meet_code] || "경주");
  const clockDirection = race.meet_code === 2 ? 1 : -1;
  const directionLabel = race.meet_code === 2 ? "제주 · 시계 방향 ↻" : [1, 3].includes(race.meet_code) ? `${meet} · 반시계 방향 ↺` : "진행 방향은 개념 표시";
  find("[data-ap-context]").textContent = `${meet} ${race.number || ""}R · ${Number(race.distance || 0).toLocaleString("ko-KR")}m`;
  find("[data-ap-direction]").textContent = directionLabel;
  find("[data-ap-cutoff]").textContent = payload.cutoff_label ? String(payload.cutoff_label) : "출전취소마는 배치 대상에서 제외합니다.";
  selectionStatus.setAttribute("role", "status");
  selectionStatus.setAttribute("aria-live", "polite");
  find("[data-ap-empty]").hidden = runners.length !== 0;
  const nodes = new Map();
  let selected = null;
  let undoState = null;
  let drag = null;
  let storageAvailable = true;
  let state = { version: 2, raceId: race.id, fingerprint, stage: "early", manual: false, editedStages: { early: false, middle: false, late: false }, positions: {} };

  // The grid prevents overlapping default stones. It represents relative order,
  // not an inferred gate, lane, physical distance, speed or finishing position.
  function defaultPositions(stage) {
    const width = Math.max(board.clientWidth, 320);
    const columns = clamp(Math.floor((width - 55) / 62), 4, 10);
    const cells = [];
    for (let column = 0; column < columns; column += 1) {
      for (let row = 0; row < 4; row += 1) cells.push({ x: .09 + column / (columns - 1) * .82, y: .18 + row * .14 });
    }
    const result = {};
    runners.filter((runner) => hasEvidence(runner, stage)).sort((a, b) => stageEvidence(a, stage).normalized - stageEvidence(b, stage).normalized || a.number - b.number).forEach((runner) => {
      const styleBias = stage === "early" ? /선행/.test(runner.style) ? .025 : /추입/.test(runner.style) ? -.025 : 0 : 0;
      const preferred = .9 - .8 * stageEvidence(runner, stage).normalized + styleBias;
      let best = 0;
      let score = Infinity;
      cells.forEach((cell, index) => {
        const candidate = Math.abs(cell.x - preferred) * 3 + Math.abs(cell.y - .39) * .22;
        if (candidate < score) { best = index; score = candidate; }
      });
      const cell = cells.splice(best, 1)[0] || { x: .5, y: .4 };
      result[runner.id] = { x: cell.x, y: cell.y, placed: true };
    });
    runners.filter((runner) => !hasEvidence(runner, stage)).forEach((runner) => { result[runner.id] = { x: .5, y: .4, placed: false }; });
    return result;
  }
  function resetPositions(empty = false) {
    STAGES.forEach((stage) => {
      state.positions[stage] = defaultPositions(stage);
      state.editedStages[stage] = empty;
      if (empty) runners.forEach((runner) => { state.positions[stage][runner.id].placed = false; });
    });
    state.manual = empty;
  }
  resetPositions();

  function readSaved() {
    let raw;
    try { raw = window.localStorage.getItem(storageKey) || window.localStorage.getItem(legacyStorageKey); } catch (_) { storageAvailable = false; return; }
    if (!raw) return;
    try {
      if (raw.length > 60000) return;
      const saved = JSON.parse(raw);
      if (!saved || ![1, 2].includes(saved.version) || saved.raceId !== race.id || saved.fingerprint !== fingerprint || !STAGES.includes(saved.stage)) return;
      const editedStages = Object.fromEntries(STAGES.map((stage) => [stage, saved.manual === true && (saved.editedStages ? saved.editedStages[stage] === true : true)]));
      const positions = clone(state.positions);
      for (const stage of STAGES) {
        // Rebuild automatic defaults from current section evidence. Preserve
        // every manually edited stage, including the legacy version-1 format.
        if (!editedStages[stage]) continue;
        if (!saved.positions || !saved.positions[stage]) return;
        positions[stage] = {};
        for (const runner of runners) {
          const position = saved.positions[stage][runner.id];
          if (!position || !finite(position.x) || !finite(position.y) || typeof position.placed !== "boolean") return;
          positions[stage][runner.id] = { x: clamp(position.x, .04, .96), y: clamp(position.y, .16, .62), placed: position.placed };
        }
      }
      const manual = Object.values(editedStages).some(Boolean);
      state = { version: 2, raceId: race.id, fingerprint, stage: saved.stage, manual, editedStages, positions };
      persist();
      saveStatus.textContent = manual ? "저장된 배치를 불러왔습니다" : "최신 구간 근거로 참고 배치를 갱신했습니다";
    } catch (_) { /* Corrupt or older private notes must not break the page. */ }
  }
  readSaved();

  function persist() {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(state));
      storageAvailable = true;
      saveStatus.textContent = "이 브라우저에 저장됨";
    } catch (_) {
      storageAvailable = false;
      saveStatus.textContent = "저장 공간을 사용할 수 없어 이번 화면에서만 유지됩니다";
    }
  }
  function remember() { undoState = clone(state); find("[data-ap-undo]").disabled = false; }
  function color(runner, node) {
    const index = ((runner.number - 1) % COLORS.length + COLORS.length) % COLORS.length;
    node.style.setProperty("--stone-color", COLORS[index]);
    node.style.setProperty("--stone-ink", index === 0 ? "#233c31" : index === 4 ? "#332d18" : "#ffffff");
  }
  function evidenceText(runner) {
    const evidence = stageEvidence(runner, state.stage);
    return evidence.normalized !== null ? `${runner.style} · ${evidence.fallback ? "초반 대체 · " : ""}${evidence.label} ${evidence.samples}회` : `${runner.style} · ${STAGE_LABELS[state.stage]} 근거 부족`;
  }
  function selectRunner(id, broadcast = true) {
    if (!runnerById.has(id)) return;
    selected = id;
    const runner = runnerById.get(id);
    const position = state.positions[state.stage][id];
    const evidence = stageEvidence(runner, state.stage);
    selectionStatus.textContent = `${runner.number}번 ${runner.name} · ${evidenceText(runner)}${evidence.normalized !== null ? ` · 정규화 통과 위치 ${Math.round(evidence.normalized * 100)}% (0%=선두)` : ""} · ${position.placed ? "방향키로 이동" : "Enter로 배치"}`;
    nodes.forEach((pair, key) => {
      pair.stone.classList.toggle("is-selected", key === id);
      pair.roster.classList.toggle("is-selected", key === id);
      pair.roster.setAttribute("aria-pressed", String(key === id));
    });
    if (broadcast) root.dispatchEvent(new CustomEvent("analysis:runner-select", { bubbles: true, detail: { entryId: runner.id, horseId: runner.horseId } }));
  }

  function geometry(waitingCount) {
    const width = Math.max(board.clientWidth, 320);
    const trackHeight = width <= 600 ? 360 : 340;
    const columns = Math.max(4, Math.floor((width - 24) / 62));
    const rows = Math.ceil(waitingCount / columns);
    const benchTop = trackHeight * .72;
    return { width, trackHeight, columns, benchTop, height: benchTop + (rows ? rows * 64 + 40 : 42) };
  }
  function waitingPosition(index, count, layout) {
    const countInRow = Math.min(layout.columns, count - Math.floor(index / layout.columns) * layout.columns);
    const row = Math.floor(index / layout.columns);
    return { x: (index % layout.columns + .5) / countInRow, top: layout.benchTop + 44 + row * 64 };
  }
  function setTrack() {
    const middle = state.stage === "middle";
    const curve = clockDirection > 0 ? 1 : -1;
    const path = (center) => middle ? `M 0 ${center - curve * 25} C 380 ${center - curve * 25} 620 ${center + curve * 25} 1000 ${center + curve * 25}` : `M 0 ${center} H 1000`;
    find("[data-ap-road]").setAttribute("d", path(143));
    find("[data-ap-rail-one]").setAttribute("d", path(80));
    find("[data-ap-rail-two]").setAttribute("d", path(206));
    find("[data-ap-lane]").setAttribute("d", path(143));
    board.setAttribute("aria-labelledby", `analysis-pace-tab-${state.stage}`);
    tabs.forEach((tab) => { const active = tab.dataset.apStage === state.stage; tab.setAttribute("aria-selected", String(active)); tab.tabIndex = active ? 0 : -1; });
    const fallbackCount = runners.filter((runner) => stageEvidence(runner, state.stage).fallback).length;
    find("[data-ap-mode]").textContent = state.editedStages[state.stage] ? `${STAGE_LABELS[state.stage]} · 직접 편집한 시나리오` : `${STAGE_LABELS[state.stage]} · 과거 구간 순위 기반 참고 배치${fallbackCount ? ` · 초반 대체 ${fallbackCount}두` : ""}`;
  }
  function render() {
    setTrack();
    const positions = state.positions[state.stage];
    const waiting = runners.filter((runner) => !positions[runner.id].placed);
    const layout = geometry(waiting.length);
    board.style.height = `${layout.height}px`;
    find(".analysis-pace-track").style.height = `${layout.trackHeight}px`;
    find(".analysis-pace-waiting-label").style.top = `${layout.benchTop}px`;
    find(".analysis-pace-waiting-label").textContent = waiting.length ? `배치 대기 · ${waiting.length}두` : "모든 말이 배치되었습니다";
    runners.forEach((runner) => {
      const pair = nodes.get(runner.id);
      const position = positions[runner.id];
      const display = position.placed ? { x: position.x, top: position.y * layout.trackHeight } : waitingPosition(waiting.findIndex((item) => item.id === runner.id), waiting.length, layout);
      pair.stone.style.left = `${display.x * 100}%`;
      pair.stone.style.top = `${display.top}px`;
      pair.stone.classList.toggle("is-waiting", !position.placed);
      pair.stone.setAttribute("aria-label", `${runner.number}번 ${runner.name}, ${STAGE_LABELS[state.stage]}, ${position.placed ? "배치됨" : "배치 대기"}, ${evidenceText(runner)}. 방향키로 이동, Delete로 대기.`);
      pair.roster.title = `${runner.name}: ${evidenceText(runner)}. 선택 후 전개도 마번을 움직일 수 있습니다.`;
      pair.detail.textContent = evidenceText(runner);
    });
    if (selected !== null) selectRunner(selected, false);
  }

  function pointFromEvent(event) {
    const rect = board.getBoundingClientRect();
    const margin = Math.max(.04, 25 / rect.width);
    const layout = geometry(0);
    return { x: clamp((event.clientX - rect.left) / rect.width, margin, 1 - margin), y: (event.clientY - rect.top) / layout.trackHeight };
  }
  function moveFromPointer(event) {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const point = pointFromEvent(event);
    const position = state.positions[state.stage][drag.id];
    position.x = point.x;
    position.y = clamp(point.y, .16, .62);
    position.placed = point.y < .72;
    state.manual = true;
    state.editedStages[state.stage] = true;
    drag.changed = true;
    render();
  }
  function finishPointer(event, cancelled = false) {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const active = drag;
    drag = null;
    nodes.get(active.id).stone.classList.remove("is-dragging");
    if (cancelled && undoState) { state = clone(undoState); render(); }
    if (active.changed && !cancelled) persist();
  }
  function onKey(event, runner) {
    const direction = ({ ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] })[event.key];
    if (!direction && !["Enter", "Delete", "Backspace"].includes(event.key)) return;
    event.preventDefault();
    remember();
    const position = state.positions[state.stage][runner.id];
    if (["Delete", "Backspace"].includes(event.key)) position.placed = false;
    else {
      position.placed = true;
      if (direction) {
        const step = event.shiftKey ? .07 : .018;
        const margin = Math.max(.04, 25 / Math.max(board.clientWidth, 320));
        position.x = clamp(position.x + direction[0] * step, margin, 1 - margin);
        position.y = clamp(position.y + direction[1] * step, .16, .62);
      }
    }
    state.manual = true;
    state.editedStages[state.stage] = true;
    selectRunner(runner.id);
    render();
    persist();
  }

  runners.forEach((runner) => {
    const stone = document.createElement("button");
    stone.type = "button";
    stone.className = "analysis-pace-stone";
    stone.dataset.apRunner = String(runner.id);
    stone.textContent = String(runner.number);
    color(runner, stone);
    const name = document.createElement("span");
    name.className = "analysis-pace-stone-name";
    name.textContent = runner.name;
    name.setAttribute("aria-hidden", "true");
    stone.append(name);
    stone.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !event.isPrimary) return;
      event.preventDefault();
      if (drag) return;
      remember();
      drag = { id: runner.id, pointerId: event.pointerId, changed: false };
      stone.setPointerCapture(event.pointerId);
      stone.focus({ preventScroll: true });
      stone.classList.add("is-dragging");
      selectRunner(runner.id);
    });
    stone.addEventListener("pointermove", moveFromPointer);
    stone.addEventListener("pointerup", (event) => finishPointer(event));
    stone.addEventListener("pointercancel", (event) => finishPointer(event, true));
    stone.addEventListener("lostpointercapture", (event) => finishPointer(event));
    stone.addEventListener("keydown", (event) => onKey(event, runner));
    stone.addEventListener("focus", () => selectRunner(runner.id));
    stone.addEventListener("click", () => selectRunner(runner.id));
    const roster = document.createElement("button");
    roster.type = "button";
    roster.className = "analysis-pace-runner";
    roster.setAttribute("aria-pressed", "false");
    color(runner, roster);
    const number = document.createElement("span");
    number.className = "analysis-pace-runner-number";
    number.textContent = String(runner.number);
    const copy = document.createElement("span");
    copy.className = "analysis-pace-runner-copy";
    const title = document.createElement("strong");
    title.textContent = runner.name;
    const detail = document.createElement("small");
    detail.textContent = evidenceText(runner);
    copy.append(title, detail);
    roster.append(number, copy);
    roster.addEventListener("click", () => { selectRunner(runner.id); stone.focus({ preventScroll: true }); });
    nodes.set(runner.id, { stone, roster, detail });
    stonesHost.append(stone);
    rosterHost.append(roster);
  });

  function switchStage(stage) {
    if (!STAGES.includes(stage)) return;
    state.stage = stage;
    render();
    persist();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => switchStage(tab.dataset.apStage));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? 2 : (index + (event.key === "ArrowRight" ? 1 : -1) + 3) % 3;
      switchStage(STAGES[next]);
      tabs[next].focus();
    });
  });
  find("[data-ap-restore]").addEventListener("click", () => {
    remember(); resetPositions(); render(); persist();
    selectionStatus.textContent = "세 구간을 해당 구간의 과거 통과순위 기반 참고 배치로 복원했습니다. 구간 근거가 부족한 말은 초반 기록을 대체 사용합니다.";
  });
  find("[data-ap-clear]").addEventListener("click", () => {
    remember(); resetPositions(true); render(); persist();
    selectionStatus.textContent = "세 구간의 말을 모두 대기 영역으로 옮겼습니다. 직접 끌어 배치하세요.";
  });
  find("[data-ap-undo]").addEventListener("click", () => {
    if (!undoState) return;
    state = clone(undoState); undoState = null; find("[data-ap-undo]").disabled = true;
    render(); persist(); selectionStatus.textContent = "직전 배치로 되돌렸습니다.";
  });
  document.addEventListener("analysis:runner-select", (event) => {
    const id = Number(event.detail && event.detail.entryId);
    if (runnerById.has(id) && selected !== id) selectRunner(id, false);
  });
  if (typeof ResizeObserver === "function") new ResizeObserver(() => render()).observe(board);
  else window.addEventListener("resize", render, { passive: true });
  if (!storageAvailable) saveStatus.textContent = "저장 공간을 사용할 수 없어 이번 화면에서만 유지됩니다";
  render();
})();
