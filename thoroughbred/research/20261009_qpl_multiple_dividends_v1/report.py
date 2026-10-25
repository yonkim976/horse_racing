"""Publish QPL multiple-hit counts, winning dividends, and summed returns."""

# ruff: noqa: E501

import json

import pandas as pd
import run as e


def table(frame):
    def cell(v):
        return f"{v:.4f}" if isinstance(v, float) else str(v)

    lines = [
        "| " + " | ".join(frame.columns) + " |",
        "| " + " | ".join(["---"] * len(frame.columns)) + " |",
    ]
    lines += [
        "| " + " | ".join(cell(v) for v in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join(lines)


def main():
    e.check()
    assert json.loads((e.OUT / "verification.json").read_text())["status"] == "passed"
    sql = json.loads((e.OUT / "sql_crosscheck.json").read_text())
    assert sql["status"] == "passed"
    assert not (e.HERE / "README.md").exists()
    dividends = pd.read_csv(e.OUT / "dividend_summary.csv")
    all_div = dividends[dividends.scope.eq("all")].iloc[0]
    returns = pd.read_csv(e.OUT / "model_return_summary.csv")
    chosen = returns[returns.policy.eq("in3_out3")].iloc[0]
    multi = pd.read_csv(e.OUT / "multiple_hit_counts.csv")
    selected = multi[multi.policy.eq("in3_out3")]
    races = pd.read_parquet(e.OUT / "matched_race_returns.parquet")
    dates = pd.read_parquet(e.OUT / "db_races.parquet").set_index("race_key").race_date
    matched_dates = dates.loc[races.race_key.unique()]
    payouts = pd.read_parquet(e.OUT / "winning_pair_payouts.parquet")
    same_market = payouts[payouts.eligible & payouts.race_key.isin(races.race_key)]
    e.save(
        e.OUT / "matched_market_comparison.json",
        dict(
            races=int(same_market.race_key.nunique()),
            winning_pairs=len(same_market),
            market_mean=float(same_market.odds.mean()),
            selected_mean=float(chosen.mean_winning_odds),
            policy="in3_out3",
            first_date=str(matched_dates.min()),
            last_date=str(matched_dates.max()),
        ),
    )
    text = f"""# 복연 다중 적중·당첨 배당·합산 환급

2026-10-09. 기존 복연 집계는 여러 조합이 맞은 횟수도 저장했지만, 앞서 보여준67.06%는 **한 조합 이상 맞힌 경주 비율**이었다. 조합 선택은 개별 복연 확률순이며 배당 가중 환급 최적화가 아니다. 이번에는 실제 당첨 배당을 연결하여2개·3개 적중도 모두 더했다. 새 학습/선택/운영 변경은 없다.

## 2024–2026년 다중 적중 분포

기존 동일4,799경주의 축 포함3개+제외3개, 총6조합 결과다.

{table(selected)}

0개1,581경주, 1개2,193경주, 2개332경주, 3개693경주다. 하나 이상 적중3,218경주(67.06%)이며 **총 당첨 조합은4,936개**다. 2개·3개 적중 경주를 경주 적중률에서2번·3번 세지는 않는다. 두 개가 맞으면 두 조합의 각 배당을, 세 개면 세 배당을 합산해야 한다. 모든 정책의 분포:

{table(multi)}

## 2026년 실제 당첨 복연 평균 배당

로컬 SQLite의 서울·부산 완료 경주 중 실제1·2·3착이 한 두씩이고 당첨복연3개 배당이 모두 정상인 **{int(all_div.races):,}경주/{int(all_div.winning_pairs):,}당첨조합**, **{all_div.first_date}~{all_div.last_date}**다. 요청 기준일10월9일까지 조회했지만 DB에서 확인 가능한 마지막 정상 자료는10월2일이었다. 서울 종료일9월20일, 부산10월2일로 지역마다 다르다.2026년 전체 연간 값이나10월9일까지의 완전 수집이라고 표현하지 않는다.

| 통계 | 배당(배) |
| --- | ---: |
| 전체 당첨조합 산술평균 | {all_div["mean"]:.4f} |
| 중앙값 | {all_div["median"]:.4f} |
| 1~99백분위 범위만 사용한 평균 | {all_div.trim1_mean:.4f} |
| 5~95백분위 범위만 사용한 평균 | {all_div.trim5_mean:.4f} |
| 25~75백분위 범위 | {all_div.p25:.4f}~{all_div.p75:.4f} |

주 극단값제외 통계는1~99백분위 경계 **{all_div.trim1_low:.4f}~{all_div.trim1_high:.4f}배** 안의 {int(all_div.trim1_count):,}개다.5~95백분위 경계는 {all_div.trim5_low:.4f}~{all_div.trim5_high:.4f}배 안의 {int(all_div.trim5_count):,}개다. 경계 동률은 포함하므로 정확히2%/10% 행을 제거한 절삭평균과는 다르다. 모든 가능한 미당첨 조합의 배당을 평균낸 값이 아니다.3개씩 완전한 경주만 사용하여 당첨조합 평균과 경주별3개 평균의 평균은 일치한다.

{table(dividends)}

서울·부산 완료경주1,304개 중 Top3착순이 정확한1·2·3 한 두씩이 아닌7개를 제외했다. 예정 상태31개도 제외했다. 제외 경주의 관측 Top3 착순은 [SQL 대조](outputs/sql_crosscheck.json)에 보존했다. 정산 특수값9999.9,0,누락,비유한값은 정상 배당으로 평균내지 않는다. 실제 정상 Top3 경주에서는 당첨배당3개가 모두 확인됐다. 동률 등 복잡한 정산 경주의 환급은 이번 표에서 별도 취급하지 않는다.

## 우리 조합에 실제 배당을 연결한 결과

예측명단·마번·말ID·정상화착순 전체와 배당3개가 일치한2026년 **{int(chosen.races):,}경주**, **{matched_dates.min()}~{matched_dates.max()}**다. 위4,799경주 다중 적중 표와 기간이 다르다.1288개 연구평가 경주 전부 연결됐으며, 실제 경주 정답을 보고 조합을 다시 고르지 않았다.

{table(returns)}

포함3+제외3은 총{int(chosen.tickets):,}조합에 각각1단위를 투입하고, 적중한{int(chosen.winning_tickets):,}조합의 실제 배당을 모두 더한 표시환급이 **{chosen.display_return:,.4f}단위**였다. 단순 총환급비율 **{chosen.gross_return_ratio * 100:.4f}%**, 표시손익률 **{chosen.net_ratio_before_adjustments * 100:+.4f}%**다.2개·3개 맞힌 경주도 전부 합산한 결과다. 적중경주는{int(chosen.hits):,}개({chosen.hit_rate * 100:.4f}%)이며 당첨조합 수와 다르다.

**전체 당첨 배당 평균과 우리가 맞힌 평균은 다르다.** 선택 적중조합의 평균은 **{chosen.mean_winning_odds:.4f}배**다. 같은1288경주 시장의 모든 당첨복연 평균은 **{same_market.odds.mean():.4f}배**이며, 일반2026년 평균 {all_div["mean"]:.4f}배를 우리 적중률에 곱해서 환급을 추정하면 안 된다.

표시환급은 세금·절사·개별 환급 예외를 적용하지 않은 단순 합산이다. 배당 누락/취소/공동착순 등 복잡한 정산 경주는 별도이며 실제 최종 실현 순수익이라고 부르지 않는다. 극단값제외는 시장 배당의 설명 통계에만 적용했고 **모델 합산 환급에서는 높은 정상 배당도 자르지 않았다.**

## 검증과 해석

읽기 전용 SQLite 단일 트랜잭션의 서울/부산 행을 동결하고 해시를 저장했다. 실제당첨2두 조합별 배당을 독립 SQL 조인으로 대조하고 모든 선택 조합의0/양수환급·다중적중합·극단값제외·기존4,936당첨조합을 재계산했다. [검증](outputs/verification.json) · [원천SQL대조](outputs/sql_crosscheck.json) · [자료 시점](outputs/database_snapshot.json).

예측은 기존 연구의 후향 검증값이며 새 독립 기간이 아니다. 기존 당일 부담중량 PIT 검증 미완료 한계도 유지한다. 원축의 안정성/적중률/당첨조합 수/배당/수익은 서로 다른 지표다. 이번 데이터에서 다중 적중을 합산해도 포함3+제외3 정책의 단순환급은 투입에 미달했다. 운영/선택 모델은 유지했고 제주/Supabase/DB쓰기는 하지 않았다.

[사전 계획](PLAN.md) · [배당통계](outputs/dividend_summary.csv) · [환급표](outputs/model_return_summary.csv) · [다중적중](outputs/multiple_hit_counts.csv) · [전체선택환급](outputs/matched_ticket_returns.parquet) · [용량](outputs/artifact_inventory.json).
"""
    (e.HERE / "README.md").write_text(text)
    pub = f"""# 게시 요약: 복연 다중 적중과 평균 배당

기존4,799경주의 축 포함3+제외3에서는2개 적중332경주,3개 적중693경주,총4,936조합이 맞았다.67.06%는 하나 이상 적중한 경주 비율이다.

로컬2026년 서울·부산 정상1,297경주/3,891당첨복연조합({all_div.first_date}~{all_div.last_date})의 평균배당은 {all_div["mean"]:.2f}배, 중앙값 {all_div["median"]:.2f}배,1~99백분위 범위 평균 {all_div.trim1_mean:.2f}배,5~95백분위 범위 평균 {all_div.trim5_mean:.2f}배다. DB자료 종료일이 지역별로 다르며 연간전체 통계가 아니다.

실제 배당과 일치하는2026년1,288경주에서 선택한 포함3+제외3의 적중배당 평균은 {chosen.mean_winning_odds:.2f}배였다.2개·3개 적중을 모두 합산한 세금/절사 전 단순총환급은 투입 대비 {chosen.gross_return_ratio * 100:.2f}%, 표시손익률 {chosen.net_ratio_before_adjustments * 100:+.2f}%였다. 일반 배당 평균을 모델 적중률에 그대로 곱하면 안 된다. 후향 검증이며 운영/선택은 유지한다.

[전체 보고서](README.md) · [검증](outputs/verification.json).
"""
    (e.HERE / "PUBLICATION.md").write_text(pub)
    e.save(
        e.OUT / "decision.json",
        dict(
            status="multiple_win_returns_evaluated_no_promotion",
            production_changed=False,
            selected_baseline_changed=False,
            database_writes=False,
            supabase_access=False,
            jeju_access=False,
            market_races=int(all_div.races),
            model_races=int(chosen.races),
            gross_return_ratio=float(chosen.gross_return_ratio),
            conclusion="Multiple winning bets summed; displayed gross return remained below stake.",
        ),
    )
    shared = [
        e.R / "README.md",
        e.R / "ARTIFACT_SIZE_LOG.md",
        e.R / "conclusions/README.md",
        e.R / "conclusions/SOURCES.md",
        e.R / "conclusions/source_manifest.json",
    ]
    before = {}
    for path in shared:
        name = str(path.relative_to(e.ROOT))
        before[name] = dict(bytes=path.stat().st_size, sha256=e.sha(path))
        dest = e.OUT / "publication_before" / path.relative_to(e.R)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
    e.save(e.OUT / "publication_before.json", before)
    target = e.R / "conclusions/34_QPL_MULTIPLE_DIVIDENDS.md"
    assert not target.exists()
    target.write_text(
        pub.replace("(README.md)", f"(../{e.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{e.HERE.name}/outputs/"
        )
    )
    marker = "<!-- qpl_multiple_dividends_v1_20261009 -->"
    for path in [shared[0], shared[2], shared[3]]:
        link = f"{e.HERE.name}/README.md" if path.parent == e.R else "34_QPL_MULTIPLE_DIVIDENDS.md"
        with path.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[복연 다중 적중과 실제 당첨 배당]({link}):2026서울/부산 정상당첨 평균 {all_div['mean']:.2f}배,1~99백분위 범위 {all_div.trim1_mean:.2f}배. 실제1288경주 포함3+제외3 다중당첨 합산 표시총환급 {chosen.gross_return_ratio * 100:.2f}%. 적중률/일반배당평균/모델당첨평균을 구분하고 운영은 유지한다.\n"
            )
    manifest = json.loads(shared[-1].read_text())
    add = (
        [e.HERE / n for n in ["PLAN.md", "README.md", "PUBLICATION.md"]]
        + [
            e.OUT / n
            for n in [
                "source_lock.json",
                "database_snapshot.json",
                "verification.json",
                "sql_crosscheck.json",
                "decision.json",
            ]
        ]
        + [target, shared[0], shared[2], shared[3]]
    )
    for path in add:
        name = str(path.relative_to(e.ROOT))
        manifest["sources"] = [r for r in manifest["sources"] if r["path"] != name]
        manifest["sources"].append(dict(path=name, sha256=e.sha(path), bytes=path.stat().st_size))
    e.save(shared[-1], manifest)
    e.save(
        e.OUT / "completion.json",
        dict(
            status="complete_verified_published_locally",
            market_races=int(all_div.races),
            model_races=int(chosen.races),
            website_deployed=False,
            production_changed=False,
            database_writes=False,
        ),
    )
    e.check()
    print(pub, flush=True)


if __name__ == "__main__":
    main()
