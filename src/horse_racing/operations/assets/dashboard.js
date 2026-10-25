"use strict";
const $ = selector => document.querySelector(selector);
const token = $('meta[name="ops-token"]').content;
const titles = {
  overview: ["수집 현황", "데이터 수집 현황", "자동 수집의 마지막 실행과 확인이 필요한 항목을 한곳에서 살펴보세요."],
  history: ["실행 이력", "수집 실행 이력", "어떤 작업이 언제 실행되었고, 어떤 결과를 남겼는지 확인합니다."],
  search: ["데이터 검색", "운영 데이터 검색", "출마표부터 조교·진료·구간기록까지, 실제 저장된 값을 읽습니다."],
  issues: ["누락 의심", "확인이 필요한 데이터", "완료 경주와 연결 기록을 대조해 의심 항목을 찾습니다. 자동 보완하지 않습니다."],
};
const stateLabels = {completed: "실행 완료", failed: "실패", partial: "일부 실패", running: "실행 중", stale: "갱신 지연 의심", long_running: "장시간 실행 의심", unknown: "이력 없음"};
const labels = {
  date: "날짜", meet: "경마장", meet_code: "경마장 코드", race_no: "경주", race_id: "경주 ID",
  horse: "말 이름", horse_no: "공식 마번", horse_number: "출전 번호", kra_horse_id: "공식 마번", name_ko: "말 이름",
  rider: "기승자", duration_seconds: "조교 시간(초)", start: "입장", end: "퇴장", canter: "구보", gallop: "습보", evidence: "표시 근거",
  hospital: "병원", diagnosis_1: "진단 원문 1", diagnosis_2: "진단 원문 2", occurrence: "당일 저장 슬롯", stable: "조", remark: "비고",
  swim_count: "수영 횟수", quality_status: "품질 표시", farm_name: "목장", training_time_local: "훈련 시각", training_date_local: "훈련일",
  f1_seconds: "1F(초)", f2_seconds: "2F(초)", f3_seconds: "3F(초)", total_seconds: "합계(초)", metadata_version_count: "원문 버전 수",
  rating: "경주 당시 레이팅", body_weight_kg: "마체중(kg)", scratched: "취소", finish_position: "착순", finish_time_ms: "완주(ms)",
  point_code: "지점", time_kind: "시간 종류", elapsed_time_ms: "구간 기록(ms)", position_raw: "개별 통과순위", notation_raw: "통과조 원문",
  judgement: "심판·판정 원문", additional_judgement: "추가 심판 원문", jockey_change_note: "기수 변경", horse_name_raw: "말 이름(원문)", failure_reason: "불합격 사유",
};
let view = "overview", busy = 0, overviewLoaded = false, historyRows = [], nextCursor = null;
const loaded = new Set();
function el(tag, className, text) { const n = document.createElement(tag); if (className) n.className = className; if (text !== undefined) n.textContent = text; return n; }
function clear(node) { node.replaceChildren(); }
function number(n) { return Number(n || 0).toLocaleString("ko-KR"); }
function moment(ms, short = false) {
  if (!ms) return "—";
  return new Intl.DateTimeFormat("ko-KR", {timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, ...(short ? {} : {year: "numeric", second: "2-digit"})}).format(new Date(ms));
}
function isoMoment(value) { return value ? moment(new Date(value).getTime()) + " KST" : "—"; }
function pill(status) { return el("span", "pill state-" + status, stateLabels[status] || status); }
function textValue(value) { return value === null || value === undefined || value === "" ? "—" : typeof value === "boolean" ? (value ? "예" : "아니오") : String(value); }
async function api(path, params = {}) {
  const url = new URL(path, location.origin);
  Object.entries(params).forEach(([key, value]) => { if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, value); });
  busy++; $("#loading").hidden = false; $("#error").hidden = true;
  try {
    const response = await fetch(url, {headers: {"X-Operations-Token": token}, credentials: "same-origin", cache: "no-store"});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "조회 조건을 확인하세요. 기간은 최대 31일입니다.");
    $("#connection").textContent = "Supabase 조회 연결";
    return result;
  } catch (error) {
    $("#error").textContent = error.message || "조회하지 못했습니다. 로컬 서버가 실행 중인지 확인하세요.";
    $("#error").hidden = false;
    $("#connection").textContent = "최근 조회 실패";
    throw error;
  } finally { busy--; $("#loading").hidden = busy === 0; }
}
function notes(node, values) { clear(node); values.forEach(value => node.append(el(node.tagName === "UL" ? "li" : "p", "", value))); }
function metric(label, value, note, unit = "") {
  const node = el("article", "metric"); node.append(el("p", "metric-label", label));
  const big = el("div", "metric-value", value); if (unit) big.append(el("small", "", unit)); node.append(big, el("p", "metric-note", note)); return node;
}
function runButton(run) {
  const button = el("button", "run-link", "#" + run.id); button.type = "button";
  button.setAttribute("aria-label", "실행 " + run.id + " 상세 보기");
  button.addEventListener("click", () => showRun(run.id).catch(() => {})); return button;
}
function table(target, columns, rows, empty = "조건에 맞는 저장 기록이 없습니다.") {
  clear(target);
  if (!rows.length) { target.append(el("p", "empty", empty)); return; }
  const t = el("table"), thead = el("thead"), tr = el("tr"), tbody = el("tbody");
  for (const [key, label] of columns) { const th = el("th", "", label); th.scope = "col"; tr.append(th); }
  thead.append(tr);
  for (const row of rows) {
    const tr = el("tr");
    for (const [key, label, render] of columns) {
      const cell = el("td");
      if (render) { const value = render(row); cell.append(value instanceof Node ? value : document.createTextNode(textValue(value))); }
      else {
        const value = textValue(row[key]);
        if (value.length > 100) {
          cell.className = "long-cell";
          const details = el("details"), summary = el("summary", "", value.slice(0, 70) + "… 펼치기");
          details.append(summary, el("p", "", value)); cell.append(details);
        } else { cell.textContent = value; if (value.length > 30) cell.className = "long-cell"; }
      }
      tr.append(cell);
    }
    tbody.append(tr);
  }
  t.append(thead, tbody); target.append(t);
}
const runColumns = [
  ["id", "실행", runButton], ["started_at_ms", "시작 시각 (KST)", r => moment(r.started_at_ms)],
  ["data_type", "수집 종류"], ["status", "상태", r => pill(r.status)],
  ["records_fetched", "수집기 응답 수", r => number(r.records_fetched)],
  ["records_written", "기록 처리 수", r => number(r.records_written)],
  ["duration", "소요", r => r.completed_at_ms ? Math.max(0, (r.completed_at_ms - r.started_at_ms) / 1000).toFixed(1) + "초" : "종료 미기록"],
];
async function loadOverview() {
  const data = await api("/api/overview"); overviewLoaded = true;
  const categories = data.categories, counts = status => categories.filter(c => status.includes(c.state)).length;
  clear($("#metrics"));
  $("#metrics").append(metric("모니터링 수집 항목", number(categories.length), "종류별 마지막 실행 기준", "개"),
    metric("마지막 실행 완료", number(counts(["completed"])), "전체 데이터 검증 완료와는 다릅니다", "개"),
    metric("실패 · 지연 의심", number(counts(["failed", "partial", "stale", "long_running"])), "수집 이력에서 확인이 필요한 항목", "개"),
    metric("실행 중 · 이력 없음", number(counts(["running", "unknown"])), "이력 없음은 예약 미설정을 뜻하지 않습니다", "개"));
  $("#checked-at").textContent = "조회 " + isoMoment(data.checked_at);
  clear($("#status-grid"));
  for (const c of categories) {
    const card = el("article", "status-card"), top = el("div", "card-top");
    top.append(el("h3", "", c.name), pill(c.state)); card.append(top);
    card.append(el("span", "card-time", c.latest ? moment(c.latest.started_at_ms, true) : "실행 기록 없음"));
    const count = el("p", "card-count");
    if (c.latest) {
      count.append(document.createTextNode("응답 " + number(c.latest.records_fetched) + " · 처리 " + number(c.latest.records_written) + " · "), runButton(c.latest));
    } else count.textContent = "DB에 이 종류의 실행 이력이 없습니다.";
    card.append(count);
    if (c.empty_response) card.append(el("p", "card-warning", "빈 응답 · 데이터가 없다고 확정하지 않습니다."));
    if (c.latest_success && c.latest_success.id !== c.latest?.id) card.append(el("p", "card-warning", "마지막 성공 " + moment(c.latest_success.started_at_ms, true)));
    card.append(el("p", "card-schedule", c.schedule)); $("#status-grid").append(card);
  }
  table($("#recent-table"), runColumns, data.recent);
  notes($("#overview-notes"), data.notes);
  const typeSelect = $("#history-type"), current = typeSelect.value;
  clear(typeSelect); const all = el("option", "", "전체"); all.value = ""; typeSelect.append(all);
  data.data_types.forEach(type => { const option = el("option", "", type); option.value = type; typeSelect.append(option); }); typeSelect.value = current;
  loaded.add("overview");
}
function formParams(id) { return Object.fromEntries(new FormData($(id)).entries()); }
async function loadHistory(append = false) {
  const params = formParams("#history-form"); if (append && nextCursor) params.before_id = nextCursor;
  const data = await api("/api/runs", params);
  historyRows = append ? historyRows.concat(data.rows) : data.rows;
  nextCursor = data.next_cursor;
  table($("#history-results"), runColumns, historyRows);
  $("#more-runs").hidden = !data.has_more;
  $("#history-count").textContent = number(historyRows.length) + "건 표시";
  loaded.add("history");
}
async function showRun(id) {
  const data = await api("/api/runs/" + encodeURIComponent(id));
  $("#run-title").textContent = "실행 #" + data.run.id;
  clear($("#run-content")); const grid = el("dl", "detail-grid"), r = data.run;
  const fields = [["수집 종류", r.data_type], ["원천", r.source], ["상태", stateLabels[r.status]], ["시작 (KST)", moment(r.started_at_ms)], ["종료 (KST)", moment(r.completed_at_ms)], ["응답 / 기록 처리", number(r.records_fetched) + " / " + number(r.records_written)]];
  fields.forEach(([name, value]) => { const div = el("div"); div.append(el("dt", "", name), el("dd", "", value)); grid.append(div); });
  $("#run-content").append(grid);
  if (r.has_error) $("#run-content").append(el("p", "notice", r.error_note));
  $("#run-content").append(el("h3", "detail-heading", "저장된 원문 응답 근거 (최대 20개)"));
  const wrap = el("div", "table-wrap");
  table(wrap, [["id", "원문 ID"], ["endpoint", "API 경로"], ["operation", "작업"], ["retrieved_at_ms", "수신 (KST)", d => moment(d.retrieved_at_ms)], ["http_status_code", "HTTP"], ["response_bytes", "크기(bytes)"], ["sha256", "SHA-256"]], data.documents,
    "이 실행에 직접 연결된 원문 문서가 없습니다. 상위 실행이면 하위 종류의 이력을 확인하세요.");
  $("#run-content").append(wrap);
  if (data.documents_truncated) $("#run-content").append(el("p", "hint", "추가 원문이 있습니다. 최근 20개만 표시했습니다."));
  $("#run-dialog").showModal();
}
async function findHorse() {
  const query = $("#horse-query").value.trim();
  if (query.length < 2) { $("#horse-options").textContent = "말 이름 앞부분 또는 공식 마번을 2자 이상 입력하세요."; return; }
  const data = await api("/api/horses", {q: query}); clear($("#horse-options"));
  data.rows.forEach(horse => {
    const button = el("button", "horse-option", horse.name_ko + " · " + horse.kra_horse_id + (horse.is_active ? " · 현역" : " · 비현역/미확인")); button.type = "button";
    button.addEventListener("click", () => { $("#horse-id").value = horse.id; $("#horse-query").value = horse.name_ko; $("#selected-horse").textContent = "선택: " + horse.name_ko + " / 공식 마번 " + horse.kra_horse_id; clear($("#horse-options")); });
    $("#horse-options").append(button);
  });
  if (!data.rows.length) $("#horse-options").append(el("p", "hint", "검색 결과가 없습니다. 이름 앞부분이나 공식 마번을 확인하세요."));
  if (data.has_more) $("#horse-options").append(el("p", "hint", "20두만 표시했습니다. 더 구체적인 이름을 입력하세요."));
}
async function loadData() {
  const data = await api("/api/data", formParams("#search-form"));
  const keys = data.rows.length ? Object.keys(data.rows[0]) : [];
  table($("#data-results"), keys.map(key => [key, labels[key] || key]), data.rows);
  notes($("#search-notes"), ["조회 " + data.rows.length + "행" + (data.has_more ? " · 100행을 초과합니다. 날짜·경주·말 조건을 좁혀 주세요." : ""), ...data.notes]);
}
async function loadIssues() {
  const data = await api("/api/issues");
  clear($("#issue-metrics"));
  $("#issue-metrics").append(metric("관계 대조한 완료 경주", number(data.checked_races), "최근 14일 · 오늘과 어제 제외", "경주"),
    metric("범위 내 누락 의심", number(data.issue_count_in_scope), "확정 누락 아님 · 목록 최대 200행", "건"),
    metric("검사 시작일", data.start.slice(5), data.start), metric("검사 종료일", data.end.slice(5), data.end));
  $("#issues-time").textContent = isoMoment(data.checked_at);
  const issueLabels = {entries: "출전행", results: "경주 결과", groups: "통과조", sections: "구간기록", stewards: "심판리포트"};
  table($("#issue-results"), [["date", "경주일"], ["meet", "경마장"], ["race_no", "경주"], ["kind", "확인 항목", r => issueLabels[r.kind] || r.kind], ["horse", "말 이름"], ["detail", "확인 사유"], ["inspect", "조회", r => {
    const button = el("button", "run-link", "저장값 보기");
    button.addEventListener("click", () => {
      const f = $("#search-form"); f.elements.start.value = r.date; f.elements.end.value = r.date; f.elements.meet.value = r.meet_code; f.elements.race_no.value = r.race_no;
      f.elements.kind.value = r.kind === "results" || r.kind === "entries" ? "entries" : r.kind;
      clearHorse(); navigate("search"); loadData().catch(() => {});
    }); return button;
  }]], data.issues, "이번 범위·검사 규칙에서 누락 의심을 찾지 못했습니다. 전체 원천 대조 완료를 의미하지 않습니다.");
  notes($("#issue-notes"), data.notes.concat(data.race_scope_truncated ? ["경주 범위가 500경주를 초과해 일부만 검사했습니다."] : [], data.issues_truncated ? ["의심 목록 중 200행만 표시했습니다."] : []));
  loaded.add("issues");
}
function clearHorse() { $("#horse-id").value = ""; $("#horse-query").value = ""; $("#selected-horse").textContent = "선택한 말 없음 · 경주 관련 데이터는 말 선택 없이도 조회할 수 있습니다."; clear($("#horse-options")); }
function navigate(next) {
  if (!titles[next]) return;
  view = next; const [name, title, subtitle] = titles[next];
  $("#breadcrumb").textContent = name; $("#page-title").textContent = title; $("#page-subtitle").textContent = subtitle;
  document.querySelectorAll(".view").forEach(node => node.hidden = node.id !== "view-" + next);
  document.querySelectorAll(".nav-item").forEach(node => { node.classList.toggle("active", node.dataset.view === next); if (node.dataset.view === next) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current"); });
  $("#error").hidden = true;
  if (!loaded.has(next)) ({overview: loadOverview, history: loadHistory, issues: loadIssues}[next] || (() => Promise.resolve()))().catch(() => {});
}
const dateString = offset => { const d = new Date(Date.now() + 9 * 3600000 + offset * 86400000); return d.toISOString().slice(0, 10); };
for (const form of [$("#history-form"), $("#search-form")]) { form.elements.start.value = dateString(-7); form.elements.end.value = dateString(0); }
document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.view)));
$("#refresh").addEventListener("click", () => ({overview: loadOverview, history: () => loadHistory(false), search: loadData, issues: loadIssues}[view])().catch(() => {}));
$("#history-form").addEventListener("submit", e => { e.preventDefault(); loadHistory(false).catch(() => {}); });
$("#search-form").addEventListener("submit", e => { e.preventDefault(); loadData().catch(() => {}); });
$("#more-runs").addEventListener("click", () => loadHistory(true).catch(() => {}));
$("#find-horse").addEventListener("click", () => findHorse().catch(() => {}));
$("#horse-query").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); findHorse().catch(() => {}); } });
$("#horse-query").addEventListener("input", () => { if ($("#horse-id").value) { $("#horse-id").value = ""; $("#selected-horse").textContent = "검색어를 변경했습니다. 말을 다시 선택하세요."; } });
$("#clear-horse").addEventListener("click", clearHorse);
$("#close-dialog").addEventListener("click", () => $("#run-dialog").close());
loadOverview().catch(() => {});
