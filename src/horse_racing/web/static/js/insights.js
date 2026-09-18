(() => {
  const COLORS = ["#34d399", "#fbbf24", "#7dd3fc", "#f87171", "#c4b5fd", "#fb7185", "#bef264", "#fdba74"];
  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[char]);

  function initPace() {
    const root = document.querySelector("[data-pace-root]");
    if (!root) return;
    const dataNode = root.querySelector("[data-pace-data]");
    let runners = [];
    try { runners = JSON.parse(dataNode?.textContent || "[]"); } catch (_) { return; }
    const track = root.querySelector("[data-pace-track]");
    const list = root.querySelector("[data-pace-list]");
    const label = root.querySelector("[data-pace-label]");
    const slider = root.querySelector("[data-pace-stage]");
    const scenario = root.querySelector("[data-pace-scenario]");
    const play = root.querySelector("[data-pace-play]");
    const labels = ["출발", "초반", "중반", "종반"];
    let selected = null;
    let timer = null;
    const active = runners.filter((item) => !item.scratched);

    const estimatedRank = (runner, stage, flow) => {
      const fallback = active.findIndex((item) => item.id === runner.id) + 1;
      const early = runner.early || fallback;
      const styleShift = runner.style === "선행" ? -1 : runner.style === "추입" ? 1 : 0;
      const flowShift = flow === "fast" ? -styleShift : flow === "slow" ? styleShift : 0;
      if (stage === 0) return fallback;
      if (stage === 1) return early;
      if (stage === 2) return (early + fallback) / 2 + flowShift * .4;
      const closing = runner.closing ? (runner.closing - 15) / 1.6 : 0;
      return early + styleShift * -1.2 + flowShift - closing;
    };
    const render = () => {
      const stage = Number(slider.value);
      const flow = scenario.value;
      label.textContent = `${labels[stage]} · ${scenario.options[scenario.selectedIndex].text}`;
      const ranked = [...active].sort((a, b) => estimatedRank(a, stage, flow) - estimatedRank(b, stage, flow));
      const width = 760, height = 350, cx = 380, cy = 175, rx = 270, ry = 112;
      const baseAngle = [Math.PI, Math.PI * 1.42, Math.PI * 1.88, Math.PI * 2.58][stage];
      const marks = ranked.map((runner, index) => {
        const lane = index % 3;
        const angle = baseAngle - index * .018;
        const x = cx + Math.cos(angle) * (rx - lane * 14);
        const y = cy + Math.sin(angle) * (ry - lane * 8);
        const color = COLORS[runners.findIndex((item) => item.id === runner.id) % COLORS.length];
        const dim = selected && selected !== runner.id ? " is-dimmed" : "";
        return `<g class="pace-marker${dim}" data-pace-id="${runner.id}" transform="translate(${x.toFixed(1)} ${y.toFixed(1)})"><circle r="15" fill="${color}"></circle><text y="1">${runner.number}</text></g>`;
      }).join("");
      track.innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true"><ellipse class="track-line" cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}"></ellipse><ellipse class="track-edge" cx="${cx}" cy="${cy}" rx="${rx + 32}" ry="${ry + 32}"></ellipse><ellipse class="track-edge" cx="${cx}" cy="${cy}" rx="${rx - 32}" ry="${ry - 32}"></ellipse><path class="track-edge" d="M105 175H655" stroke-dasharray="5 8"></path>${marks}</svg>`;
      list.innerHTML = ranked.map((runner, index) => `<button type="button" data-pace-id="${runner.id}" class="${selected === runner.id ? "active" : ""}"><span><i class="pace-dot" style="display:inline-block;background:${COLORS[runners.findIndex((item) => item.id === runner.id) % COLORS.length]}"></i>${runner.number} ${escapeHtml(runner.name)}</span><small>추정 ${index + 1}위 · ${escapeHtml(runner.style)}</small></button>`).join("");
      root.querySelectorAll("[data-pace-id]").forEach((node) => node.addEventListener("click", () => { selected = selected === Number(node.dataset.paceId) ? null : Number(node.dataset.paceId); render(); syncRunnerRows(selected); }));
    };
    const syncRunnerRows = (id) => document.querySelectorAll("[data-entry-id]").forEach((row) => { const match = id === Number(row.dataset.entryId); row.classList.toggle("is-highlighted", match); row.classList.toggle("is-dimmed", Boolean(id) && !match); });
    slider.addEventListener("input", render);
    scenario.addEventListener("change", render);
    play.addEventListener("click", () => { if (timer) { clearInterval(timer); timer = null; play.textContent = "▶"; return; } play.textContent = "Ⅱ"; timer = setInterval(() => { slider.value = String((Number(slider.value) + 1) % 4); render(); }, 900); });
    document.querySelectorAll("[data-highlight]").forEach((button) => button.addEventListener("click", () => { selected = selected === Number(button.dataset.highlight) ? null : Number(button.dataset.highlight); render(); syncRunnerRows(selected); }));
    render();
  }

  function initAnalysis() {
    const dataNode = document.querySelector("[data-analysis-data]");
    if (!dataNode) return;
    let horses = [];
    try { horses = JSON.parse(dataNode.textContent || "[]"); } catch (_) { return; }
    let selected = null;
    const colorFor = (id) => COLORS[horses.findIndex((horse) => horse.horse_id === id) % COLORS.length];
    const sync = (id) => {
      selected = selected === id ? null : id;
      document.querySelectorAll("[data-horse-id]").forEach((node) => { const match = Number(node.dataset.horseId) === selected; node.classList.toggle("active", match); node.classList.toggle("is-highlighted", match); node.classList.toggle("is-dimmed", Boolean(selected) && !match); });
      document.querySelectorAll(".chart-series").forEach((node) => node.classList.toggle("is-dimmed", Boolean(selected) && Number(node.dataset.horseId) !== selected));
    };
    document.querySelectorAll(".horse-stat, [data-analysis-highlight]").forEach((node) => node.addEventListener("click", () => sync(Number(node.dataset.horseId || node.dataset.analysisHighlight))));

    const formChart = document.querySelector("[data-form-chart]");
    if (formChart) {
      const width = 660, height = 270, pad = 38;
      const maxPoints = Math.max(...horses.map((horse) => horse.trend.length), 2);
      let body = "";
      for (let rank = 1; rank <= 12; rank += 2) { const y = pad + (rank - 1) / 11 * (height - pad * 2); body += `<line class="chart-grid" x1="${pad}" y1="${y}" x2="${width-pad}" y2="${y}"></line><text class="chart-label" x="8" y="${y+4}">${rank}위</text>`; }
      horses.forEach((horse) => { const points = horse.trend.map((row, index) => ({ x: pad + index / (maxPoints - 1) * (width - pad * 2), y: pad + (Math.min(row.finish, 12) - 1) / 11 * (height - pad * 2), row })); const path = points.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" "); body += `<g class="chart-series" data-horse-id="${horse.horse_id}"><path class="chart-line" d="${path}" stroke="${colorFor(horse.horse_id)}"></path>${points.map((p) => `<circle class="chart-point" cx="${p.x}" cy="${p.y}" r="5" fill="${colorFor(horse.horse_id)}"><title>${escapeHtml(horse.name)} ${p.row.date} ${p.row.finish}위</title></circle>`).join("")}</g>`; });
      formChart.innerHTML = `<svg viewBox="0 0 ${width} ${height}">${body}</svg>`;
    }
    const distanceChart = document.querySelector("[data-distance-chart]");
    if (distanceChart) {
      const groups = horses.flatMap((horse) => horse.distances.map((row) => ({...row, horse_id: horse.horse_id, name: horse.name}))).sort((a, b) => a.distance - b.distance || a.name.localeCompare(b.name));
      const width = 660, rowH = 24, height = Math.max(270, groups.length * rowH + 35);
      const body = groups.map((row, index) => { const y = 20 + index * rowH; const bar = row.rate * 390; return `<g class="chart-series" data-horse-id="${row.horse_id}"><text class="chart-label" x="5" y="${y+12}">${escapeHtml(row.name)} ${row.distance}m</text><rect x="160" y="${y}" width="${bar}" height="15" rx="4" fill="${colorFor(row.horse_id)}"></rect><text class="chart-label" x="${165+bar}" y="${y+12}">${Math.round(row.rate*100)}% · n=${row.starts}</text></g>`; }).join("");
      distanceChart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" style="height:${height}px">${body}</svg>`;
    }
    const sectionChart = document.querySelector("[data-section-chart]");
    if (sectionChart) {
      const width = 760, height = 200, left = 160, barWidth = 490;
      let body = `<text class="chart-label" x="${left}" y="18">빠름</text><text class="chart-label" x="${left + barWidth - 25}" y="18">느림</text>`;
      horses.forEach((horse, index) => {
        const y = 38 + index * 30;
        const early = horse.early_position == null ? null : left + Math.min(horse.early_position / 12, 1) * barWidth;
        const closing = horse.closing_time == null ? null : left + Math.max(0, Math.min((horse.closing_time - 14) / 6, 1)) * barWidth;
        body += `<g class="chart-series" data-horse-id="${horse.horse_id}"><text class="chart-label" x="5" y="${y + 4}">${escapeHtml(horse.name)} · n=${horse.section_sample}</text><line class="chart-grid" x1="${left}" y1="${y}" x2="${left + barWidth}" y2="${y}"></line>${early == null ? "" : `<circle cx="${early}" cy="${y - 5}" r="6" fill="${colorFor(horse.horse_id)}"><title>초반 평균 ${horse.early_position}위</title></circle>`}${closing == null ? "" : `<rect x="${closing - 5}" y="${y + 4}" width="10" height="10" rx="2" fill="${colorFor(horse.horse_id)}"><title>G1F 평균 ${horse.closing_time}초</title></rect>`}</g>`;
      });
      sectionChart.innerHTML = `<svg viewBox="0 0 ${width} ${height}">${body}</svg>`;
    }
    document.querySelectorAll("[data-column-toggle]").forEach((input) => input.addEventListener("change", () => { const index = Number(input.dataset.columnToggle) + 1; document.querySelectorAll(`[data-analysis-table] tr > :nth-child(${index})`).forEach((cell) => { cell.hidden = !input.checked; }); }));

    const memo = document.querySelector("[data-analysis-memo]");
    const memoKey = `hr-analysis-memo:${location.search || "default"}`;
    if (memo) { try { memo.value = localStorage.getItem(memoKey) || ""; } catch (_) {} let saveTimer; memo.addEventListener("input", () => { clearTimeout(saveTimer); saveTimer = setTimeout(() => { try { localStorage.setItem(memoKey, memo.value); document.querySelector("[data-memo-state]").textContent = "저장됨"; } catch (_) { document.querySelector("[data-memo-state]").textContent = "저장 실패"; } }, 250); }); }
    const form = document.querySelector("[data-analysis-form]");
    document.querySelector("[data-preset-save]")?.addEventListener("click", () => { try { localStorage.setItem("hr-analysis-preset", new URLSearchParams(new FormData(form)).toString()); alert("현재 분석 조건을 이 브라우저에 저장했습니다."); } catch (_) { alert("브라우저 저장소를 사용할 수 없습니다."); } });
    document.querySelector("[data-preset-load]")?.addEventListener("click", () => { try { const value = localStorage.getItem("hr-analysis-preset"); if (value) location.href = `/analysis?${value}`; else alert("저장된 조건이 없습니다."); } catch (_) { alert("저장된 조건을 불러올 수 없습니다."); } });
  }

  initPace();
  initAnalysis();
})();
