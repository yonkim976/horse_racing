from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import func, select
from test_race_day import migrated_session

from horse_racing.collectors.kra_text import KraTextClient
from horse_racing.db.models import (
    Horse,
    Jockey,
    RunningTrial,
    RunningTrialResult,
    SourceDocument,
    Trainer,
)
from horse_racing.parsers.running_trials import parse_running_trial_report
from horse_racing.services.running_trials import ingest_running_trials

SEOUL_REPORT = """
제목 : 26년 8월27일 (목)   제33차 주행심사성적  제 1경주

날    씨 : 맑음                             주로상태 : 양호 (8%)
--------------------------------------------------------------------------------
   순위  마번  마    명         산지  성  연령   부  담  기수명    조교사명
--------------------------------------------------------------------------------
     1     3   송당퍼스트        한   암    2    53+2.0  조상범     이강서
    92     6   템프테이션        한   암    2    53      조재로     이관호
--------------------------------------------------------------------------------
   순위 마번  마    명        마체중 기  록  도착차    판정 불합격사유   검사사유
--------------------------------------------------------------------------------
     1   3   송당퍼스트        471  1:02.6            합              주행미합(신)
    92   6   템프테이션        456           주행중지 불   진입불량   주행미합(신)
--------------------------------------------------------------------------------
   순위  마번    G-3Ｆ    S-1F   ３코너   ４코너     G-1F  S1F-1C-2C-3C-4C-G1F
--------------------------------------------------------------------------------
     1     3     37.2   0:14.6   0:14.6   0:31.6     13.0   6-  -  - 6- 4- 1
    92     6                                               11-  -  -11-11-11
--------------------------------------------------------------------------------
""".strip()


BUSAN_REPORT = """
제목 : 26년 8월27일 (목)   제33차 주행심사성적  제 1경주

날    씨 : 흐림                               주로상태 : 건조 (2%)
--------------------------------------------------------------------------------
   순위  마번  마    명         산지  성  연령   부  담  기수명    조교사명
--------------------------------------------------------------------------------
     1     9   용비짱            한   거    3    55      김어수     구민성
--------------------------------------------------------------------------------
   순위 마번  마    명        마체중 기  록  도착차    판정 불합격사유   검사사유
--------------------------------------------------------------------------------
     1    9   용비짱            493  1:01.8            합             주행지정(재)
--------------------------------------------------------------------------------
   순위  마번   S1F-G3F-G2F-G1F  S1-F    400     G400     G-3F     G-1F
--------------------------------------------------------------------------------
     1     9     2- 2- 2- 1      13.9    23.3    24.6     0:36.5   0:12.5
--------------------------------------------------------------------------------
""".strip()


def test_parse_running_trial_report_handles_status_and_sections() -> None:
    trial = parse_running_trial_report(SEOUL_REPORT, meet=1)[0]
    assert trial.trial_date == date(2026, 8, 27)
    assert trial.distance_m == 1000
    assert trial.track_moisture_percent == 8.0
    assert len(trial.results) == 2

    winner = trial.results[0]
    assert winner.horse_name == "송당퍼스트"
    assert winner.finish_time_ms == 62_600
    assert winner.g3f_ms == 37_200
    assert winner.passing_order_raw == "6-  -  - 6- 4- 1"

    stopped = trial.results[1]
    assert stopped.finish_position is None
    assert stopped.finish_time_ms is None
    assert stopped.margin_text == "주행중지"
    assert stopped.failure_reason == "진입불량"


def test_parse_busan_section_layout() -> None:
    result = parse_running_trial_report(BUSAN_REPORT, meet=3)[0].results[0]
    assert result.s1f_ms == 13_900
    assert result.section_400_ms == 23_300
    assert result.final_400_ms == 24_600
    assert result.g3f_ms == 36_500
    assert result.g1f_ms == 12_500
    assert result.passing_order_raw == "2- 2- 2- 1"


def test_parse_cancelled_trial_judgement() -> None:
    cancelled = SEOUL_REPORT.replace(
        "92   6   템프테이션        456           주행중지 불   진입불량   주행미합(신)",
        "99   6   템프테이션          0                    심   악천후(농무) 주행미합(신)",
    )
    result = parse_running_trial_report(cancelled, meet=1)[0].results[1]
    assert result.finish_position is None
    assert result.body_weight_kg is None
    assert result.judgement == "심"
    assert result.failure_reason == "악천후(농무)"


def test_ingest_running_trials_links_existing_entities(tmp_path: Path) -> None:
    report_bytes = SEOUL_REPORT.encode("cp949")
    filename = "20260827dacom23.rpt"
    remote_path = f"chollian/seoul/jungbo/ap-check-rslt/{filename}"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("textDataList.do"):
            if b"pageIndex=1" not in request.content:
                return httpx.Response(200, content=b"<html></html>")
            html = (
                '<a href="/dbdata/fileDownLoad.do?fn='
                f'{remote_path}&meet=1">{filename}</a>'
            )
            return httpx.Response(200, content=html.encode("cp949"))
        if request.url.path.endswith("fileDownLoad.do"):
            return httpx.Response(
                200,
                content=report_bytes,
                headers={"content-type": "application/octet-stream"},
            )
        return httpx.Response(404)

    session_factory = migrated_session(tmp_path)
    with session_factory() as session:
        session.add_all(
            [
                Horse(kra_horse_id="0056250", name_ko="송당퍼스트", meet_code=1),
                Jockey(kra_jockey_id="080001", name_ko="조상범"),
                Trainer(kra_trainer_id="070001", name_ko="이강서"),
            ]
        )
        session.commit()
        with KraTextClient(transport=httpx.MockTransport(handler)) as client:
            summary = ingest_running_trials(
                session,
                client,
                start_date=date(2026, 8, 27),
                end_date=date(2026, 8, 27),
                meets=[1],
                raw_data_dir=tmp_path / "raw",
            )

        assert summary.files == 1
        assert summary.trials == 1
        assert summary.records_written == 2
        assert summary.horses_linked == 1
        assert summary.horses_unresolved == 1
        assert session.scalar(select(func.count()).select_from(RunningTrial)) == 1
        assert session.scalar(select(func.count()).select_from(RunningTrialResult)) == 2
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 1

        winner = session.scalar(
            select(RunningTrialResult).where(
                RunningTrialResult.horse_name_raw == "송당퍼스트"
            )
        )
        assert winner is not None
        assert winner.horse_id is not None
        assert winner.jockey_id is not None
        assert winner.trainer_id is not None
        assert winner.finish_time_ms == 62_600
        assert Path(session.scalar(select(SourceDocument.local_path))).exists()
