"""Render the core conditional gate comparisons, preserving uncertainty."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 11})
p = pd.read_csv(OUT / "seoul1200_11_focus.csv", dtype={"level": str})
bands = ["건조", "양호", "다습", "포화", "불량"]
fig, axes = plt.subplots(1, 2, figsize=(12, 5.8))
for j, (family, title) in enumerate(
    [("outer_inner", "각 상태의 외측 - 내측"), ("interaction", "건조 대비 외내차의 변화")]
):
    ax = axes[j]
    levels = bands if j == 0 else bands[1:]
    for period, color, offset, label in [
        ("all_mad4", "#236b9e", -0.1, "전체 4MAD"),
        ("recent_mad4", "#d06b2d", 0.1, "2024~2026 4MAD"),
    ]:
        s = p[p.period.eq(period) & p.family.eq(family)].set_index("band").reindex(levels)
        y = np.arange(len(levels)) + offset
        for i, r in enumerate(s.itertuples()):
            if not np.isfinite(r.effect_seconds):
                continue
            c = color if r.supported else "#aaaaaa"
            ax.errorbar(
                r.effect_seconds,
                y[i],
                xerr=np.array([[r.effect_seconds - r.ci_low], [r.ci_high - r.effect_seconds]]),
                fmt="o",
                color=c,
                capsize=3,
                label=label if i == 0 else None,
            )
    ax.axvline(0, color="#777777", lw=1)
    ax.set_yticks(range(len(levels)), levels)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.18)
    ax.set_xlabel("조건부 기록 차이 (초)")
    ax.set_title(title, pad=12)
    ax.spines[["top", "right"]].set_visible(False)
axes[0].legend(loc="upper left", frameon=False)
fig.suptitle("서울 1200m · 11두 경주의 주로상태별 게이트 차이", fontsize=17, y=0.98)
fig.text(
    0.5,
    0.04,
    "마번 순서 앞4두 · 중간3두 · 뒤4두 | 점별 95% 구간 · 회색은 지원 부족\n"
    "경주·마필 통제 후향 비교 | 포화의 외측 우위나 자동 보정량을 뜻하지 않음",
    ha="center",
    fontsize=10,
    color="#555555",
)
fig.tight_layout(rect=(0, 0.13, 1, 0.93))
fig.savefig(OUT / "seoul1200_moisture_gate.png", dpi=160, facecolor="white")
plt.close(fig)
