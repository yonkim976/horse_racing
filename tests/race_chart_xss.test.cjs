const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.attributes = new Map();
    this.children = [];
    this.listeners = new Map();
    this.dataset = {};
    this.style = {};
    this.hidden = false;
    this.className = "";
    this.classList = {
      add: (...names) => this.setClasses([...this.classes, ...names]),
      remove: (...names) => this.setClasses(this.classes.filter((name) => !names.includes(name))),
      toggle: (name, force) => {
        const classes = new Set(this.classes);
        const shouldAdd = force ?? !classes.has(name);
        if (shouldAdd) classes.add(name);
        else classes.delete(name);
        this.setClasses([...classes]);
        return shouldAdd;
      },
      contains: (name) => this.classes.includes(name),
    };
  }

  get classes() {
    return this.className.split(/\s+/).filter(Boolean);
  }

  setClasses(names) {
    this.className = [...new Set(names)].join(" ");
  }

  set textContent(value) {
    this.children = [];
    this._text = String(value);
  }

  get textContent() {
    return (this._text || "") + this.children.map((child) => child.textContent).join("");
  }

  set innerHTML(_value) {
    throw new Error("HTML string parsing is forbidden in this XSS regression test");
  }

  append(...nodes) {
    for (const node of nodes) this.appendChild(node);
  }

  appendChild(node) {
    this.children.push(node);
    node.parentElement = this;
    return node;
  }

  replaceChildren(...nodes) {
    this.children = [];
    this._text = "";
    this.append(...nodes);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "class") this.className = String(value);
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      this.dataset[key] = String(value);
    }
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  addEventListener(name, callback) {
    const callbacks = this.listeners.get(name) || [];
    callbacks.push(callback);
    this.listeners.set(name, callbacks);
  }

  dispatch(name, event = {}) {
    for (const callback of this.listeners.get(name) || []) callback(event);
  }

  getTotalLength() { return 100; }
  get offsetWidth() { return 160; }
  get offsetHeight() { return 60; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 800, height: 400 }; }

  matches(selector) {
    const tag = selector.match(/^[a-z]+/i)?.[0];
    if (tag && this.tagName !== tag.toUpperCase()) return false;
    for (const cls of selector.matchAll(/\.([\w-]+)/g)) {
      if (!this.classes.includes(cls[1])) return false;
    }
    for (const attr of selector.matchAll(/\[([^\]=]+)(?:=["']?([^\]"']+)["']?)?\]/g)) {
      const [, name, value] = attr;
      if (!this.attributes.has(name) && !(name.startsWith("data-") && name.slice(5) in this.dataset)) return false;
      if (value != null && this.getAttribute(name) !== value) return false;
    }
    return true;
  }

  querySelectorAll(selector) {
    const found = [];
    const visit = (node) => {
      for (const child of node.children) {
        if (child.matches(selector)) found.push(child);
        visit(child);
      }
    };
    visit(this);
    return found;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}

class FakeHTMLElement extends FakeElement {}
class FakeSVGElement extends FakeHTMLElement {}
class FakeHTMLScriptElement extends FakeHTMLElement {}

function makeDocument(payload) {
  const root = new FakeHTMLElement("div");
  root.setAttribute("data-section-chart", "");
  root.clientWidth = 800;
  const svg = new FakeSVGElement("svg");
  svg.setAttribute("data-chart-svg", "");
  const frame = new FakeHTMLElement("div");
  frame.className = "section-chart-frame";
  const legend = new FakeHTMLElement("div");
  legend.setAttribute("data-chart-legend", "");
  const tooltip = new FakeHTMLElement("div");
  tooltip.setAttribute("data-chart-tooltip", "");
  frame.append(svg, tooltip);
  root.append(frame, legend);
  const script = new FakeHTMLScriptElement("script");
  script.textContent = JSON.stringify(payload);
  const document = {
    documentElement: { dataset: { theme: "dark" } },
    querySelector: (selector) => selector === "[data-section-chart]" ? root : null,
    getElementById: (id) => id === "section-chart-data" ? script : null,
    createElement: (name) => new FakeHTMLElement(name),
    createElementNS: (_namespace, name) => new FakeSVGElement(name),
  };
  return { document, root, svg, legend, tooltip };
}

test("race chart renders untrusted names, labels, and timings as text", () => {
  const attack = '<img src=x onerror="globalThis.xss = true">';
  const payload = {
    labels: [`1코너 ${attack}`],
    segmentLabels: [attack],
    maxPosition: 1,
    series: [{
      horseId: 1,
      horseNumber: 1,
      horseName: `말 ${attack}`,
      finishSort: 1,
      positions: [1],
      segmentTimes: [attack],
      cumulativeTimes: [attack],
    }],
  };
  const { document, svg, legend, tooltip } = makeDocument(payload);
  const context = {
    document,
    window: {
      matchMedia: () => ({ matches: true }),
      addEventListener() {},
      clearTimeout() {},
      setTimeout() { return 1; },
    },
    HTMLElement: FakeHTMLElement,
    SVGElement: FakeSVGElement,
    HTMLScriptElement: FakeHTMLScriptElement,
    Set,
    Math,
    Number,
    String,
    JSON,
  };
  const sourcePath = path.join(__dirname, "../src/horse_racing/web/static/js/race-chart.js");
  vm.runInNewContext(fs.readFileSync(sourcePath, "utf8"), context, { filename: sourcePath });

  const legendLabel = legend.querySelector(".chart-legend-label");
  assert.equal(legendLabel.textContent, `1. 말 ${attack}`);
  assert.equal(legend.querySelectorAll("img").length, 0);

  const hitArea = svg.querySelector(".chart-hit");
  assert.ok(hitArea, "chart rendered an interactive hit area");
  hitArea.dispatch("mouseenter", { clientX: 100, clientY: 100 });
  assert.equal(tooltip.querySelector("strong").textContent, `1. 말 ${attack}`);
  assert.equal(tooltip.querySelector("span").textContent, `1코너 ${attack} · 1위 · ${attack} ${attack} · 누적 ${attack}`);
  assert.equal(tooltip.querySelectorAll("img").length, 0);
  assert.equal(context.xss, undefined);
});
