"""Build a standalone, read-only operations page from the project's Markdown guides.

No credentials, network, database, job invocation or runtime logs are read.
Only the allowlisted documentation and the page template are input files.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OPS_DOC = "DATA_COLLECTION_AUTOMATION_OPERATIONS_2026-10-05.md"
DOCS = (
    OPS_DOC,
    "LOCAL_REFERENCE_DATA_AUTOMATION_2026-10-07.md",
    "KRA_DATA_REFRESH_SCHEDULE_AND_CLOUD_JOBS_PLAN_2026-10-01.md",
    "LOCAL_RACE_DAY_COLLECTION_AND_DISCORD_HANDOFF_2026-10-02.md",
    "LOCAL_POST_RACE_AUTOMATION_2026-10-03.md",
    "CANONICAL_POST_RACE_REFRESH_2026-10-07.md",
    "HORSE_PROFILE_MEDICAL_REFRESH_2026-10-07.md",
    "KRA_APPROVED_42_API_CATALOG_2026-09-30.md",
    "KRA_API_USAGE_INVENTORY_2026-09-30.md",
)
API = {
    "API154": ("/API154/racePlan", "경주계획"),
    "API26_2": ("/API26_2/entrySheet_2", "출전마·관계자·경주별 레이팅"),
    "API78": ("/API78/chulmainfo", "출발번호·장구 증감 스냅샷"),
    "API18_1": ("/API18_1/dailyTraining_1", "일반 조교"),
    "API22_1": ("/API22_1/startingTranning_1", "출발 조교"),
    "API216": ("/API216/SwimTr", "수영 훈련"),
    "hilldriving": ("/hilldriving/gethilldriving", "언덕 훈련"),
    "API25_1": ("/API25_1/entryHorseWeightInfo_1", "당일 마체중·증감"),
    "API10_1": ("/API10_1/jockeyChangeInfo_1", "기수·부담중량 변경"),
    "API9_1": ("/API9_1/raceHorseCancelInfo_1", "출전 취소"),
    "API155": ("/API155/raceResult", "경주 결과"),
    "API156": ("/API156/raceRsutDtl", "상세 결과"),
    "API301": ("/API301/Dividend_rate_total", "7승식 확정배당"),
    "API16_1": ("/API16_1/raceHorseClinic_1", "진료·진단명 원문"),
    "API8_2": ("/API8_2/raceHorseInfo_2", "현역마 기본정보"),
    "API308": ("/API308/trainerInfo", "조교사 소속·등록 상태"),
    "API20_1": ("/API20_1/ridingTestResult_1", "주행심사 결과·공식 ID"),
    "API215": ("/API215/JudgeReport", "심판리포트"),
    "API4_3": ("/API4_3/raceResult_3", "말별 구간시간·통과순위"),
    "API303": ("/API303/corner_rank", "경주 통과조·주로빠르기"),
    "API6_1": ("/API6_1/raceDetailSectionRecord_1", "구간·통과조 독립 대조"),
}
# Schedules, scope, registration names and documented evidence come from OPS_DOC.
# This small mapping adds navigation, command recipes and behavior explanations.
META = {
    "주간 출마표": dict(
        id="cloud-cards",
        place="cloud",
        category="출마표",
        apis=["API154", "API26_2", "API78"],
        manual=(
            "gcloud run jobs execute mapilog-weekly-entry-cards "
            "--project=mapilog-509017 --region=asia-northeast1 --async"
        ),
        check=(
            "gcloud run jobs executions list --job=mapilog-weekly-entry-cards "
            "--project=mapilog-509017 --region=asia-northeast1 --limit=5"
        ),
        log="Google Cloud Logging → mapilog-weekly-entry-cards",
        alert="완료·변경 없음·수집 실패 요약",
        evidence="10/5 문서의 Scheduler ENABLED 확인 기록",
        rule=(
            "수요일부터 다음 화요일의 미래 경주를 확인합니다. "
            "이미 시작한 경주의 당일 값을 초기 출마표로 되돌리지 않습니다."
        ),
    ),
    "조기 출마표": dict(
        id="local-cards",
        place="local",
        category="출마표",
        apis=["API154", "API26_2", "API78"],
        mode="cards",
        alert="기존 주간 출마표 알림 사용",
        evidence="10/7 16:10 달력 예약 실행 · 종료 0 · Discord 확인",
        rule=(
            "Google 출마표 예약을 유지하면서 조기 공개분을 추가 조회합니다. "
            "같은 fingerprint와 PostgreSQL 잠금으로 중복을 방지합니다."
        ),
    ),
    "매일 조교": dict(
        id="cloud-training",
        place="cloud",
        category="훈련",
        apis=["API18_1", "API22_1", "API216", "hilldriving"],
        manual=(
            "gcloud run jobs execute mapilog-daily-training "
            "--project=mapilog-509017 --region=asia-northeast1 --async"
        ),
        check=(
            "gcloud run jobs executions list --job=mapilog-daily-training "
            "--project=mapilog-509017 --region=asia-northeast1 --limit=5"
        ),
        log="Google Cloud Logging → mapilog-daily-training",
        alert="종류별 집계·실패 상세. 언덕 중복 제외 건수와 원본 이력 행수를 구분합니다.",
        evidence="10/17 제주 API22 전환 · 152행 보완 · 실제 50작업 오류 0 · Discord 확인",
        rule=(
            "최근 7일을 다시 조회합니다. 제주 출발조교도 API22로 수집하며 "
            "하루 여러 행을 occurrence_no로 보존합니다. 홈페이지 확정일은 API로 덮어쓰지 않고 "
            "빈 응답으로 기존 훈련을 지우지 않습니다. 언덕 집계는 DB의 "
            "horse_hill_training_current를 사용합니다(원본 이력 보존)."
        ),
    ),
    "당일 변경과 결과": dict(
        id="live",
        place="local",
        category="경주 당일",
        apis=["API25_1", "API10_1", "API9_1", "API155", "API156"],
        manual=".venv/bin/python -m horse_racing.jobs.local_race_day --apply",
        check=".venv/bin/python scripts/manage-local-race-day.py status",
        log="local-live-race-day",
        alert="변경·새 완료 경주·오류·복구만. 동일 오류는 30분 제한",
        evidence="10/5 복구 후 반복 정상 종료 기록",
        rule=(
            "다음 경주 하나가 아니라 오늘 출마표가 있는 전체 경마장을 조회합니다. "
            "첫 경주 1시간 전~마지막 경주 2시간 후, 08:00~22:00 미만에만 수집합니다. "
            "예정 시각이 없으면 09:00~21:00 미만을 사용합니다. "
            "완료 경마장은 10분 재확인으로 줄입니다."
        ),
    ),
    "확정배당": dict(
        id="dividends",
        place="local",
        category="경주 후",
        apis=["API301"],
        manual=".venv/bin/python -m horse_racing.jobs.local_post_race --mode dividends --apply",
        check=".venv/bin/python scripts/manage-local-post-race.py status",
        log="local-closing-dividends",
        alert="신규·정정·오류만. 변경 없음·발표 대기는 조용히 처리",
        evidence="10/5 실제 적재·알림 검증 기록",
        rule=(
            "완료가 검증된 경주의 확정배당만 저장합니다. "
            "경주 시간 창과 09:00~22:00 미만 제한을 함께 적용합니다. "
            "경주 전 실시간 변동 배당은 아닙니다."
        ),
    ),
    "결과 정정과 배당 보완": dict(
        id="repair",
        place="local",
        category="경주 후",
        apis=["API155", "API156", "API301"],
        manual=".venv/bin/python -m horse_racing.jobs.local_post_race --mode repair --apply",
        check=".venv/bin/python scripts/manage-local-post-race.py status",
        log="local-post-race-repair",
        alert="변경이 없어도 완료·대기·오류 집계",
        evidence="10/12 LaunchAgent 재검증 22808 · 18단계 완료 · 종료 0 · 알림 성공",
        rule=(
            "기존 출마표에 연결된 최근 7일의 결과·배당을 보완합니다. "
            "출마표가 없는 경주는 생성하지 않습니다. 7일보다 늦은 정정은 수동 검증이 필요합니다."
        ),
    ),
    "진료와 진단명 연결": dict(
        id="medical",
        place="local",
        category="기본정보",
        apis=["API16_1"],
        mode="medical",
        alert="완료·부분 완료·실패와 처리 건수",
        evidence="10/12 지난주 누락 739건 보완 · 2,701건 보존 · 연결 누락 0",
        rule=(
            "최근 14일을 재조회하고 저장 후 원천 자연키 누락을 확인합니다. "
            "진단명 원문과 두 슬롯을 유지하고 각각 고유 용어에 연결합니다. "
            "같은 자연키는 재사용합니다. 새 용어의 의학적 설명·위험도는 자동 확정하지 않습니다."
        ),
    ),
    "말 기본정보와 조교사": dict(
        id="profiles",
        place="local",
        category="기본정보",
        apis=["API8_2", "API308"],
        mode="profiles",
        alert="말·조교사 단계별 완료·부분 완료·실패",
        evidence="10/7 저장 경로 검증 · 말 4,025두 · 현역 조교사 88명",
        rule=(
            "18:40 예약은 매일 호출되지만 DB 일정의 주간 마지막 경주일일 때만 수집합니다. "
            "현역 목록의 부재만으로 은퇴 처리하지 않으며 "
            "조교사는 공식 API와 홈페이지를 대조합니다."
        ),
    ),
    "주행심사": dict(
        id="trials",
        place="local",
        category="심사",
        apis=["API20_1"],
        mode="trials",
        text=True,
        alert="검증 완료·API 공개 대기·지역별 오류·공식 ID 연결 집계",
        evidence="10/7 저장 경로 검증 · 10/1 공개 10심사·103두 · 연결 누락 0",
        rule=(
            "공식 Text와 API의 날짜·지역·출전번호·말·관계자·완주기록을 대조한 뒤 "
            "공식 ID로 연결합니다. API 정상 0건은 공개 대기로 남기고 "
            "날짜·지역별로 독립 처리합니다. "
            "이름만으로 동명이인을 병합하지 않습니다."
        ),
    ),
    "심판과 구간 및 통과기록": dict(
        id="canonical",
        place="local",
        category="경주 후",
        apis=["API215", "API4_3", "API303", "API6_1"],
        mode="canonical",
        text=True,
        alert="신규·정정·대기·오류 요약. 변경 없는 재조회도 실행 원장 기록",
        evidence="10/12 서울 구간 900·통과조 51행 추가 · 지난주 재대조 일치",
        rule=(
            "심판과 구간을 독립 단계로 처리합니다. 정정 전 값을 보존하고 저장 후 대조합니다. "
            "연간 원천 충돌·기존 행이 빠지는 응답은 자동 교체하지 않습니다. "
            "미제공 개별 순위는 추정하지 않습니다."
        ),
    ),
    "수집기 로그 정리": dict(
        id="logs",
        place="local",
        category="유지관리",
        apis=[],
        manual=".venv/bin/python -m horse_racing.jobs.local_log_rotation --apply",
        check=".venv/bin/python scripts/manage-local-log-rotation.py status",
        log="/Users/kimyongjin/Library/Logs/horse-racing/rotation-status.json",
        alert="Discord 없음. rotation-status.json 확인",
        evidence="기존 로그 정리 유지 · 복구 로그 포함 18개 허용 목록 테스트",
        rule=(
            "허용된 수집 로그 18개만 압축·검증한 뒤 내용을 비웁니다. 파일과 inode는 유지합니다. "
            "7일 초과 압축본만 삭제하며 DB·원문·연구 자료는 삭제하지 않습니다."
        ),
    ),
    "로컬 장애 복구": dict(
        id="recovery",
        place="local",
        category="유지관리",
        apis=[],
        manual=".venv/bin/python -m horse_racing.jobs.local_recovery --apply",
        check=".venv/bin/python scripts/manage-local-recovery.py status",
        log="local-recovery",
        alert="확실히 미전송된 알림만 별도 재확인. 도착 여부 불명은 재전송하지 않음",
        evidence="10/10 등록·기동 종료 0. 정상 상태에서 수집 실행 없음",
        rule=(
            "최근 DB 최초 연결 실패를 온라인 복구 후 작업별 최대 3회 재확인합니다. "
            "정상 완료·API 공개 대기·검증 불일치는 반복 적재하지 않습니다. "
            "노트북 전원·로그인·네트워크가 필요하며 강제 깨움 기능은 없습니다."
        ),
    ),
}
WEEKDAYS = {
    "월요일": 0,
    "화요일": 1,
    "수요일": 2,
    "목요일": 3,
    "금요일": 4,
    "토요일": 5,
    "일요일": 6,
}


def table_rows(markdown, heading):
    section = markdown.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    lines = [line for line in section.splitlines() if line.startswith("|")]
    if len(lines) < 3:
        raise ValueError("operations_table_missing")
    return [[value.strip() for value in line.strip("|").split("|")] for line in lines[2:]]


def schedule_events(value):
    if "분 간격" in value:
        return {"kind": "interval", "minutes": int(re.search(r"(\d+)분", value)[1]), "events": []}
    events, days, conditional = [], list(range(7)), False
    labels = "|".join([*WEEKDAYS, "매일", "주간 마지막 경주일"])
    for match in re.finditer(rf"(?:(?P<label>{labels})\s*)?(?P<time>\d{{1,2}}:\d{{2}})", value):
        label = match["label"]
        if label:
            conditional = label == "주간 마지막 경주일"
            days = [WEEKDAYS[label]] if label in WEEKDAYS else list(range(7))
        events.append(dict(time=match["time"].zfill(5), days=days.copy(), conditional=conditional))
    if not events:
        raise ValueError("schedule_could_not_be_parsed")
    return {"kind": "calendar", "events": events}


def markdown_blocks(markdown):
    """Parse a small safe Markdown subset into data, never executable HTML."""
    lines, blocks, i = markdown.splitlines(), [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            if i == len(lines):
                raise ValueError("unclosed_markdown_fence")
            blocks.append(dict(type="code", text="\n".join(code)))
            i += 1
        elif match := re.match(r"^(#{1,6}) (.*)", line):
            blocks.append(dict(type="heading", level=len(match[1]), text=match[2]))
            i += 1
        elif (
            line.startswith("|") and i + 1 < len(lines) and re.fullmatch(r"[| :\-]+", lines[i + 1])
        ):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([v.strip() for v in lines[i].strip("|").split("|")])
                i += 1
            blocks.append(dict(type="table", head=rows[0], rows=rows[2:]))
        elif re.match(r"^(- |\d+\. )", line):
            items = []
            while i < len(lines) and re.match(r"^(- |\d+\. )", lines[i]):
                items.append(re.sub(r"^(- |\d+\. )", "", lines[i]))
                i += 1
            blocks.append(dict(type="list", items=items))
        else:
            paragraph = [line]
            i += 1
            while (
                i < len(lines)
                and lines[i].strip()
                and not re.match(r"^(#|\||```|- |\d+\. )", lines[i])
            ):
                paragraph.append(lines[i])
                i += 1
            blocks.append(dict(type="paragraph", text="\n".join(paragraph)))
    return blocks


def payload():
    documents = []
    for name in DOCS:
        path = ROOT / "docs" / name
        markdown = path.read_text(encoding="utf-8")
        # Do not publish a credential accidentally pasted into an operational guide.
        validate_public_text(markdown)
        documents.append(
            dict(
                id=name,
                title=markdown.splitlines()[0].removeprefix("# "),
                sha256=hashlib.sha256(markdown.encode()).hexdigest(),
                blocks=markdown_blocks(markdown),
            )
        )
    markdown = (ROOT / "docs" / OPS_DOC).read_text(encoding="utf-8")
    rows = table_rows(markdown, "활성 예약 전체 목록")
    if len(rows) != len(META) or {r[0] for r in rows} != set(META):
        raise ValueError("job_registry_changed_review_metadata_mapping")
    jobs = []
    for name, runner, schedule, scope, confirmation in rows:
        meta = META[name].copy()
        mode = meta.get("mode")
        if mode:
            meta.update(
                manual=f".venv/bin/python -m horse_racing.jobs.local_catalog --mode {mode} --apply",
                check=f".venv/bin/python scripts/manage-local-catalog.py status --mode {mode}",
                log=f"local-catalog-{mode}",
            )
        jobs.append(
            dict(
                name=name,
                runner=runner,
                schedule=schedule,
                scope=scope,
                confirmation=confirmation,
                **meta,
                **schedule_events(schedule),
            )
        )
    pending = markdown.split("## 과거 예약과 아직 자동화하지 않은 항목\n", 1)[1].split("\n## ", 1)[
        0
    ]
    pending = [line[2:] for line in pending.splitlines() if line.startswith("- ")]
    basis = re.search(r"확인 기준은 (\d{4})년 (\d{1,2})월 (\d{1,2})일", markdown)
    if not basis:
        raise ValueError("document_basis_date_missing")
    return dict(
        asOf=f"{basis[1]}-{int(basis[2]):02d}-{int(basis[3]):02d}",
        generatedAt=datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        root=str(ROOT),
        jobs=jobs,
        documents=documents,
        apis=[dict(code=code, path=info[0], description=info[1]) for code, info in API.items()],
        pending=pending,
    )


def validate_public_text(value):
    """Reject recognizable credentials without echoing their contents."""
    patterns = (
        r"https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+",
        r"postgres(?:ql)?://[^\s:/]+:[^\s@]+@",
        r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}\b",
        r"\bsbp_[a-zA-Z0-9]{20,}\b",
    )
    if any(re.search(pattern, value) for pattern in patterns):
        raise ValueError("credential_like_text_in_allowlisted_document")


def safe_json(value):
    # JSON inside <script type=application/json> must not close the HTML script element.
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def main():
    template = ROOT / "operations/page.template.html"
    output = ROOT / "operations/index.html"
    if output.is_symlink() or template.resolve().parent != ROOT / "operations":
        raise ValueError("unsafe_operations_page_path")
    source = template.read_text(encoding="utf-8")
    if source.count("__OPERATIONS_DATA__") != 1:
        raise ValueError("operations_template_marker")
    result = source.replace("__OPERATIONS_DATA__", safe_json(payload()))
    output.write_text(result, encoding="utf-8")
    print(f"Built {output} ({len(result.encode()):,} bytes); no DB/network/job access")


if __name__ == "__main__":
    main()
