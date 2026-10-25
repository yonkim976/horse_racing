"""Render conditional seconds contrasts; no automatically applied penalties."""

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/horse_gate_lateral_seconds_mpl")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"


def main():
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    d = pd.read_csv(OUT / "seconds_profiles.csv", dtype={"level": str})
    fig, ax = plt.subplots(figsize=(11, 5.5))
    examples = [
        ("서울", 1600, "exact10", "10"),
        ("부산", 1600, "exact12", "1"),
        ("부산", 1400, "exact12", "1"),
    ]
    for y, (meet, distance, block, level) in enumerate(examples):
        for period, label, color, offset in [
            ("all_mad4", "전체기간4MAD", "#2458a6", -0.1),
            ("recent_mad4", "2024년이후4MAD", "#e27625", 0.1),
        ]:
            r = d[
                d.kind.eq("gate")
                & d.meet.eq(meet)
                & d.distance_m.eq(distance)
                & d.block.eq(block)
                & d.level.eq(level)
                & d.family.eq("number")
                & d.adjustment.eq("dual")
                & d.period.eq(period)
            ].iloc[0]
            ax.errorbar(
                r.effect_seconds,
                y + offset,
                xerr=[[r.effect_seconds - r.ci_low], [r.ci_high - r.effect_seconds]],
                fmt="o",
                color=color,
                label=label if y == 0 else None,
                capsize=4,
                markerfacecolor=color if r.q < 0.05 else "white",
            )
    ax.set_yticks(
        range(3),
        [f"{m} {distance}m · {block[5:]}두 · {level}번" for m, distance, block, level in examples],
    )
    ax.axvline(0, color="gray", linewidth=1)
    ax.set_xlabel("같은 두수 평균 게이트 대비 완주시간 차이(초) · 양수는 느린 방향")
    ax.set_title("느린 방향은 남지만 최근 다중비교 기준은 통과하지 못했다", fontsize=15, pad=18)
    ax.legend(loc="lower right")
    ax.grid(axis="x", alpha=0.15)
    ax.invert_yaxis()
    fig.text(
        0.08,
        0.04,
        "같은 경주·같은 말과 기존 이력 통제 · 점별95% 구간 · 채운 점은q<0.05 · "
        "고정 보정초로 전량 적용하지 않음",
        fontsize=10,
    )
    fig.subplots_adjust(left=0.29, bottom=0.2, top=0.83, right=0.96)
    fig.savefig(OUT / "gate_seconds_focus.png", dpi=170)
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True)
    for row, meet in enumerate(["서울", "부산"]):
        points = ["S1F", "3C", "4C", "G1F"] if meet == "서울" else ["S1F", "G4F", "G3F", "G1F"]
        for col, block in enumerate(["pair", "triple"]):
            ax = axes[row, col]
            for period, label, color, offset in [
                ("all_mad4", "전체기간", "#2458a6", -0.09),
                ("recent_mad4", "2024년이후", "#e27625", 0.09),
            ]:
                g = (
                    d[
                        d.kind.eq("lateral")
                        & d.meet.eq(meet)
                        & d.distance_m.eq(0)
                        & d.period.eq(period)
                        & d.metric.eq("finish")
                        & d.block.eq(block)
                        & d.level.eq("outer-inner")
                    ]
                    .set_index("point")
                    .loc[points]
                )
                ax.errorbar(
                    g.effect_seconds,
                    np.arange(4) + offset,
                    xerr=[g.effect_seconds - g.ci_low, g.ci_high - g.effect_seconds],
                    fmt="o",
                    color=color,
                    capsize=3,
                    label=label,
                )
            ax.set_yticks(range(4), points)
            ax.invert_yaxis()
            ax.axvline(0, color="gray", linewidth=0.8)
            ax.set_title(f"{meet} · {'2두' if block == 'pair' else '3두 이상'} 마군")
            ax.set_xlabel("외측-내측 완주시간 차이(초)")
            ax.grid(axis="x", alpha=0.15)
            ax.legend(fontsize=9)
    fig.suptitle("코너의 외측 느림과 막판의 외측 빠름을 구분한다", fontsize=16)
    fig.text(
        0.08,
        0.025,
        "같은 마군·같은 말×거리와 게이트·기존 이력 통제 · 점별95% 구간 · 음수: 외측 빠름 · "
        "상대 위치이며 실제 추가 주행미터가 아님",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(OUT / "lateral_seconds_by_point.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    main()
