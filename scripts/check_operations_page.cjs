/* Optional isolated browser QA. Needs Playwright in NODE_PATH; never contacts the DB. */
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  const errors = [], external = [];
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("request", request => { if (/^https?:/.test(request.url())) external.push(request.url()); });
  const navigate = view => page.locator(`[data-view="${view}"]`).click();
  const noOverflow = async label => {
    const overflow = await page.evaluate(() => ({
      width: innerWidth, actual: document.documentElement.scrollWidth,
      elements: [...document.querySelectorAll("body *")].filter(node => {
        const r = node.getBoundingClientRect();
        return r.width && r.right > innerWidth + 1;
      }).slice(0, 16).map(node => ({ tag: node.tagName, class: node.className,
        width: node.getBoundingClientRect().width }))
    }));
    if (overflow.actual > overflow.width + 1) {
      await page.screenshot({ path: "/tmp/horse-operations-overflow.png", fullPage: true });
      assert.fail(`${label}: viewport overflow ${JSON.stringify(overflow)}`);
    }
  };
  try {
    await page.goto(pathToFileURL(path.resolve(__dirname, "../operations/index.html")).href);
    await page.waitForSelector(".schedule-row");
    await page.keyboard.press("Tab");
    assert(await page.locator(".skip-link").evaluate(node => node === document.activeElement));
    assert.match(await page.locator("#metric-total").innerText(), /12/);
    await page.getByRole("button", { name: "수요일 일정", exact: true }).click();
    assert.match(await page.locator("#schedule").innerText(), /15:10[\s\S]*16:10/);
    await noOverflow("desktop overview");
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: "/tmp/horse-operations-desktop.png", fullPage: true });
    await navigate("jobs");
    assert.equal(await page.locator(".job-item").count(), 12);
    await page.locator('[data-filter="cloud"]').click();
    assert.equal(await page.locator(".job-item").count(), 2);
    await page.locator('[data-filter="local"]').click();
    assert.equal(await page.locator(".job-item").count(), 10);
    await page.locator("#search").fill("API215");
    assert.equal(await page.locator(".job-item").count(), 1);
    assert.match(await page.locator("#job-detail").innerText(), /미제공 개별 순위는 추정하지 않습니다/);
    await page.locator("#search").fill("no such job");
    assert.match(await page.locator("#job-list").innerText(), /검색 결과가 없습니다/);
    await page.locator("#search").fill("");
    await page.locator('[data-filter="all"]').click();
    await page.locator(".copy").first().click();
    await page.locator("#toast").waitFor({ state: "visible" });
    assert.match(await page.locator("#toast").innerText(), /복사|선택/);
    await navigate("sources");
    assert.equal(await page.locator(".doc-card").count(), 9);
    assert.equal(await page.locator("#api-table > tr").count(), 21);
    for (let index = 0; index < 9; index++) {
      await page.locator(".doc-card").nth(index).click();
      assert(await page.locator("#document-dialog").isVisible());
      assert((await page.locator("#document-body").innerText()).length > 100);
      await page.keyboard.press("Escape");
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => document.getElementById("toast").hidden = true);
    for (const view of ["overview", "jobs", "storage", "sources", "pending"]) {
      await navigate(view);
      await noOverflow(`mobile ${view}`);
    }
    await navigate("overview");
    await page.screenshot({ path: "/tmp/horse-operations-mobile.png", fullPage: true });
    await navigate("sources");
    await page.locator(".doc-card").first().click();
    await noOverflow("mobile document");
    await page.locator("#close-document").click();
    assert.deepEqual(errors, [], "Browser errors / CSP violations");
    assert.deepEqual(external, [], "Unexpected external requests");
    console.log("PASS: schedules, 12 jobs, filters/search, 9 documents, 21 API paths, copy, mobile layout; no browser errors or external requests.");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
