"""FEATURE_CATALOG.md 자동 생성기."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from horse_racing.analysis.features import all_feature_specs

HEADER = """# Feature 카탈로그 (자동 생성)

이 문서는 `horse-racing write-feature-catalog`가 feature 레지스트리에서 생성한다.
직접 수정하지 말고 각 그룹 모듈(`src/horse_racing/analysis/features/`)의
`FeatureSpec`을 수정한 뒤 재생성한다. 설계 배경은
[MODELING_ROADMAP](MODELING_ROADMAP.md) §4를 본다.

공통 원칙: 모든 feature는 예측 시점(`prediction_at`) 이전에 공개된 값만 사용한다.
과거 이력은 예측 대상 경주일 **이전** 데이터만 집계하며, 당일 이벤트(훈련·진료)는
공개 시점이 불확실해 보수적으로 제외한다 (T3 실측 후 완화 검토).
"""


def render_catalog() -> str:
    specs = all_feature_specs()
    lines = [HEADER]
    lines.append(f"생성일: {date.today().isoformat()} · 등록 feature: {len(specs)}개\n")

    current_group: str | None = None
    for spec in specs:
        if spec.group != current_group:
            current_group = spec.group
            lines.append(f"\n## {current_group}\n")
            lines.append("| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |")
            lines.append("|---|---|---|---|---|---|")
        lines.append(
            f"| `{spec.name}` | {spec.description} | {spec.source} "
            f"| {spec.lookback} | {spec.null_policy} | {spec.leakage_note} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_feature_catalog(path: Path) -> int:
    """카탈로그를 기록하고 feature 개수를 반환한다."""
    path.write_text(render_catalog(), encoding="utf-8")
    return len(all_feature_specs())
