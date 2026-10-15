/* Full precision model probabilities; odds arithmetic stays in the browser. */
(() => {
  "use strict";
  const fairOdds = (p) => Number.isFinite(p) && p > 0 && p <= 1 ? 1 / p : null;
  const expectedRoi = (p, odds) => (
    Number.isFinite(p) && p >= 0 && p <= 1 && Number.isFinite(odds) && odds >= 1
      ? p * odds - 1 : null
  );
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { fairOdds, expectedRoi };
  }
  if (typeof document === "undefined") return;
  document.querySelectorAll("[data-jeju-wagers]").forEach((root) => {
    if (root.dataset.initialized) return;
    const dataNode = root.querySelector("[data-jeju-wager-data]");
    if (!dataNode) return;
    let data;
    try { data = JSON.parse(dataNode.textContent); } catch (_) { return; }
    if (!Array.isArray(data.pools)) return;
    root.dataset.initialized = "true";
    const oddsValues = new Map();
    const cell = (text) => {
      const element = document.createElement("td");
      element.textContent = text;
      return element;
    };
    const oddsText = (value) => {
      if (value === null || !Number.isFinite(value)) return "—";
      return `${value >= 1e8 ? value.toExponential(2) : value.toLocaleString("ko-KR", {
        minimumFractionDigits: 2, maximumFractionDigits: 2,
      })}배`;
    };
    data.pools.forEach((pool) => {
      const section = [...root.querySelectorAll("[data-wager-pool]")]
        .find((node) => node.dataset.wagerPool === pool.code);
      if (!section || !Array.isArray(pool.rows)) return;
      const body = section.querySelector("[data-wager-rows]");
      const expand = section.querySelector("[data-wager-expand]");
      let expanded = false;
      let rendered = false;
      const render = () => {
        const fragment = document.createDocumentFragment();
        pool.rows.slice(0, expanded ? pool.rows.length : 6).forEach((item) => {
          const p = item.probability;
          if (!Number.isFinite(p) || p < 0 || p > 1 || !Array.isArray(item.selection)
              || !item.selection.every(Number.isInteger)) return;
          const selection = item.selection.join(["EXA", "TRI"].includes(pool.code) ? " → " : "-");
          const key = `${pool.code}:${item.selection.join("-")}`;
          const row = document.createElement("tr");
          const percentage = p > 0 && p < 0.00001 ? "<0.001%" : `${(p * 100).toFixed(3)}%`;
          row.append(cell(selection), cell(percentage), cell(oddsText(fairOdds(p))));
          const inputCell = cell("");
          const input = document.createElement("input");
          input.type = "number";
          input.min = "1";
          input.step = "any";
          input.inputMode = "decimal";
          input.placeholder = "배";
          input.setAttribute("aria-label", `${pool.label} ${selection} 확인한 배당`);
          input.value = oddsValues.get(key) || "";
          inputCell.append(input);
          const output = cell("—");
          const update = () => {
            const value = input.value.trim();
            const roi = value === "" || input.validity.badInput ? null : expectedRoi(p, Number(value));
            input.setAttribute("aria-invalid", value !== "" && roi === null ? "true" : "false");
            const invalidMessage = value !== "" && roi === null ? "1배 이상 입력" : "—";
            output.textContent = roi === null ? invalidMessage : `${roi > 0 ? "+" : ""}${(roi * 100).toFixed(2)}%`;
            oddsValues.set(key, value);
          };
          input.addEventListener("input", update);
          update();
          row.append(inputCell, output);
          fragment.append(row);
        });
        body.replaceChildren(fragment);
        rendered = true;
      };
      if (section.open) render();
      section.addEventListener("toggle", () => { if (section.open && !rendered) render(); });
      if (expand) expand.addEventListener("click", () => {
        expanded = !expanded;
        expand.textContent = expanded ? "상위 6조합만 보기" : `전체 ${pool.rows.length}조합 보기`;
        expand.setAttribute("aria-expanded", String(expanded));
        render();
      });
    });
  });
})();
