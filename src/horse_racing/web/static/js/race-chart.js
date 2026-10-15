(() => {
  const root = document.querySelector("[data-section-chart]");
  const payload = document.getElementById("section-chart-data");
  if (!root || !(payload instanceof HTMLScriptElement) || !payload.textContent) return;
  let data;
  try { data = JSON.parse(payload.textContent); } catch { return; }
  if (!data.labels?.length || !data.series?.length) return;
  const checkpoints = root.querySelector("[data-passing-checkpoints]");
  const formation = root.querySelector("[data-passing-formation]");
  const legend = root.querySelector("[data-chart-legend]");
  const detail = root.querySelector("[data-passing-detail]");
  if (!checkpoints || !formation || !legend || !detail) return;
  const runners = new Map(data.series.map(item => [item.horseNumber, item]));
  const state = { index: 0, horse: null };
  // Keep the original checkpoint index for timings and rank changes when a point is hidden.
  const steps = data.labels.map((label, index) => ({ index, point: pointAt(index) }))
    .filter(({ point }) => !(point.label.split("/").includes("G3F") && point.mode !== "official"));
  if (!steps.length) return;
  const summary = document.querySelector("[data-passing-summary]");
  if (summary) summary.textContent = `${steps.length}개 전개 구간`;
  const maxPack = Math.max(4, ...steps.flatMap(({point}) => point.groups.map(group => group.horses.length)));
  const UNIT = 28; // One displayed length, shared by every checkpoint and finish.
  const MARKER = 46;
  let formationIndex = null;
  function element(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function pointAt(index) {
    return data.checkpoints?.[index] || {
      label: data.labels[index], mode: "rank", notation: "", groups: data.series
        .filter(item => item.positions[index] != null)
        .sort((a, b) => a.positions[index] - b.positions[index] || a.horseNumber - b.horseNumber)
        .map(item => ({ horses: [item.horseNumber], gap: ",", distanceLengths: null })),
    };
  }
  const displayLabel = point => point.label === "FIN" ? "결승" : point.label;
  function selectHorse(number) { state.horse = state.horse === number ? null : number; render(); }
  function horseBadge(number) {
    // Share the entry table's palette, including striped silks 11–14.
    return element("span", `silk-number silk-${number} passing-silk`, String(number));
  }
  function positionLabel(item, index) {
    const position = item.positions[index];
    return position == null ? "순위 미제공" : `${position}위${item.positionsInferred?.[index] ? " · 시간 기준" : ""}`;
  }
  function gapLabel(distance) {
    return `약 ${Number(distance.toFixed(2))}마신`;
  }
  function renderDetail(point, index) {
    detail.replaceChildren();
    const item = runners.get(state.horse);
    if (!item) {
      const leader = point.groups[0]?.horses.map(number => `${number}번`).join(" · ");
      detail.append(element("strong", "", leader ? `${point.mode === "official" ? "선두조" : "선두"} ${leader}` : "통과 데이터 없음"),
        element("span", "", "말을 선택하면 선두와의 추정 간격, 순위와 기록이 표시됩니다."));
      return;
    }
    detail.append(element("strong", "", `${item.horseNumber}. ${item.horseName}`));
    const bits = [positionLabel(item, index)];
    const group = point.groups.find(group => group.horses.includes(item.horseNumber));
    if (Number.isFinite(group?.distanceLengths)) bits.push(group.distanceLengths === 0 && point.mode !== "finish" ? "선두조" : `선두로부터 ${gapLabel(group.distanceLengths)}`);
    const previousIndex = steps[state.index - 1]?.index;
    const current = item.positions[index];
    const previous = item.positions[previousIndex];
    if (previousIndex != null && current != null && previous != null) {
      const delta = previous - current;
      bits.push(delta > 0 ? `이전 표시 구간보다 ${delta}계단 상승` : delta < 0 ? `이전 표시 구간보다 ${-delta}계단 하락` : "이전 표시 구간과 순위 동일");
    }
    if (point.mode === "finish" && item.finishMargin) bits.push(`앞선 말과 공식 착차 ${item.finishMargin}`);
    if (item.segmentTimes?.[index]) bits.push(`${(data.segmentLabels?.[index] || "구간").replaceAll("FIN", "결승")} ${item.segmentTimes[index]}`);
    if (item.cumulativeTimes?.[index]) bits.push(`누적 ${item.cumulativeTimes[index]}`);
    detail.append(element("span", "", bits.join(" · ")));
  }
  function renderFormation(point, index) {
    const distanceFromRight = formationIndex === index
      ? Math.max(0, formation.scrollWidth - formation.clientWidth - formation.scrollLeft) : 0;
    formation.replaceChildren();
    const track = element("div", "passing-track");
    if (point.mode === "official") {
      track.classList.add("has-inner-rail");
      track.append(element("div", "passing-infield", "펜스 안쪽"),
        element("div", "passing-inner-rail"), element("div", "passing-outer-label", "외측 ↓"));
    }
    const included = new Set();
    const laneEnds = [];
    let maxDistance = 0;
    let maxBottom = maxPack * 48 + 40;
    const unknown = element("div", "passing-unknown");
    point.groups.forEach(group => {
      const distance = group.distanceLengths;
      // Upstream margins are untrusted. Never let a malformed value size a
      // browser-wide track or drive an unbounded axis-building loop.
      const known = Number.isFinite(distance) && distance >= 0 && distance <= 1000;
      const pack = element("div", "passing-pack");
      pack.append(element("span", "passing-pack-label", known ? distance === 0 && point.mode !== "finish" ? "선두" : `≈${Number(distance.toFixed(2))}` : "미제공"));
      const members = element("div", "passing-pack-members");
      group.horses.forEach(number => {
        const item = runners.get(number);
        if (!item) return;
        included.add(number);
        const button = element("button", "passing-horse");
        button.type = "button";
        button.dataset.horse = String(number);
        button.classList.toggle("is-selected", state.horse === number);
        button.setAttribute("aria-pressed", String(state.horse === number));
        const label = `${number}번 ${item.horseName} · ${positionLabel(item, index)}${known ? ` · ${gapLabel(distance)}` : ""}`;
        button.setAttribute("aria-label", label);
        button.title = label;
        button.append(horseBadge(number));
        button.addEventListener("click", () => selectHorse(number));
        members.append(button);
      });
      pack.append(members);
      if (!known) { unknown.append(pack); return; }
      maxDistance = Math.max(maxDistance, distance);
      const x = distance * UNIT;
      // Only the inside-to-outside order within each pack is known, not exact lanes.
      let top = 40;
      if (point.mode === "finish") {
        let lane = laneEnds.findIndex(end => end + MARKER <= x);
        if (lane < 0) lane = laneEnds.length;
        laneEnds[lane] = x;
        top = 26 + lane * 70;
      }
      pack.style.right = `${18 + x}px`;
      pack.style.top = `${top}px`;
      pack.dataset.distanceLengths = String(distance);
      maxBottom = Math.max(maxBottom, top + 24 + group.horses.length * 48);
      track.append(pack);
    });
    const axisMax = Math.max(10, Math.ceil(maxDistance / 2) * 2);
    track.style.width = `${axisMax * UNIT + 84}px`;
    track.style.height = `${maxBottom + 38}px`;
    const axis = element("div", "passing-axis");
    const tickStep = Math.max(2, Math.ceil(axisMax / 100) * 2);
    for (let value = 0; value <= axisMax; value += tickStep) {
      const tick = element("span", "", String(value));
      tick.style.right = `${18 + value * UNIT}px`;
      axis.append(tick);
    }
    track.append(axis);
    formation.append(track);
    if (unknown.children.length) formation.append(unknown);
    if (!point.groups.length) formation.append(element("p", "passing-empty", "이 구간의 통과 데이터가 없습니다."));
    // Open each checkpoint at the leader; preserve the view when selecting a horse.
    formation.scrollLeft = Math.max(0, formation.scrollWidth - formation.clientWidth - distanceFromRight);
    formationIndex = index;
    return included;
  }
  function render() {
    // Measure the formation only after its tab is visible.
    if (!root.getClientRects().length) return;
    const {point, index} = steps[state.index];
    checkpoints.querySelectorAll("button").forEach((button, step) => {
      button.classList.toggle("is-active", step === state.index);
      button.setAttribute("aria-pressed", String(step === state.index));
    });
    root.querySelector("[data-passing-title]").textContent = `${displayLabel(point)} ${point.mode === "official" ? "통과조" : point.mode === "finish" ? "도착 간격" : "통과순위"}`;
    root.querySelector("[data-passing-location]").textContent = point.location || "";
    root.querySelector("[data-passing-source]").textContent = point.mode === "official" ? "기호 기준 추정" : point.mode === "finish" ? "공식 착차 기준" : "순위 기준";
    root.querySelector("[data-passing-count]").textContent = `${state.index + 1} / ${steps.length}`;
    root.querySelector("[data-passing-prev]").disabled = state.index === 0;
    root.querySelector("[data-passing-next]").disabled = state.index === steps.length - 1;
    const lanes = root.querySelector("[data-passing-lanes]");
    if (lanes) lanes.textContent = point.mode === "official"
      ? "위쪽 경계가 내측 펜스입니다. 각 조는 내측부터 정렬하며, 실제 펜스와의 거리를 뜻하지 않습니다."
      : point.mode === "finish" ? "결승의 세로 위치는 겹침 방지용이며, 내·외측을 뜻하지 않습니다."
        : "이 구간은 내·외측 정보가 제공되지 않습니다.";
    const mapTitle = root.querySelector("[data-passing-map-title]");
    if (mapTitle) mapTitle.textContent = `${displayLabel(point)} · ${point.location || "선택 구간"}`;
    let located = false;
    root.querySelectorAll("[data-passing-map-codes]").forEach(marker => {
      const active = marker.dataset.passingMapCodes.split("/").some(code => point.label.split("/").includes(code));
      marker.classList.toggle("is-current", active);
      if (active) located = true;
    });
    const mapStatus = root.querySelector("[data-passing-map-status]");
    if (mapStatus) mapStatus.textContent = located
      ? "강조한 점이 선택 구간의 개략 위치입니다. 지도는 실제 주로 방향을 따릅니다."
      : "이 구간의 지도상 위치는 확인되지 않아 강조하지 않습니다.";
    const included = renderFormation(point, index);
    const absent = data.series.filter(item => !included.has(item.horseNumber)).map(item => `${item.horseNumber}번`);
    root.querySelector("[data-passing-notation]").textContent = [
      point.notation ? `통과조 원문  ${point.notation}` : point.mode === "finish" ? "앞선 말과의 공식 착차를 착순대로 누적해 배치합니다. 기록이 같아도 착차가 있으면 가로 위치가 달라집니다." : "이 지점은 통과조 원문이 없어 순위만 표시합니다.",
      absent.length ? `통과 정보 없음: ${absent.join(" · ")}` : "",
    ].filter(Boolean).join(" · ");
    const estimate = root.querySelector("[data-passing-estimate]");
    if (estimate) estimate.textContent = point.mode === "finish"
      ? "가로축: 우승마로부터 누적 마신 · 코 0.05, 머리 0.15, 목 0.3마신은 그림을 위한 대표값이며, 대차는 최소 10마신으로 놓습니다. 세로 위치는 겹침을 피하기 위한 배치입니다."
      : "가로축: 선두조로부터 추정 마신 · ,는 1.5, -는 3.5, =는 7.5마신을 대표값으로, ≡는 최소 10마신으로 놓습니다. 같은 조 안의 1마신 미만 차이는 생략합니다.";
    legend.querySelectorAll("[data-horse]").forEach(button => {
      const selected = Number(button.dataset.horse) === state.horse;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    renderDetail(point, index);
  }
  steps.forEach(({point}, index) => {
    const button = element("button", "passing-checkpoint", displayLabel(point));
    button.type = "button";
    button.addEventListener("click", () => { state.index = index; render(); });
    checkpoints.append(button);
  });
  [...data.series].sort((a, b) => a.horseNumber - b.horseNumber).forEach(item => {
    const button = element("button", "chart-legend-item");
    button.type = "button";
    button.dataset.horse = String(item.horseNumber);
    button.append(horseBadge(item.horseNumber), element("span", "chart-legend-label", item.horseName));
    button.addEventListener("click", () => selectHorse(item.horseNumber));
    legend.append(button);
  });
  root.querySelector("[data-passing-prev]").addEventListener("click", () => { state.index = Math.max(0, state.index - 1); render(); });
  root.querySelector("[data-passing-next]").addEventListener("click", () => { state.index = Math.min(steps.length - 1, state.index + 1); render(); });
  root.closest("[data-race-detail-workspace]")?.addEventListener("race-detail-pane-shown", event => {
    if (event.detail === "sections") render();
  });
  render();
})();
