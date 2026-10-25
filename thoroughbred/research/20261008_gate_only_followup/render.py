"""Render gate-number effects with sample sizes and pointwise uncertainty."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent / "outputs"
plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 11})


def main():
    data = pd.read_csv(OUT / "number_profiles.csv")
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    for ax, (meet, distance, n) in zip(
        axes.flat, [(1, 1600, 10), (3, 1600, 12), (1, 1200, 12), (3, 1200, 12)], strict=True
    ):
        for window, label, color, shift in [
            ("all", "전체기간", "#236f9e", -0.12),
            ("2024plus", "2024년 이후", "#c36825", 0.12),
        ]:
            f = data[
                data.meet.eq(meet)
                & data.distance_m.eq(distance)
                & data.field_size.eq(n)
                & data.window.eq(window)
            ].sort_values("gate_number")
            x = f.gate_number.to_numpy() + shift
            ax.errorbar(
                x,
                f.effect_pp,
                yerr=np.vstack([f.effect_pp - f.ci_low, f.ci_high - f.effect_pp]),
                color=color,
                fmt="none",
                capsize=2,
                alpha=0.7,
                label=f"{label}: {int(f.races.iloc[0])}경주",
            )
            ax.scatter(x, f.effect_pp, facecolors="white", edgecolors=color, zorder=3)
            significant = f.q.lt(0.05).to_numpy()
            ax.scatter(x[significant], f.effect_pp.to_numpy()[significant], color=color, zorder=4)
        ax.axhline(0, color="#777777", lw=1)
        ax.set_xticks(range(1, n + 1))
        ax.set_xlabel("마번을 사용한 게이트 번호")
        ax.set_ylabel("같은 두수의 평균 게이트 대비 Top3 차이 (%p)")
        ax.set_title(f"{'서울' if meet == 1 else '부산'} {distance}m · {n}두")
        ax.grid(axis="y", alpha=0.18)
        ax.legend(fontsize=9)
    fig.suptitle("내측·외측 평균이 모든 게이트 번호의 우열을 뜻하지는 않는다", fontsize=18)
    fig.text(
        0.5,
        0.025,
        "선은 점별 95% 구간 · 채운 점은 해당 기간 전체 번호 대비의 BH q<0.05\n"
        "능력·과거 이력 조정 관찰값이며, 개별 말의 입상확률 가산이나 초 단위 보정값이 아님",
        ha="center",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0.075, 1, 0.95))
    fig.savefig(OUT / "gate_number_profiles.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
