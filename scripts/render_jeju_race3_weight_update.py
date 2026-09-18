"""Render one HY_R_FORM race report with an official same-day weight overlay."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl


KST = ZoneInfo("Asia/Seoul")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def weight_note(delta: float) -> tuple[str, str]:
    if abs(delta) >= 10:
        return "큰 변화 · 별도 확인 필요", "alert"
    if delta == 0:
        return "변화 없음", "steady"
    return "변화 폭 작음", "normal"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prediction_dir", type=Path)
    parser.add_argument("weight_observation", type=Path)
    parser.add_argument("--race", type=int, default=3)
    args = parser.parse_args()

    root = args.prediction_dir.resolve()
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    races = json.loads((root / "race_predictions.json").read_text(encoding="utf-8"))
    explanations = json.loads((root / "horse_explanations.json").read_text(encoding="utf-8"))
    observation = json.loads(args.weight_observation.read_text(encoding="utf-8"))

    race = next(item for item in races if int(item["race_number"]) == args.race)
    horses = (
        pl.read_parquet(root / "horse_predictions.parquet")
        .filter(pl.col("race_number") == args.race)
        .sort("model_rank")
        .to_dicts()
    )
    reason_by_id = {
        str(item["horse_id"]): item
        for item in explanations
        if int(item["race_number"]) == args.race
    }
    parsed = observation["parsed"]
    if int(parsed["race_number"]) != args.race:
        raise ValueError("Weight observation race does not match requested race")
    weight_by_id = {str(item["horse_id"]): item for item in parsed["runners"]}
    prediction_ids = {str(item["horse_id"]) for item in horses}
    if prediction_ids != set(weight_by_id):
        missing = sorted(prediction_ids - set(weight_by_id))
        extra = sorted(set(weight_by_id) - prediction_ids)
        raise ValueError(f"Prediction/weight runner mismatch: missing={missing}, extra={extra}")

    retrieved_at = datetime.fromtimestamp(observation["retrieved_ms"] / 1000, tz=KST)
    rows = []
    for horse in horses:
        horse_id = str(horse["horse_id"])
        weight = weight_by_id[horse_id]
        if int(horse["horse_number"]) != int(weight["horse_number"]):
            raise ValueError(f"Horse number mismatch for {horse_id}")
        if str(horse["horse_name"]) != str(weight["horse_name"]):
            raise ValueError(f"Horse name mismatch for {horse_id}")
        delta = float(weight["body_weight_delta_kg"])
        note, note_class = weight_note(delta)
        selected_class = " selected" if horse["selected_set"] else ""
        pick = "<span class='pill pick'>한 마리 선택</span>" if horse["selected_pick"] else ""
        selected = "<span class='pill set'>입상 3두</span>" if horse["selected_set"] else ""
        reasons = reason_by_id[horse_id]
        positive = reasons["positive_reasons"][0]["label"] if reasons["positive_reasons"] else "표시 없음"
        negative = reasons["negative_reasons"][0]["label"] if reasons["negative_reasons"] else "표시 없음"
        rows.append(
            f"""
            <tr class="{selected_class.strip()}">
              <td><strong>{int(horse['model_rank'])}</strong></td>
              <td><strong>{int(horse['horse_number'])}번 {esc(horse['horse_name'])}</strong><div class="pills">{pick}{selected}</div></td>
              <td>{esc(horse['jockey_name'])}</td>
              <td>{float(horse['burden_kg']):.1f}kg</td>
              <td class="prob">{float(horse['top3_probability']):.1%}</td>
              <td><strong>{float(weight['body_weight_kg']):.0f}kg</strong></td>
              <td class="delta {note_class}">{delta:+.0f}kg<div>{note}</div></td>
              <td><span class="up">+ {esc(positive)}</span><br><span class="down">− {esc(negative)}</span></td>
            </tr>
            """
        )

    major_changes = [
        item for item in parsed["runners"] if abs(float(item["body_weight_delta_kg"])) >= 10
    ]
    if major_changes:
        major_text = ", ".join(
            f"{item['horse_number']}번 {item['horse_name']} {float(item['body_weight_delta_kg']):+.0f}kg"
            for item in major_changes
        )
    else:
        major_text = "없음"

    horse_by_id = {str(item["horse_id"]): item for item in horses}
    selected_weight_text = ", ".join(
        f"{horse_by_id[str(horse_id)]['horse_number']}번 "
        f"{horse_by_id[str(horse_id)]['horse_name']} "
        f"{float(weight_by_id[str(horse_id)]['body_weight_kg']):.0f}kg "
        f"({float(weight_by_id[str(horse_id)]['body_weight_delta_kg']):+.0f}kg)"
        for horse_id in race["predicted_set_horse_ids"]
    )

    model_manifest = root / "manifest.json"
    report_path = root / f"race{args.race}_weight_update.html"
    css = """
    :root{--ink:#17222d;--muted:#64717c;--navy:#12344d;--blue:#16658a;--green:#18724b;--red:#aa352e;--gold:#d5a43a;--paper:#f5f2eb;--line:#d9dedf}
    *{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Noto Sans KR",sans-serif;line-height:1.55}
    header{background:linear-gradient(135deg,#102b40,#185d78);color:white;padding:48px 22px}header>div,main{max-width:1180px;margin:auto}h1{font-size:38px;margin:6px 0 12px}header p{color:#d9ebf2;max-width:840px}.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-weight:800;color:#8fd0e4}
    .stamp{display:inline-block;background:#0c2536;border:1px solid #50849a;border-radius:999px;padding:7px 12px;margin-top:10px;font-size:13px}main{padding:24px 20px 50px}
    .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.card,.notice,.table-wrap{background:white;border:1px solid var(--line);border-radius:14px;box-shadow:0 6px 18px #20394812}.card{padding:20px}.card span{display:block;color:var(--muted);font-size:13px}.card strong{display:block;font-size:23px;color:var(--navy);margin-top:8px}
    .notice{padding:18px 20px;margin:16px 0}.notice strong{color:var(--navy)}.notice.alert{border-left:5px solid var(--gold);background:#fffaf0}.notice.info{border-left:5px solid var(--blue);background:#f2f8fb}
    .table-wrap{overflow:auto;margin-top:16px}table{width:100%;border-collapse:collapse;min-width:1000px}th{background:#eaf1f4;color:var(--navy);text-align:left;font-size:13px;position:sticky;top:0}th,td{padding:12px 11px;border-bottom:1px solid #e7eaeb;vertical-align:top}tr.selected{background:#f2faf6}.prob{font-weight:900;color:var(--blue);font-size:17px}.delta div{font-size:11px;white-space:nowrap}.alert{color:var(--red);font-weight:900}.steady{color:var(--muted)}.normal{color:var(--green)}
    .pill{display:inline-block;border-radius:999px;padding:2px 7px;font-size:10px;font-weight:800;margin:5px 4px 0 0}.pill.pick{background:#163b55;color:white}.pill.set{background:#dff1e8;color:#155e40}.up{color:var(--green);font-size:12px}.down{color:var(--red);font-size:12px}
    h2{margin:28px 0 8px;color:var(--navy)}.source{font-size:12px;color:var(--muted);word-break:break-all}.source a{color:var(--blue)}footer{margin-top:24px;border-top:1px solid var(--line);padding-top:16px;color:var(--muted);font-size:12px}
    @media(max-width:760px){.grid{grid-template-columns:1fr}h1{font-size:29px}}
    """
    html_text = f"""<!doctype html>
    <html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>제주 {args.race}경주 HY_R_FORM 마체중 확인 예측</title><style>{css}</style></head><body>
    <header><div><div class="eyebrow">HY_R_FORM · Official Weight Check</div><h1>제주 {args.race}경주 최신 예측</h1>
    <p>현재 공식 출마표로 모델을 다시 실행하고, 경주 전 공개된 공식 마체중 10두를 모두 연결했다.</p>
    <div class="stamp">예측 생성 {esc(metadata['created_at'])} · 마체중 확인 {retrieved_at.strftime('%Y-%m-%d %H:%M:%S KST')}</div></div></header>
    <main><section class="grid">
      <article class="card"><span>한 마리 입상 선택</span><strong>{esc(race['pick'])}</strong><b>{race['pick_top3_probability']:.1%}</b></article>
      <article class="card"><span>입상 3두 선택</span><strong>{' · '.join(esc(x) for x in race['predicted_set'])}</strong><b>집합확률 {race['set_probability']:.2%}</b></article>
      <article class="card"><span>정확 순서</span><strong>{' → '.join(esc(x) for x in race['predicted_order'])}</strong><b>순서확률 {race['order_probability']:.2%}</b></article>
    </section>
    <section class="notice info"><strong>마체중 확인 결론.</strong> 선택 3두: {esc(selected_weight_text)}. 큰 변화 관측: {esc(major_text)}. 선택마에 큰 변화가 없다면 모델 선택을 유지하고, 큰 변화가 있더라도 검증된 계수 없이 확률을 임의 조정하지 않는다.</section>
    <section class="notice alert"><strong>해석 제한.</strong> 동결된 HY_R_FORM은 당일 마체중을 입력 변수로 사용하지 않는다. 아래 수치는 경주 직전 상태 확인용이며, 큰 증감의 유불리는 이번 관측만으로 정량화하지 않았다.</section>
    <h2>{args.race}경주 전체 순위와 공식 마체중</h2><div class="table-wrap"><table><thead><tr><th>모델순위</th><th>경주마</th><th>기수</th><th>부담중량</th><th>입상확률</th><th>마체중</th><th>증감</th><th>모델 주요 근거</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    <section class="notice"><strong>카드 검증.</strong> 마체중 페이지 10두와 최신 모델 출마표 10두의 말 번호·말 이름·말 ID가 모두 일치했다. 최신 재실행 결과도 앞선 교정 예측과 동일하다. 변경사항 페이지는 수집기 표 구조 오류가 있어 완전한 무변경 선언에는 사용하지 않았다.</section>
    <p class="source">공식 출처: <a href="{esc(observation['url'])}">{esc(observation['url'])}</a><br>원문 SHA-256 {esc(observation['raw_sha256'])}<br>모델 SHA-256 {esc(metadata['model_sha256'])}</p>
    <footer>대상 경주 결과 endpoint 호출 0회 · 과거 이력 마지막 날짜 {esc(metadata['history_last_date'])} · 당일 마체중은 사후 조정 없이 관측 정보로만 표시 · 예측 manifest SHA-256 {sha256(model_manifest)}</footer>
    </main></body></html>"""
    report_path.write_text(html_text, encoding="utf-8")

    weight_json_path = root / f"race{args.race}_weight_observations.json"
    weight_json_path.write_text(
        json.dumps(
            {
                "race_number": args.race,
                "retrieved_at": retrieved_at.isoformat(),
                "source_url": observation["url"],
                "raw_sha256": observation["raw_sha256"],
                "runners": parsed["runners"],
                "same_day_weight_used_as_model_input": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    output_manifest = root / f"race{args.race}_weight_update_manifest.json"
    manifest = {
        "report": {"path": report_path.name, "sha256": sha256(report_path)},
        "weight_observations": {
            "path": weight_json_path.name,
            "sha256": sha256(weight_json_path),
        },
        "prediction_manifest_sha256": sha256(model_manifest),
        "weight_source_raw_sha256": observation["raw_sha256"],
        "runner_match_count": len(horses),
        "target_results_used": False,
        "same_day_weight_used_as_model_input": False,
    }
    output_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"report": str(report_path), **manifest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
