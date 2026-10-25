"""Render research correction amounts with Korean labels."""

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/horse_record_normalization_mpl")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"


def main():
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    c = pd.read_csv(OUT / "conservative_candidates.csv")
    m = c[c.kind.eq("month")].copy()
    m["month"] = m.level.astype(int)
    keep = m[m.candidate_nonzero].groupby(["meet", "distance_m"]).size().index
    matrix = (
        m.set_index(["meet", "distance_m"])
        .loc[list(keep)]
        .reset_index()
        .pivot(index=["meet", "distance_m"], columns="month", values="candidate_add_seconds")
    )
    fig, ax = plt.subplots(figsize=(13, 5.7))
    data = matrix.to_numpy()
    im = ax.imshow(data, cmap="RdBu_r", vmin=-0.12, vmax=0.12, aspect="auto")
    ax.set_xticks(range(12), [f"{i}월" for i in range(1, 13)])
    ax.set_yticks(range(len(matrix)), [f"{meet} {distance}m" for meet, distance in matrix.index])
    for i in range(len(matrix)):
        for j in range(12):
            value = data[i, j]
            ax.text(
                j,
                i,
                "보류" if abs(value) < 0.005 else f"{value:+.2f}",
                ha="center",
                va="center",
                color="white" if abs(value) > 0.08 else "black",
                fontsize=11,
            )
    fig.colorbar(im, ax=ax, label="원시 완주시간에 더할 초", shrink=0.9)
    ax.set_title("기존 함수율 보정에 추가하는 보수적 월별 후보", fontsize=17, pad=18)
    fig.text(
        0.1,
        0.06,
        "양수: 빠르게 관측된 기록에 시간 추가 · 음수: 느리게 관측된 기록에서 시간 차감\n"
        "보류: 추가 적용0, 효과 부재의 뜻은 아님 · 게이트/실제 내외측 추가 적용은 보류 · "
        "예측 검증 전 연구 후보",
        fontsize=10,
    )
    fig.subplots_adjust(left=0.14, right=0.92, bottom=0.21, top=0.85)
    fig.savefig(OUT / "monthly_candidate_seconds.png", dpi=160)
    plt.close(fig)
    e = pd.read_csv(OUT / "joint_seconds_profiles.csv")
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True)
    for ax, (meet, distance) in zip(
        axes.flat, [("서울", 1200), ("부산", 1200), ("서울", 1400), ("부산", 1400)], strict=True
    ):
        for period, label, color in [
            ("all_mad4", "전체기간", "#2458a6"),
            ("recent_mad4", "2024년 이후", "#e27625"),
        ]:
            g = e[
                e.meet.eq(meet)
                & e.distance_m.eq(distance)
                & e.kind.eq("month")
                & e.period.eq(period)
            ].copy()
            g["month"] = g.level.astype(int)
            g = g.sort_values("month")
            ax.plot(g.month, g.effect_seconds, color=color, label=label)
            ax.fill_between(g.month, g.ci_low, g.ci_high, color=color, alpha=0.12)
        ax.axhline(0, color="gray", linewidth=0.8)
        ax.set_title(f"{meet} {distance}m")
        ax.set_xticks(range(1, 13))
        ax.set_ylabel("연간 평균 대비 관찰된 시간 차이(초)")
        ax.grid(alpha=0.15)
        ax.legend(fontsize=10)
    fig.suptitle("월별 관찰 차이는 적용 후보량보다 크며 기간에 따라 달라진다", fontsize=16)
    fig.text(
        0.07,
        0.025,
        "같은 말·등급×연도·정확 함수율 등을 통제한 공동모형 · 음수는 빠른 기록 방향 · "
        "음영은 점별95% 구간 · 관찰 차이를 전량 보정하지 않음",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(OUT / "monthly_observed_seconds.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
