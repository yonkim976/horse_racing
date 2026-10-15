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
    this.scrollWidth = 0;
    this.clientWidth = 0;
    this.scrollLeft = 0;
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
  getClientRects() { return this.hidden ? [] : [this.getBoundingClientRect()]; }

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

  closest(selector) {
    for (let node = this; node; node = node.parentElement) {
      if (node.matches(selector)) return node;
    }
    return null;
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
  const parts = {};
  for (const name of ["passing-checkpoints", "passing-formation", "chart-legend", "passing-detail", "passing-title", "passing-location", "passing-source", "passing-count", "passing-prev", "passing-next", "passing-notation", "passing-lanes"]) {
    const node = new FakeHTMLElement(name.includes("prev") || name.includes("next") ? "button" : "div");
    node.setAttribute(`data-${name}`, "");
    root.append(node);
    parts[name] = node;
  }
  const script = new FakeHTMLScriptElement("script");
  script.textContent = JSON.stringify(payload);
  const document = {
    documentElement: { dataset: { theme: "dark" } },
    querySelector: (selector) => selector === "[data-section-chart]" ? root : null,
    getElementById: (id) => id === "section-chart-data" ? script : null,
    createElement: (name) => new FakeHTMLElement(name),
    createElementNS: (_namespace, name) => new FakeSVGElement(name),
  };
  return { document, root, parts };
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
  const { document, root, parts } = makeDocument(payload);
  const legend = parts["chart-legend"];
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
  assert.equal(legendLabel.textContent, `말 ${attack}`);
  assert.equal(legend.querySelectorAll("img").length, 0);
  const horse = parts["passing-formation"].querySelector("button");
  assert.ok(horse, "passing view rendered an interactive horse");
  horse.dispatch("click");
  assert.equal(parts["passing-detail"].querySelector("strong").textContent, `1. 말 ${attack}`);
  assert.ok(parts["passing-detail"].textContent.includes(attack));
  assert.equal(parts["passing-checkpoints"].querySelector("button").textContent, `1코너 ${attack}`);
  assert.equal(root.querySelectorAll("img").length, 0);
  assert.equal(context.xss, undefined);
});

function mountPassingView(payload, prepare, runtimeOverrides = {}) {
  const fixture = makeDocument(payload);
  if (prepare) prepare(fixture);
  const sourcePath = path.join(__dirname, "../src/horse_racing/web/static/js/race-chart.js");
  vm.runInNewContext(fs.readFileSync(sourcePath, "utf8"), {
    ...runtimeOverrides,
    document: fixture.document,
    HTMLScriptElement: FakeHTMLScriptElement,
  }, { filename: sourcePath, timeout: 1000 });
  return fixture;
}

test("passing navigation hides only unavailable G3F and keeps original timing indexes", () => {
  const payload = {
    labels: ["S1F", "G3F", "4C", "FIN"],
    series: [{ horseNumber: 2, horseName: "테스트마", finishSort: 2,
      positions: [2, 1, 3, 2], segmentTimes: ["초반", "숨긴 구간", "코너 기록", "결승 기록"],
      cumulativeTimes: [], finishTimeMs: 60200, finishMargin: "목" }],
    checkpoints: [
      { label: "S1F", mode: "official", groups: [{horses: [2], distanceLengths: 0}] },
      { label: "G3F", mode: "rank", groups: [{horses: [2], distanceLengths: null}] },
      { label: "4C", mode: "official", groups: [{horses: [2], distanceLengths: 3.5}] },
      { label: "FIN", mode: "finish", groups: [{horses: [2], distanceLengths: 1}] },
    ],
  };
  const { root, parts } = mountPassingView(payload);
  const buttons = parts["passing-checkpoints"].querySelectorAll("button");
  assert.deepEqual(buttons.map(button => button.textContent), ["S1F", "4C", "결승"]);
  parts["chart-legend"].querySelector("button").dispatch("click");
  buttons[1].dispatch("click");
  assert.ok(parts["passing-detail"].textContent.includes("1계단 하락"));
  assert.ok(parts["passing-detail"].textContent.includes("코너 기록"));
  assert.ok(!parts["passing-detail"].textContent.includes("숨긴 구간"));
  buttons[2].dispatch("click");
  assert.equal(parts["passing-title"].textContent, "결승 도착 간격");
  assert.equal(parts["passing-next"].disabled, true);
  assert.ok(parts["passing-detail"].textContent.includes("공식 착차 목"));
  assert.equal(parts["passing-source"].textContent, "공식 착차 기준");
  const silk = root.querySelector(".silk-2");
  assert.ok(silk.classList.contains("silk-number"));
  assert.equal(silk.style.background, undefined, "palette must come from shared CSS");
  payload.checkpoints[1].mode = "official";
  const official = mountPassingView(payload);
  assert.ok(official.parts["passing-checkpoints"].textContent.includes("G3F"));
});

test("finish geometry preserves margin scale and stacks equal offsets", () => {
  const payload = {
    labels: ["FIN"],
    series: [1, 2, 3].map(number => ({horseNumber: number, horseName: `말${number}`,
      finishSort: number, positions: [number], segmentTimes: [], cumulativeTimes: []})),
    checkpoints: [{ label: "FIN", mode: "finish", groups: [0, 0, 1].map((distance, i) => ({
      horses: [i + 1], distanceLengths: distance,
    })) }],
  };
  const { parts } = mountPassingView(payload);
  const packs = parts["passing-formation"].querySelectorAll(".passing-pack");
  assert.equal(packs[0].style.right, packs[1].style.right, "equal offsets share x position");
  assert.notEqual(packs[0].style.top, packs[1].style.top, "equal offsets remain distinguishable");
  assert.equal(parseFloat(packs[2].style.right) - parseFloat(packs[0].style.right), 28);
  assert.equal(packs[0].style.left, undefined, "leader is anchored from the right");
  assert.ok(parts["passing-lanes"].textContent.includes("내·외측을 뜻하지 않습니다"));
  assert.equal(parts["passing-formation"].querySelectorAll(".passing-inner-rail").length, 0);
  const ticks = parts["passing-formation"].querySelectorAll(".passing-axis")[0].children;
  assert.equal(ticks[0].textContent, "0");
  assert.equal(ticks[0].style.right, packs[0].style.right);
  assert.equal(parseFloat(ticks[1].style.right) - parseFloat(ticks[0].style.right), 56);
});

function finishMarginPayload(distance) {
  return {
    labels: ["FIN"],
    series: [1, 2].map(number => ({horseNumber: number, horseName: `말${number}`,
      finishSort: number, positions: [number], segmentTimes: [], cumulativeTimes: []})),
    checkpoints: [{label: "FIN", mode: "finish", groups: [
      {horses: [1], distanceLengths: 0},
      {horses: [2], distanceLengths: distance},
    ]}],
  };
}

function boundElementCreation({document}) {
  const createElement = document.createElement;
  let created = 0;
  document.createElement = name => {
    assert.ok(++created <= 1000, "chart exceeded its safe DOM creation budget");
    return createElement(name);
  };
}

test("invalid finish margins cannot expand the track or create unbounded ticks", () => {
  for (const distance of [1e9, 1e49, 1000.01, -1, Infinity, -Infinity, NaN]) {
    const payload = finishMarginPayload(distance);
    // JSON cannot encode NaN and normally turns nonfinite values into null.
    // Preserve them here to exercise the renderer's own numeric boundary too.
    const {parts} = mountPassingView(payload, boundElementCreation, {
      JSON: {parse: () => payload},
    });
    const formation = parts["passing-formation"];
    const unknown = formation.querySelector(".passing-unknown");
    assert.equal(unknown.querySelector(".passing-pack-label").textContent, "미제공");
    assert.equal(unknown.querySelector(".passing-pack").style.right, undefined);
    assert.equal(formation.querySelector(".passing-track").style.width, "364px");
    const ticks = formation.querySelector(".passing-axis").children;
    assert.ok(ticks.length <= 51);
    assert.equal(ticks.at(-1).textContent, "10");
  }
});

test("long valid finish margins retain the length scale with at most 51 axis ticks", () => {
  for (const distance of [0.3, 35.5, 100, 999.5, 1000]) {
    const {parts} = mountPassingView(finishMarginPayload(distance), boundElementCreation);
    const formation = parts["passing-formation"];
    const packs = formation.querySelectorAll(".passing-pack");
    assert.equal(formation.querySelector(".passing-unknown"), null);
    const pixelGap = parseFloat(packs[1].style.right) - parseFloat(packs[0].style.right);
    assert.ok(Math.abs(pixelGap - distance * 28) < 1e-9);
    assert.equal(packs[1].dataset.distanceLengths, String(distance));
    const ticks = formation.querySelector(".passing-axis").children;
    assert.ok(ticks.length <= 51);
    assert.equal(ticks[0].textContent, "0");
    for (const tick of ticks) {
      assert.equal(parseFloat(tick.style.right), 18 + Number(tick.textContent) * 28);
    }
  }
});

test("official packs put leaders on the right and keep original notation and member order", () => {
  const payload = {
    labels: ["4C", "G1F"],
    series: [1, 2, 3].map(number => ({horseNumber: number, horseName: `말${number}`,
      positions: [number, number], segmentTimes: [], cumulativeTimes: []})),
    checkpoints: ["4C", "G1F"].map(label => ({label, mode: "official", notation: "(1,2)-3",
      groups: [{horses: [1, 2], distanceLengths: 0}, {horses: [3], distanceLengths: 3.5}]})),
  };
  const { parts } = mountPassingView(payload);
  const packs = parts["passing-formation"].querySelectorAll(".passing-pack");
  assert.ok(parseFloat(packs[0].style.right) < parseFloat(packs[1].style.right));
  assert.deepEqual(packs[0].querySelectorAll(".silk-number").map(e => e.textContent), ["1", "2"]);
  assert.ok(parts["passing-notation"].textContent.includes("(1,2)-3"));
  assert.equal(packs[0].style.top, packs[1].style.top, "each pack starts from the inner fence");
  assert.equal(parts["passing-formation"].querySelectorAll(".passing-inner-rail").length, 1);
  assert.ok(parts["passing-lanes"].textContent.includes("위쪽 경계가 내측 펜스"));
  const formation = parts["passing-formation"];
  formation.scrollWidth = 1000;
  formation.clientWidth = 300;
  formation.scrollLeft = 400;
  packs[1].querySelector("button").dispatch("click");
  assert.equal(formation.scrollLeft, 400, "horse selection preserves horizontal view");
  parts["passing-next"].dispatch("click");
  assert.equal(formation.scrollLeft, 700, "next checkpoint opens at the right-side leader");
});

test("course map follows checkpoint aliases and never invents an unavailable location", () => {
  const payload = {
    labels: ["S1F/3C", "4C", "FIN"],
    series: [{horseNumber: 1, horseName: "말1", positions: [1, 1, 1]}],
    checkpoints: ["S1F/3C", "4C", "FIN"].map(label => ({label, mode: "official",
      groups: [{horses: [1], distanceLengths: 0}]})),
  };
  let markers, status, title;
  const {parts} = mountPassingView(payload, ({root}) => {
    markers = ["S1F", "FIN"].map(code => {
      const marker = new FakeHTMLElement("g");
      marker.setAttribute("data-passing-map-codes", code);
      root.append(marker);
      return marker;
    });
    status = new FakeHTMLElement("p");
    status.setAttribute("data-passing-map-status", "");
    title = new FakeHTMLElement("p");
    title.setAttribute("data-passing-map-title", "");
    root.append(status, title);
  });
  assert.ok(markers[0].classList.contains("is-current"));
  assert.ok(title.textContent.startsWith("S1F/3C"));
  parts["passing-next"].dispatch("click");
  assert.ok(markers.every(marker => !marker.classList.contains("is-current")));
  assert.ok(status.textContent.includes("확인되지 않아"));
  parts["passing-next"].dispatch("click");
  assert.ok(markers[1].classList.contains("is-current"));
  assert.ok(title.textContent.startsWith("결승"));
});
