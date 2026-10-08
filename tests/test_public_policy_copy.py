from pathlib import Path

from fastapi.testclient import TestClient

from horse_racing.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "src" / "horse_racing" / "web" / "templates"


def test_privacy_copy_covers_purpose_data_retention_choices_and_requests() -> None:
    policy = (TEMPLATES / "public_info.html").read_text(encoding="utf-8")

    for expected in (
        "수집 항목과 이용 목적",
        "IP 주소, 요청 URL",
        "일반 접속 기록:</strong> 30일 보관한 뒤",
        "관리자·시스템 보안 기록:</strong> 400일 보관",
        "비활성 정보는 약 2분 기준으로 정리되도록 운영합니다",
        "실제 정리 시점은 이용 상황에 따라 달라질 수 있습니다",
        "수신일부터 7일간 보관",
        "처리 완료 후 7일 이내 파기",
        "개인정보 열람·정정·삭제·처리정지 요청",
        "쿠키를 차단하거나 삭제",
        "접속 기록 관리, 이메일 수신, 글꼴 표시를 위해 Google의 서비스와 jsDelivr",
        "Google과 jsDelivr가 제공하는 글꼴 서비스",
        "Google의 이메일 서비스로 전달됩니다",
        "일본 소재의 서비스 운영 시설에서 처리될 수 있습니다",
        "처리·보관 국가와 국외 처리 조건은 현재 확인되지 않았습니다",
    ):
        assert expected in policy

    for internal_name in (
        "Cloud Run",
        "Google Cloud",
        "Google Cloud Logging",
        "Gmail",
        "Google Fonts",
        "_Default",
        "_Required",
        "버킷",
        "global",
        "리전",
        "프로세스 메모리",
    ):
        assert internal_name not in policy


def test_public_policy_copy_does_not_show_internal_draft_or_unavailable_features() -> None:
    policy = (TEMPLATES / "public_info.html").read_text(encoding="utf-8")
    footer = (TEMPLATES / "_site_footer.html").read_text(encoding="utf-8")

    assert "최종 개정일: 2026년 10월 3일" in policy
    assert "게시 전 검토본" not in policy
    assert "실제 게시일이나 운영 반영일이 아닙니다" not in policy
    assert "자동 삭제 기능은 구현되어 있지 않습니다" not in policy
    assert "Google Forms" not in policy
    assert "href=\"/feedback\"" not in footer
    assert 'href="/guide"' in footer
    assert 'href="/privacy"' in footer
    assert "마필로그 운영자" in footer


def test_mobile_prediction_copy_keeps_probability_and_history_meanings_clear() -> None:
    guide = (TEMPLATES / "mobile" / "_prediction_guide.html").read_text(
        encoding="utf-8"
    )

    assert "3위 안 입상 확률" in guide
    assert "약 300%" in guide
    assert "우승 확률이나 정확히 2·3위에 들 확률은 아닙니다" in guide
    assert "예측값 없음" in guide
    assert "계산된 확률이 0%" in guide
    assert "후착후보" in guide
    assert "실제 과거 경주의 착순" in guide
    assert "과거 결과가 미래 결과를 확정하지는 않습니다" in guide


def test_field_copy_and_checklist_cover_demo_revisit_and_qr_gate() -> None:
    field_notes = (
        ROOT / "docs" / "MAPILOG_BETA_PUBLIC_COPY_2026-10-03.txt"
    ).read_text(encoding="utf-8")

    for expected in (
        "[20초 소개]",
        "[3분 시연 순서]",
        "[현장 질문 하나]",
        "[다음 주 재방문 문구]",
        "[QR 안내판 문구]",
        "https://mapilog.xyz/ 는 404 상태",
        "QR을 만들거나 인쇄하지 않습니다",
        "[Google Form 도입 시에만 사용할 안내 초안]",
        "Gmail 받은편지함과 보낸편지함에서 삭제한 뒤 휴지통도 비웁니다",
        "국외 처리 조건은 현재 확인되지 않았습니다",
    ):
        assert expected in field_notes


def test_final_public_pages_render_without_database_access(monkeypatch) -> None:
    monkeypatch.delenv("MAPILOG_OPERATOR_NAME", raising=False)
    monkeypatch.delenv("MAPILOG_CONTACT_EMAIL", raising=False)

    def no_database_access():
        raise AssertionError("guide and privacy pages must not open a database session")

    with TestClient(create_app(session_factory=no_database_access)) as client:
        guide = client.get("/guide")
        mobile_guide = client.get(
            "/guide",
            headers={"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"},
        )
        privacy = client.get("/privacy")

    assert guide.status_code == mobile_guide.status_code == privacy.status_code == 200
    assert "3위 안에 들 확률" in guide.text
    assert "개인정보처리방침" in privacy.text
    assert 'href="mailto:mapilog@mapilog.xyz"' in privacy.text
    assert "게시 전 검토본" not in privacy.text
