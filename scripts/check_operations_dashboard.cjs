/* Local read-only UI QA. Run against python -m horse_racing.operations on 127.0.0.1. */
const assert = require("node:assert/strict");
const {chromium} = require("playwright");
const origin = "http://127.0.0.1:8765";

(async () => {
  const browser = await chromium.launch({headless: true, channel: "chrome"});
  const context = await browser.newContext({viewport: {width: 1440, height: 1050}, reducedMotion: "reduce"});
  const page = await context.newPage(), errors = [], external = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => {if (message.type() === "error") errors.push(message.text());});
  page.on("request", request => {if (new URL(request.url()).origin !== origin) external.push(request.url());});
  async function settled() {
    await page.locator("#loading").waitFor({state: "hidden", timeout: 55000});
    assert(!await page.locator("#error").isVisible(), await page.locator("#error").textContent());
  }
  async function navigate(view) {await page.locator(`.nav-item[data-view="${view}"]`).click(); await settled();}
  async function noOverflow(label) {
    const sizes = await page.evaluate(() => ({actual: document.documentElement.scrollWidth, width: innerWidth}));
    assert(sizes.actual <= sizes.width + 1, `${label}: ${JSON.stringify(sizes)}`);
  }
  try {
    assert.equal((await page.goto(origin)).status(), 200);
    await page.waitForSelector(".status-card", {timeout: 55000}); await settled();
    assert.equal(await page.locator(".status-card").count(), 15);
    await noOverflow("desktop overview");
    await page.screenshot({path: "/tmp/horse-operations-dashboard-desktop.png", fullPage: true});
    await page.locator("#recent-table .run-link").first().click();
    await page.locator("#run-dialog").waitFor({state: "visible"});
    assert.match(await page.locator("#run-content").innerText(), /수집 종류/);
    await page.getByRole("button", {name: "닫기", exact: true}).click();
    await navigate("history");
    assert.equal(await page.locator("#history-results tbody tr").count(), 50);
    await page.locator("#more-runs").click(); await settled();
    assert.equal(await page.locator("#history-results tbody tr").count(), 100);
    await page.locator('#history-form select[name="status"]').selectOption("failed");
    await page.getByRole("button", {name: "이력 조회", exact: true}).click(); await settled();
    const statuses = await page.locator("#history-results .pill").allTextContents();
    assert(statuses.length && statuses.every(s => s === "실패"));
    await navigate("search");
    await page.locator("#data-kind").selectOption("medical");
    await page.getByRole("button", {name: "저장 데이터 조회", exact: true}).click(); await settled();
    assert.match(await page.locator("#search-notes").innerText(), /말을 먼저/);
    await page.locator("#horse-query").fill("올수");
    await page.getByRole("button", {name: "말 찾기", exact: true}).click(); await settled();
    await page.locator(".horse-option").first().click();
    assert.match(await page.locator("#selected-horse").innerText(), /선택: 올수/);
    await page.getByRole("button", {name: "저장 데이터 조회", exact: true}).click(); await settled();
    // Verify collector-origin text remains text, with no HTML execution.
    await page.route("**/api/data?**", route => route.fulfill({json: {
      rows: [{diagnosis_1: '<img src=x onerror="window.opsXss=1">', diagnosis_2: "원문 보존"}],
      has_more: false, notes: ["UI 안전성 테스트 응답 · 실제 DB 변경 없음"],
    }}));
    await page.getByRole("button", {name: "저장 데이터 조회", exact: true}).click(); await settled();
    assert.match(await page.locator("#data-results").innerText(), /<img/);
    assert.equal(await page.locator("#data-results img").count(), 0);
    assert.equal(await page.evaluate(() => window.opsXss), undefined);
    await page.unroute("**/api/data?**");
    await navigate("issues");
    assert.equal(await page.locator("#issue-metrics .metric").count(), 4);
    await noOverflow("desktop issues");
    if (await page.locator("#issue-results .run-link").count()) {
      await page.locator("#issue-results .run-link").first().click(); await settled();
      assert(await page.locator("#view-search").isVisible());
    }
    await page.setViewportSize({width: 390, height: 844});
    for (const view of ["overview", "history", "search", "issues"]) {await navigate(view); await noOverflow("mobile " + view);}
    await navigate("overview");
    await page.screenshot({path: "/tmp/horse-operations-dashboard-mobile.png", fullPage: true});
    assert.deepEqual(errors, [], "Browser errors / CSP violations");
    assert.deepEqual(external, [], "No external browser requests allowed");
    console.log("PASS: 15 statuses, execution detail/pagination/filter, horse/data search, gap links, XSS escaping, desktop/mobile overflow, no browser errors/external requests.");
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
