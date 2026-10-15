const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const { fairOdds, expectedRoi } = require("../src/horse_racing/web/static/js/jeju-wagers.js");

test("full precision fair odds and gross payout expected return", () => {
  assert.equal(fairOdds(0.2), 5);
  assert.equal(fairOdds(0.0023456789), 1 / 0.0023456789);
  assert.ok(Math.abs(expectedRoi(0.2, 6) - 0.2) < 1e-14);
  assert.ok(Math.abs(expectedRoi(0.2, 4) + 0.2) < 1e-14);
  assert.equal(expectedRoi(0.2, 5), 0);
  assert.equal(expectedRoi(0, 100), -1);
});

test("missing, nonnumeric and nonfinite odds never turn into positive EV", () => {
  for (const odds of [null, undefined, "6", NaN, Infinity, -1, 0, 0.5]) {
    assert.equal(expectedRoi(0.2, odds), null);
  }
  for (const p of [null, undefined, "0.2", NaN, Infinity, -1, 1.01]) {
    assert.equal(expectedRoi(p, 6), null);
    assert.equal(fairOdds(p), null);
  }
  assert.equal(fairOdds(0), null);
});

test("wager rows render lazily, compare odds, preserve edits and use safe text nodes", () => {
  class Node {
    constructor() {
      this.dataset = {}; this.children = []; this.attributes = {}; this.listeners = {};
      this.value = ""; this.validity = { badInput: false }; this.textContent = "";
    }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(fragment) { this.children = fragment.children; }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener(key, callback) { this.listeners[key] = callback; }
    set innerHTML(_) { throw new Error("Untrusted HTML insertion"); }
  }
  const root = new Node(), section = new Node(), body = new Node(), button = new Node();
  section.dataset.wagerPool = "TLA";
  section.open = true;
  const data = new Node();
  data.textContent = JSON.stringify({ pools: [{ code: "TLA", label: "<script>test</script>",
    rows: Array.from({ length: 12 }, (_, i) => ({ selection: [1, 2, i + 3], probability: 0.2 })),
  }] });
  root.querySelector = () => data;
  root.querySelectorAll = () => [section];
  section.querySelector = (key) => key === "[data-wager-rows]" ? body : button;
  const document = {
    querySelectorAll: () => [root],
    createElement: () => new Node(),
    createDocumentFragment: () => new Node(),
  };
  const source = fs.readFileSync("src/horse_racing/web/static/js/jeju-wagers.js", "utf8");
  vm.runInNewContext(source, { document });
  assert.equal(body.children.length, 6);
  let row = body.children[0];
  assert.equal(row.children[2].textContent, "5.00배");
  let input = row.children[3].children[0];
  assert.match(input.attributes["aria-label"], /<script>test<\/script>/);
  assert.equal(row.children[4].textContent, "—");
  input.value = "6";
  input.listeners.input();
  assert.equal(row.children[4].textContent, "+20.00%");
  button.listeners.click();
  assert.equal(body.children.length, 12);
  row = body.children[0];
  input = row.children[3].children[0];
  assert.equal(input.value, "6");
  assert.equal(row.children[4].textContent, "+20.00%");
  input.value = "0.5";
  input.listeners.input();
  assert.equal(row.children[4].textContent, "1배 이상 입력");
  input.value = "";
  input.listeners.input();
  assert.equal(row.children[4].textContent, "—");
  button.listeners.click();
  assert.equal(body.children.length, 6);
});
