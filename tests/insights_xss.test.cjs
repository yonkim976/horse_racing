const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

class FakeElement {
  constructor() {
    this.textContent = "";
    this.innerHTML = "";
    this.listeners = new Map();
    this.dataset = {};
    this.style = {};
    this.value = "0";
    this.options = [{ text: "보통" }];
    this.selectedIndex = 0;
  }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
}

function dataNode(value) {
  const node = new FakeElement();
  node.textContent = JSON.stringify(value);
  return node;
}

test("insights charts escape malicious text and attributes while rendering valid charts", () => {
  const attack = '</title><image onload="globalThis.xss = true">';
  const attributeAttack = '7" onmouseover="globalThis.xss = true';
  const paceData = dataNode([{
    id: attributeAttack,
    number: attack,
    name: attack,
    style: attack,
    early: 2,
    closing: 15,
  }]);
  const analysisData = dataNode([{
    horse_id: attributeAttack,
    name: `말 ${attack}`,
    trend: [{ date: attack, finish: '1" onload="globalThis.xss = true' }],
    distances: [{ distance: attack, rate: '0.7" onload="globalThis.xss = true', starts: attack }],
    early_position: attack,
    closing_time: attack,
    section_sample: attack,
  }]);
  const paceRoot = new FakeElement();
  const paceNodes = new Map([
    ["[data-pace-data]", paceData],
    ["[data-pace-track]", new FakeElement()],
    ["[data-pace-list]", new FakeElement()],
    ["[data-pace-label]", new FakeElement()],
    ["[data-pace-stage]", new FakeElement()],
    ["[data-pace-scenario]", new FakeElement()],
    ["[data-pace-play]", new FakeElement()],
  ]);
  const formChart = new FakeElement();
  const distanceChart = new FakeElement();
  const sectionChart = new FakeElement();
  const documentNodes = new Map([
    ["[data-pace-root]", paceRoot],
    ["[data-analysis-data]", analysisData],
    ["[data-form-chart]", formChart],
    ["[data-distance-chart]", distanceChart],
    ["[data-section-chart]", sectionChart],
  ]);
  paceRoot.querySelector = (selector) => paceNodes.get(selector) || null;
  const document = {
    querySelector: (selector) => documentNodes.get(selector) || null,
    querySelectorAll: () => [],
  };
  const context = {
    document,
    window: {},
    location: { search: "" },
    localStorage: { getItem: () => null, setItem() {} },
    URLSearchParams,
    FormData: class {},
    alert() {},
    setTimeout() { return 1; },
    clearTimeout() {},
    setInterval() { return 1; },
    clearInterval() {},
    Math,
    Number,
    String,
    JSON,
  };
  const sourcePath = path.join(__dirname, "../src/horse_racing/web/static/js/insights.js");
  vm.runInNewContext(fs.readFileSync(sourcePath, "utf8"), context, { filename: sourcePath });

  const trackHtml = paceNodes.get("[data-pace-track]").innerHTML;
  const paceListHtml = paceNodes.get("[data-pace-list]").innerHTML;
  assert.match(trackHtml, /<svg viewBox=/);
  assert.match(trackHtml, /<circle r="15"/);
  assert.match(trackHtml, /data-pace-id="7&quot; onmouseover=&quot;globalThis\.xss = true"/); // Quotes stay inside the SVG attribute.
  assert.match(trackHtml, /&lt;\/title&gt;&lt;image onload=&quot;globalThis.xss = true&quot;&gt;/);
  assert.match(paceListHtml, /<button type="button"/);
  assert.match(paceListHtml, /&lt;\/title&gt;&lt;image onload=&quot;globalThis.xss = true&quot;&gt;/);
  assert.doesNotMatch(trackHtml + paceListHtml, /<image\s/i);
  assert.doesNotMatch(trackHtml + paceListHtml, /onload="globalThis\.xss/);

  assert.match(formChart.innerHTML, /<svg viewBox=/);
  assert.match(formChart.innerHTML, /<circle class="chart-point"/);
  assert.match(formChart.innerHTML, /&lt;\/title&gt;&lt;image onload=&quot;globalThis.xss = true&quot;&gt;/);
  assert.doesNotMatch(formChart.innerHTML, /<image\s/i);
  assert.doesNotMatch(formChart.innerHTML, /onload="globalThis\.xss/);
  assert.match(distanceChart.innerHTML, /<rect x="160"/);
  assert.match(distanceChart.innerHTML, /0m/);
  assert.match(distanceChart.innerHTML, /0% · n=0/);
  assert.match(sectionChart.innerHTML, /<line class="chart-grid"/);
  assert.doesNotMatch(sectionChart.innerHTML, /NaN|onload="globalThis\.xss/);
  assert.equal(context.xss, undefined);
});
