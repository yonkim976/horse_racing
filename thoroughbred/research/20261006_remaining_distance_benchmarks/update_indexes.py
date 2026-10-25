"""Append study links, preserving independent changes to the shared project indexes."""

# ruff: noqa: E501

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CENTRAL = HERE.parent / "conclusions"
DISTANCES = [1000, 1900, 2000, 2200, 2300]
RUN = HERE.name


def main():
    p = CENTRAL / "README.md"
    text = p.read_text()
    text = text.replace("서울·부산·영천 연구 23개와", "서울·부산·영천 연구 28개와")
    text = text.replace(
        "23개 연구와 결정 문서, 이전 연구의 원 경로", "28개 연구와 결정 문서, 이전 연구의 원 경로"
    )
    marker = "| [원 보고서 목록](SOURCES.md)"
    labels = [
        "실전1000m 20조합·130행과 주행심사 구분",
        "1900m 서울 한 경주 잠정치·부산 최근 참조 없음",
        "2000m 35조합·225행과 부산 국OPEN 한 날짜",
        "부산2200m 두 경주 잠정치·시간순 검증 불가·포화 부재",
        "서울2300m 6일 참조·불량 부재",
    ]
    if "17_BENCHMARK1000.md" not in text:
        rows = (
            "\n".join(
                f"| [{d}m 등급·상태 기준]({17 + i:02d}_BENCHMARK{d}.md) | {labels[i]} |"
                for i, d in enumerate(DISTANCES)
            )
            + "\n"
        )
        text = text.replace(marker, rows + marker)
        anchor = "\n\n## 현재 보정 상태"
        findings = [
            "실전1000m20조합130행, 주행심사와 구분·숨긴 조합 개선 미확인 | 연구용 기준·부산 혼4 잠정, 운영 미반영",
            "서울2등급10기록 한 경주·부산 최근 참조 없음 | 잠정 기준·보정 효과 미확정",
            "서울/부산35조합225행, 평균 오차 소폭 감소·부산 국OPEN 한 날짜 | 연구용 기준·부산 숨긴 조합 개선 미확인",
            "부산8조합56행, 최근두 경주·포화 부재 | 잠정 기준·시간순 검증 불가",
            "서울8조합48행, 최근6일·불량 부재 | 잠정 기준·희소 검증",
        ]
        rows = "\n" + "\n".join(
            f"| {24 + i} | {d}m 등급·주로상태 기준 | {findings[i]} |"
            for i, d in enumerate(DISTANCES)
        )
        text = text.replace(anchor, rows + anchor)
        text += f"\n\n## 남은 실전 거리 기준 완료\n\n2026-10-06 [1000·1900·2000·2200·2300m 통합 연구](../{RUN}/README.md)를 추가해 현재28개 연구를 모았다. 동결 모집단의 미완료5거리이며 기존1200~1800m 기준을 재실행하지 않았다. 최근1,973기록에서76개 상태 조합·전체/구간489행을 만들었고 참조 없는324조합은 null이다.1900 서울·2200 부산의 한두 경주,2300 서울의6일과 지원 없는2200 포화·2300 불량을 구분한다.\n"
    p.write_text(text)
    p = CENTRAL / "SOURCES.md"
    text = p.read_text().replace("거리별 기준23개 연구", "거리별 기준28개 연구")
    if f"../{RUN}/1000/README.md" not in text:
        for i, d in enumerate(DISTANCES):
            text += f"\n## {d}m 남은 거리 기록 기준\n\n- {24 + i}. [{labels[i]}](../{RUN}/{d}/README.md)\n- 이 폴더의 결론: [{d}m 기준과 한계]({17 + i:02d}_BENCHMARK{d}.md)\n- [공통 원천](../{RUN}/SOURCES.md), [독립 검증](../{RUN}/{d}/outputs/verification.json), [전체 작업 용량](../{RUN}/outputs/artifact_inventory.json)\n"
    p.write_text(text)
    updates = {
        ROOT
        / "thoroughbred/README.md": f"\n\n[실전1000·1900·2000·2200·2300m 기록 기준](research/{RUN}/README.md): 남은5거리에서76조합489행을 별도 계산했다. 최근 참조 없는 등급과 전기간 상태 지원 없는2200 포화·2300 불량은 null이며1900/2200/2300은 잠정이다. [중앙 결론](research/conclusions/README.md), 게시 준비 자료와 전체 용량을 보존했다.\n",
        HERE.parent
        / "README.md": f"\n\n[남은 실전1000·1900·2000·2200·2300m 기록 기준]({RUN}/README.md): 최종16,206기록·최근1,973기록에서76조합489행을 독립 계산했다.1000은 주행심사와 구분했고324미지원 조합은 null이다.1000/2000의 시간순 평균 오차는 소폭 감소했으나 숨긴 조합 복원은 개선되지 않았다.1900/2200/2300의 희소 참조와2200 검증 불가·포화 부재,2300 불량 부재를 명시했다. [중앙 결론](conclusions/README.md)에5개 연구를 추가했다.\n",
        HERE.parent
        / "20261004_website_research_review/README.md": f"\n\n## 남은5거리 게시 준비 자료 추가\n\n2026-10-06 [통합 연구](../{RUN}/README.md)의1000·1900·2000·2200·2300m 게시요약과 거리별 web_benchmarks JSON을 추가했다.76조합489행과324미지원 조합을 구분한다.1000m는 실전으로 주행심사와 분리하고1900 부산은 최근기준 없음,1900 서울/2200 부산은 한두 경주,2300 서울은6일의 잠정치로 표시해야 한다.2200 포화·2300 불량은 시간 null이며 한 날짜의 신뢰구간 부재도 보존한다.1000/2000 평균 오차 소폭 감소를 우승 예측 개선으로 표현하지 않으며 숨긴 조합 복원의 개선도 확인되지 않았다. 실제 웹 구현·배포·운영 적용은 변경하지 않았다.\n",
    }
    account_path = HERE / "outputs/shared_edit_accounting.json"
    account = json.loads(account_path.read_text()) if account_path.exists() else {}
    for p, addition in updates.items():
        text = p.read_text()
        name = str(p.relative_to(ROOT))
        if f"{RUN}/README.md" not in text:
            before = p.stat().st_size
            p.write_text(text + addition)
            account[name] = p.stat().st_size - before
        assert name in account, f"Missing measured task append for {name}"
    account_path.write_text(json.dumps(account, ensure_ascii=False, indent=2) + "\n")
    print("Shared links appended; measured task-owned index growth preserved")


if __name__ == "__main__":
    main()
