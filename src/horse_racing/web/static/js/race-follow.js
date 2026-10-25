/* Time-based race following, independent of result ingestion. */
(() => {
  "use strict";
  function pickRace(races, now, grace = 60000) {
    const timed = races.filter(r => Number.isSafeInteger(r.id) && Number.isFinite(r.start)
      && r.status !== "cancelled").sort((a, b) => a.start - b.start);
    return timed.find(r => r.start + grace > now) || timed[timed.length - 1] || null;
  }

  function createFollower({ now, races, initialId, select, render = () => {} }) {
    let selected = initialId, pinned = false, generation = 0, pending = false, retryAt = 0;
    return {
      pin(value, id = selected) { pinned = value; selected = id; generation++; retryAt = 0; },
      get pinned() { return pinned; },
      async tick() {
        const current = pickRace(races(), now());
        render(current, pinned);
        if (pinned || !current || current.id === selected || pending || now() < retryAt) return;
        const version = generation;
        pending = true;
        try {
          if (await select(current.id)) {
            if (version === generation) selected = current.id;
          } else if (version === generation) retryAt = now() + 15000;
        } catch (_) {
          if (version === generation) retryAt = now() + 15000;
        } finally { pending = false; }
      },
    };
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { pickRace, createFollower };
  if (typeof document === "undefined") return;
  const source = document.querySelector("[data-race-follow-data]");
  const controls = document.querySelector("[data-race-follow-controls]");
  if (!source || !controls) return;
  let data, contextUrl = new URL(location.href), clockAt = performance.now();
  let refreshing = false, pollAt = 0, disposed = false, requestController;
  let serverAt = 0;
  const valid = value => value && /^\d{4}-\d{2}-\d{2}$/.test(value.date)
    && typeof value.today === "string" && Number.isFinite(value.serverNow)
    && value.graceMs === 60000 && Array.isArray(value.races) && value.races.length <= 100
    && value.races.every(r => Number.isSafeInteger(r.id) && r.id > 0
      && (r.start === null || Number.isFinite(r.start)) && typeof r.status === "string");
  try { data = JSON.parse(source.textContent); } catch (_) { return; }
  if (!valid(data)) return;
  serverAt = data.serverNow;
  const now = () => serverAt + performance.now() - clockAt;
  const live = () => data.date === data.today && data.races.some(r => Number.isFinite(r.start));
  const mobile = document.documentElement.dataset.layout === "mobile";
  const resume = controls.querySelector("[data-race-follow-resume]");
  const status = controls.querySelector("[data-race-follow-status]");
  const manuallySelected = () => contextUrl.searchParams.has("race_id")
    || contextUrl.searchParams.has("trial_id") || /^#round-\d+$/.test(contextUrl.hash);
  const selectedId = () => mobile
    ? Number(contextUrl.hash.match(/^#round-(\d+)$/)?.[1]
      || contextUrl.searchParams.get("race_id")
      || document.querySelector(".mobile-round.is-current")?.id.replace("round-", ""))
    : Number(document.querySelector("[data-dashboard-detail]")?.dataset.raceId);
  const mobileCards = () => [...document.querySelectorAll(".mobile-round[id]")];
  const jumpLinks = () => [...document.querySelectorAll('.mobile-round-jump a[data-round-id]')];
  const roundId = link => link.dataset.roundId;

  let lastRender = "";
  function render(current, pinned) {
    const signature = JSON.stringify([live(), current?.id, pinned,
      data.races.map(r => [r.id, r.start, r.status, Number.isFinite(r.start) && now() >= r.start + data.graceMs])]);
    if (signature === lastRender) return;
    lastRender = signature;
    controls.hidden = !live();
    resume.hidden = !pinned;
    status.textContent = pinned ? "선택한 경주 보기" : "출발 1분 후 자동 전환";
    if (!live() || pinned || !current) return;
    const clockText = race => Number.isFinite(race.start)
      ? new Intl.DateTimeFormat("en-GB", { timeZone:"Asia/Seoul", hour:"2-digit", minute:"2-digit" }).format(race.start)
      : "미정";
    if (mobile) {
      mobileCards().forEach(card => {
        const id = Number(card.id.replace("round-", ""));
        const race = data.races.find(r => r.id === id);
        card.classList.toggle("is-current", id === current.id);
        if (!race) return;
        card.querySelectorAll("[data-race-follow-clock]").forEach(n => { n.textContent = clockText(race); });
        const head = card.querySelector(".mobile-round-title");
        head?.querySelectorAll(".mobile-live-tag,.mobile-awaiting-tag").forEach(n => n.remove());
        if (race.status !== "scheduled" || !head) return;
        const waiting = Number.isFinite(race.start) && now() >= race.start + data.graceMs;
        if (!waiting && id !== current.id) return;
        const tag = document.createElement("span");
        tag.className = waiting ? "mobile-awaiting-tag" : "mobile-live-tag";
        tag.textContent = waiting ? "결과 대기" : "예정";
        head.append(tag);
      });
      jumpLinks().forEach(link => {
        const active = roundId(link) === `round-${current.id}`;
        link.classList.toggle("is-next", active);
        link.classList.toggle("active", active);
        if (active) link.setAttribute("aria-current", "true");
        else link.removeAttribute("aria-current");
        link.querySelectorAll(".ma-next-label").forEach(n => n.remove());
        const race = data.races.find(r => `round-${r.id}` === roundId(link));
        if (race) link.querySelectorAll("[data-race-follow-clock]").forEach(n => { n.textContent = clockText(race); });
        if (active && race?.status === "scheduled" && now() < race.start + data.graceMs) {
          const label = document.createElement("span");
          label.className = "ma-next-label"; label.textContent = "예정 · ";
          link.querySelector("span")?.prepend(label);
        }
      });
    } else {
      document.querySelectorAll("[data-dashboard-race-id]").forEach(row => {
        const race = data.races.find(r => r.id === Number(row.dataset.dashboardRaceId));
        const badge = row.querySelector(".race-status-badge");
        if (race) row.querySelectorAll("[data-race-follow-clock]").forEach(n => { n.textContent = clockText(race); });
        if (race?.status === "scheduled" && Number.isFinite(race.start) && badge) {
          badge.textContent = now() >= race.start + data.graceMs ? "결과 대기" : "예정";
        }
      });
    }
  }

  function select(id) {
    if (!mobile) return new Promise(resolve => {
      document.dispatchEvent(new CustomEvent("race-follow-select", { detail: { id, done: resolve } }));
    });
    const cards = mobileCards();
    const ordered = data.races.map(r => cards.find(card => card.id === `round-${r.id}`)).filter(Boolean);
    const index = ordered.findIndex(card => card.id === `round-${id}`);
    if (index < 0) return false;
    const rotated = [...ordered.slice(index), ...ordered.slice(0, index)];
    const parent = rotated[0].parentElement;
    if (!rotated.every(card => card.parentElement === parent)) return false;
    parent.append(...rotated);
    const links = jumpLinks();
    const sortedLinks = rotated.map(card => links.find(link => roundId(link) === card.id)).filter(Boolean);
    if (sortedLinks.length && sortedLinks.every(link => link.parentElement === sortedLinks[0].parentElement)) {
      sortedLinks[0].parentElement.append(...sortedLinks);
    }
    document.dispatchEvent(new CustomEvent("race-follow-mobile-selected", { detail: { id } }));
    return true;
  }
  const follower = createFollower({ now, races: () => data.races,
    initialId: selectedId(), select, render });
  follower.pin(manuallySelected(), selectedId());
  if (mobile && live() && follower.pinned) select(selectedId());
  const tick = () => { if (!disposed && !document.hidden && live()) return follower.tick(); };

  async function refresh() {
    if (disposed || document.hidden || !live() || refreshing || performance.now() < pollAt) return;
    refreshing = true;
    pollAt = performance.now() + 60000;
    const version = contextUrl.href;
    requestController = new AbortController();
    const started = performance.now();
    const deadline = setTimeout(() => requestController.abort(), 8000);
    try {
      const url = new URL("/api/race-follow", location.origin);
      url.searchParams.set("date", data.date);
      if (contextUrl.searchParams.has("meet")) url.searchParams.set("meet", contextUrl.searchParams.get("meet"));
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store",
        signal: requestController.signal });
      if (!response.ok) return;
      const incoming = await response.json();
      if (disposed || version !== contextUrl.href || !valid(incoming) || incoming.date !== data.date) return;
      data = incoming;
      clockAt = performance.now();
      serverAt = data.serverNow + (clockAt - started) / 2;
      render(pickRace(data.races, now()), follower.pinned);
      await tick();
    } catch (_) { /* The local timer continues when the schedule request fails. */ }
    finally { clearTimeout(deadline); refreshing = false; }
  }
  document.addEventListener("race-follow-pin", event => {
    contextUrl = new URL(location.href);
    follower.pin(true, event.detail?.id || selectedId()); render(null, true);
  });
  document.addEventListener("race-follow-context", event => {
    let incoming;
    try { incoming = JSON.parse(event.detail.data); } catch (_) { return; }
    if (!valid(incoming)) return;
    data = incoming;
    contextUrl = new URL(event.detail.url, location.href);
    serverAt = data.serverNow; clockAt = performance.now(); pollAt = 0;
    follower.pin(manuallySelected(), selectedId());
    render(pickRace(data.races, now()), follower.pinned); tick(); refresh();
  });
  const restore = () => {
    contextUrl = new URL(location.href);
    follower.pin(manuallySelected(), selectedId());
    render(pickRace(data.races, now()), follower.pinned); tick();
  };
  window.addEventListener("hashchange", restore);
  window.addEventListener("popstate", restore);
  resume.addEventListener("click", () => {
    const url = new URL(location.href);
    url.searchParams.delete("race_id"); url.searchParams.delete("trial_id"); url.hash = "";
    history.replaceState(null, "", url);
    contextUrl = url;
    follower.pin(false, null); tick(); pollAt = 0; refresh();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { tick(); refresh(); } });
  window.addEventListener("pageshow", () => { tick(); refresh(); });
  const timer = setInterval(() => { tick(); refresh(); }, 1000);
  window.addEventListener("pagehide", event => {
    requestController?.abort();
    if (!event.persisted) { disposed = true; clearInterval(timer); }
  });
  render(pickRace(data.races, now()), follower.pinned); tick(); refresh();
})();
