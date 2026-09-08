(() => {
  const root = document.querySelector("[data-section-chart]");
  const payload = document.getElementById("section-chart-data");
  if (!root || !(payload instanceof HTMLScriptElement) || !payload.textContent) {
    return;
  }

  /** @type {{labels: string[], series: Array<{horseId:number,horseNumber:number,horseName:string,finishSort:number,positions:(number|null)[],segmentTimes:string[],cumulativeTimes:string[]}>, maxPosition: number}} */
  const data = JSON.parse(payload.textContent);
  if (!data.labels?.length || !data.series?.length) {
    return;
  }

  const svg = root.querySelector("[data-chart-svg]");
  const frame = root.querySelector(".section-chart-frame");
  const legend = root.querySelector("[data-chart-legend]");
  const tooltip = root.querySelector("[data-chart-tooltip]");
  if (
    !(svg instanceof SVGElement)
    || !(frame instanceof HTMLElement)
    || !(legend instanceof HTMLElement)
  ) {
    return;
  }

  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // 마번(silk) 색상 — 다크 배경에서는 어두운 색을 밝은 톤으로 치환
  const COLORS_LIGHT = [
    "#7a8380", "#1a1a1a", "#c0392b", "#1f5fbf", "#d4a017", "#1f7a3a",
    "#d46aa0", "#6b7280", "#6d28d9", "#38bdf8", "#ea580c", "#7c4a1a",
    "#84cc16", "#1e3a8a", "#be123c", "#0f766e", "#a16207", "#334155",
  ];
  const COLORS_DARK = [
    "#e2e8f0", "#a1a1aa", "#f87171", "#60a5fa", "#facc15", "#4ade80",
    "#f9a8d4", "#94a3b8", "#a78bfa", "#38bdf8", "#fb923c", "#c08552",
    "#a3e635", "#818cf8", "#fb7185", "#2dd4bf", "#eab308", "#cbd5e1",
  ];

  function palette() {
    return document.documentElement.dataset.theme === "light" ? COLORS_LIGHT : COLORS_DARK;
  }

  const state = {
    pinned: new Set(
      data.series
        .filter((item) => item.finishSort > 0 && item.finishSort <= 5)
        .map((item) => item.horseNumber)
    ),
    hover: /** @type {number|null} */ (null),
    animated: false,
  };

  function colorFor(horseNumber) {
    const colors = palette();
    return colors[(horseNumber - 1) % colors.length];
  }

  function isActive(horseNumber) {
    if (state.hover != null) {
      return state.hover === horseNumber;
    }
    if (state.pinned.size === 0) {
      return true;
    }
    return state.pinned.has(horseNumber);
  }

  function applyActiveState() {
    svg.querySelectorAll(".chart-series").forEach((group) => {
      const horseNumber = Number(group.getAttribute("data-horse"));
      const active = isActive(horseNumber);
      group.classList.toggle("is-active", active);
      group.classList.toggle("is-muted", !active);
      const path = group.querySelector("path.chart-line");
      if (path) {
        path.setAttribute("stroke-width", active ? "2.8" : "1.4");
        path.setAttribute("opacity", active ? "1" : "0.15");
      }
      group.querySelectorAll("circle.chart-point").forEach((circle) => {
        circle.setAttribute("r", active ? "4.5" : "3");
        circle.setAttribute("opacity", active ? "1" : "0.16");
      });
      const label = group.querySelector(".chart-end-label");
      if (label) {
        label.setAttribute("opacity", active ? "1" : "0");
      }
    });

    legend.querySelectorAll(".chart-legend-item").forEach((button) => {
      const horseNumber = Number(button.getAttribute("data-horse"));
      button.classList.toggle("is-active", state.pinned.has(horseNumber));
      button.classList.toggle("is-dimmed", state.hover != null && state.hover !== horseNumber);
    });
  }

  function buildLegend() {
    legend.innerHTML = "";
    const sorted = [...data.series].sort(
      (a, b) => a.finishSort - b.finishSort || a.horseNumber - b.horseNumber
    );

    for (const item of sorted) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chart-legend-item";
      button.dataset.horse = String(item.horseNumber);
      button.innerHTML = `
        <span class="chart-swatch" data-swatch style="background:${colorFor(item.horseNumber)}"></span>
        <span class="chart-legend-label">${item.horseNumber}. ${item.horseName}</span>
        <span class="chart-legend-finish">${item.finishSort < 90 ? `${item.finishSort}위` : "—"}</span>
      `;
      button.addEventListener("click", () => {
        if (state.pinned.has(item.horseNumber)) {
          state.pinned.delete(item.horseNumber);
        } else {
          state.pinned.add(item.horseNumber);
        }
        applyActiveState();
      });
      button.addEventListener("mouseenter", () => {
        state.hover = item.horseNumber;
        applyActiveState();
      });
      button.addEventListener("mouseleave", () => {
        state.hover = null;
        applyActiveState();
      });
      legend.appendChild(button);
    }

    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "chart-legend-reset";
    reset.textContent = "상위 5두";
    reset.addEventListener("click", () => {
      state.pinned = new Set(
        data.series
          .filter((item) => item.finishSort > 0 && item.finishSort <= 5)
          .map((item) => item.horseNumber)
      );
      state.hover = null;
      applyActiveState();
    });
    legend.appendChild(reset);

    const all = document.createElement("button");
    all.type = "button";
    all.className = "chart-legend-reset";
    all.textContent = "전체";
    all.addEventListener("click", () => {
      state.pinned = new Set();
      state.hover = null;
      applyActiveState();
    });
    legend.appendChild(all);
  }

  function refreshLegendColors() {
    legend.querySelectorAll(".chart-legend-item").forEach((button) => {
      const horseNumber = Number(button.getAttribute("data-horse"));
      const swatch = button.querySelector("[data-swatch]");
      if (swatch instanceof HTMLElement) {
        swatch.style.background = colorFor(horseNumber);
      }
    });
  }

  // Catmull-Rom 보간으로 부드러운 곡선 path 생성
  function smoothPath(points) {
    if (points.length < 2) {
      return "";
    }
    let d = `M${points[0].x},${points[0].y}`;
    for (let i = 0; i < points.length - 1; i += 1) {
      const p0 = points[Math.max(i - 1, 0)];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[Math.min(i + 2, points.length - 1)];
      const c1x = p1.x + (p2.x - p0.x) / 6;
      const c1y = p1.y + (p2.y - p0.y) / 6;
      const c2x = p2.x - (p3.x - p1.x) / 6;
      const c2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2.x},${p2.y}`;
    }
    return d;
  }

  function drawChart() {
    const width = Math.max(root.clientWidth || 720, 480);
    const height = 380;
    const margin = { top: 30, right: 40, bottom: 46, left: 46 };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const maxPos = Math.max(data.maxPosition, 1);
    const n = data.labels.length;

    const xAt = (index) =>
      margin.left + (n === 1 ? plotW / 2 : (plotW * index) / (n - 1));
    const yAt = (position) =>
      margin.top + ((position - 1) / Math.max(maxPos - 1, 1)) * plotH;

    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", String(width));
    svg.setAttribute("height", String(height));
    svg.innerHTML = "";

    const ns = "http://www.w3.org/2000/svg";
    const add = (name, attrs = {}, parent = svg) => {
      const node = document.createElementNS(ns, name);
      for (const [key, value] of Object.entries(attrs)) {
        node.setAttribute(key, String(value));
      }
      parent.appendChild(node);
      return node;
    };

    for (let pos = 1; pos <= maxPos; pos += 1) {
      const y = yAt(pos);
      add("line", {
        x1: margin.left,
        y1: y,
        x2: margin.left + plotW,
        y2: y,
        class: "chart-grid",
      });
      add("text", {
        x: margin.left - 10,
        y: y + 4,
        class: "chart-axis-label",
        "text-anchor": "end",
      }).textContent = String(pos);
    }

    data.labels.forEach((label, index) => {
      const x = xAt(index);
      add("line", {
        x1: x,
        y1: margin.top,
        x2: x,
        y2: margin.top + plotH,
        class: "chart-grid-v",
      });
      add("text", {
        x,
        y: height - 16,
        class: "chart-axis-label",
        "text-anchor": "middle",
      }).textContent = label;
    });

    add("text", {
      x: 14,
      y: 16,
      class: "chart-axis-title",
    }).textContent = "통과순위 (위쪽이 앞)";

    const ordered = [...data.series].sort((a, b) => b.finishSort - a.finishSort);
    const animate = !REDUCED_MOTION && !state.animated;

    for (const item of ordered) {
      const color = colorFor(item.horseNumber);
      const points = item.positions
        .map((position, index) =>
          position == null ? null : { x: xAt(index), y: yAt(position), index, position }
        )
        .filter(Boolean);

      if (points.length === 0) {
        continue;
      }

      const group = add("g", {
        class: "chart-series",
        "data-horse": item.horseNumber,
      });

      if (points.length > 1) {
        const path = add(
          "path",
          {
            d: smoothPath(points),
            fill: "none",
            stroke: color,
            "stroke-width": 2.8,
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
            opacity: 1,
            class: "chart-line",
          },
          group
        );
        if (animate) {
          const length = path.getTotalLength();
          path.setAttribute("stroke-dasharray", String(length));
          path.setAttribute("stroke-dashoffset", String(length));
          path.classList.add("chart-line-draw");
          const delay = Math.min(Math.max(item.finishSort, 1), 20) * 35;
          path.style.animationDelay = `${delay}ms`;
          path.addEventListener(
            "animationend",
            () => {
              path.removeAttribute("stroke-dasharray");
              path.removeAttribute("stroke-dashoffset");
              path.classList.remove("chart-line-draw");
            },
            { once: true }
          );
        }
      }

      for (const point of points) {
        add(
          "circle",
          {
            cx: point.x,
            cy: point.y,
            r: 4.5,
            fill: color,
            opacity: 1,
            class: "chart-point",
            "data-horse": item.horseNumber,
            "data-index": point.index,
          },
          group
        );
        // 넓은 투명 히트 영역 — 정확히 점 위에 올리지 않아도 툴팁 표시
        const hit = add(
          "circle",
          {
            cx: point.x,
            cy: point.y,
            r: 13,
            fill: "transparent",
            class: "chart-hit",
          },
          group
        );
        hit.addEventListener("mouseenter", (event) => {
          showTooltip(event, item, point.index);
          state.hover = item.horseNumber;
          applyActiveState();
        });
        hit.addEventListener("mousemove", (event) => {
          positionTooltip(event);
        });
        hit.addEventListener("mouseleave", () => {
          hideTooltip();
          state.hover = null;
          applyActiveState();
        });
      }

      const last = points[points.length - 1];
      add(
        "text",
        {
          x: last.x + 8,
          y: last.y + 4,
          class: "chart-end-label",
          fill: color,
          opacity: 1,
        },
        group
      ).textContent = String(item.horseNumber);
    }

    state.animated = true;
    applyActiveState();
  }

  function positionTooltip(event) {
    if (!(tooltip instanceof HTMLElement)) {
      return;
    }
    const rect = frame.getBoundingClientRect();
    const gap = 14;
    const edge = 8;
    const cursorX = event.clientX - rect.left;
    const cursorY = event.clientY - rect.top;
    const tooltipWidth = tooltip.offsetWidth;
    const tooltipHeight = tooltip.offsetHeight;

    let left = cursorX + gap;
    if (left + tooltipWidth > rect.width - edge) {
      left = cursorX - tooltipWidth - gap;
    }
    left = Math.max(edge, Math.min(left, rect.width - tooltipWidth - edge));

    let top = cursorY - tooltipHeight - gap;
    if (top < edge) {
      top = cursorY + gap;
    }
    top = Math.max(edge, Math.min(top, rect.height - tooltipHeight - edge));

    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function showTooltip(event, item, index) {
    if (!(tooltip instanceof HTMLElement)) {
      return;
    }
    const position = item.positions[index];
    const segmentTime = item.segmentTimes[index];
    const cumulativeTime = item.cumulativeTimes[index];
    const label = data.labels[index];
    const timing = [
      segmentTime ? `${data.segmentLabels?.[index] || "구간"} ${segmentTime}` : "",
      cumulativeTime ? `누적 ${cumulativeTime}` : "",
    ].filter(Boolean).join(" · ");
    tooltip.hidden = false;
    tooltip.innerHTML = `
      <strong>${item.horseNumber}. ${item.horseName}</strong>
      <span>${label} · ${position ?? "—"}위${timing ? ` · ${timing}` : ""}</span>
    `;
    positionTooltip(event);
  }

  function hideTooltip() {
    if (tooltip instanceof HTMLElement) {
      tooltip.hidden = true;
    }
  }

  buildLegend();
  drawChart();

  window.addEventListener("resize", () => {
    window.clearTimeout(root._chartResizeTimer);
    root._chartResizeTimer = window.setTimeout(drawChart, 120);
  });

  window.addEventListener("hr:themechange", () => {
    refreshLegendColors();
    drawChart();
  });
})();
