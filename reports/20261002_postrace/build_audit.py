from pathlib import Path
import csv, json, re, sqlite3, html, hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
E=lambda s:html.escape(str(s),quote=True)
sources={2:ROOT/'jeju/predictions/20261002_hy_r_form_readonly_20261002T061828',3:ROOT/'thoroughbred/predictions/20261002_busan_3_9_readonly_20261002T041207Z'}
human={
(2,3):dict(axis=[7],tickets=[[7,8,9],[6,7,8],[4,7,8],[4,7,9],[6,8,9]],review='4·6·7을 모두 언급했지만 4-6-7을 묶지 않았다. 7은 3착으로 축 역할을 했고, 8·9는 4·5착. 뒤의 기록-only 검토에서는 4를 낮췄는데 실제 4가 우승해 그 판단도 틀렸다.'),
(2,4):dict(axis=[8],tickets=[[4,7,8],[7,8,9],[7,8,10]],review='8은 3착, 10은 2착으로 거리 능력 평가 일부는 맞았다. 긴 공백 때문에 우선순위를 낮춘 6이 우승했다. 7을 모든 인간 추천 조합에 넣은 것이 실패 요인. 1-7-8은 모델 참고 조합으로만 표시돼 인간 조합 수에서 제외했다.'),
(2,5):dict(axis=[1,5],tickets=[[1,3,5],[1,2,5],[1,5,6],[2,3,5]],review='1은 10착, 5는 8착으로 두 중심마 모두 실패. 3 복병 평가는 3착으로 맞았지만, 공백 때문에 낮춘 6이 우승했고 7의 2착을 놓쳤다. 한 축 이탈 대비만으로 두 중심마의 동시 실패를 감당하지 못했다.'),
(2,6):dict(axis=[7],tickets=[[3,4,7],[4,5,7],[2,4,7],[4,6,7],[3,5,6]],review='종반 기록으로 평가한 3·4가 1·2착했지만 7은 6착. 후순위로 둔 1이 3착. 7만 빠질 때 3-4-6을 따로 언급했어도 실제 1-3-4는 제시하지 않았다.'),
(2,7):dict(axis=[3],tickets=[[3,4,5],[2,3,5],[2,3,4],[3,5,6],[2,4,5]],review='3의 축 판단은 우승, 2의 종반 상대 평가는 2착으로 맞았다. 5는 9착이었고, 우선순위를 낮춘 8이 3착. 축과 두 번째 말이 맞아도 삼복의 세 번째 말을 놓치면 실패다.'),
(3,3):dict(axis=[8],tickets=[[1,8,11],[6,8,11],[7,8,11],[1,6,8]],review='8은 2착, 가장 먼저 붙인 11은 우승. 공백·체중 증가를 걱정한 1은 8착. 모델 입상 8.6%의 3이 3착하면서 삼복이 빗나갔다.'),
(3,4):dict(axis=[1],tickets=[[1,3,5],[1,3,6],[1,5,6],[1,3,9],[3,5,6],[3,5,9],[5,6,9],[2,5,6]],review='1은 우승, 5는 3착. 전개 후보로 언급한 2가 2착했지만 1-2-5를 만들지 않았다. 실제 2·5는 초반·종반 대부분 1·2위로 진행했다. 구간 기록으로 3·6을 올리는 과정에서 앞선 2의 조합 자리를 놓쳤다.'),
(3,5):dict(axis=[10,3],tickets=[[3,4,10],[3,6,10],[4,6,10],[3,4,6],[4,5,6]],review='10은 8착, 3은 5착. 4를 모델보다 높인 판단은 2착으로 맞았고 5는 우승. 종반 부진 때문에 낮춘 11이 3착해 축 동시 실패 대비 4-5-6도 실패했다. 가장 마지막 다섯 조합을 평가하고 초기 복병 조합은 합치지 않았다.'),
(3,6):dict(axis=[4],tickets=[[2,4,8],[2,4,9],[2,4,5],[4,8,9],[2,8,9]],review='4는 2착, 감량으로 높인 8은 3착. 거리 실적을 인정한 5가 우승했지만 4-5-8을 제시하지 않았다. 2는 6착, 9는 7착. 개별 말 검토보다 조합 구성에서 실패했다.'),
}
manifest=json.loads((ROOT/'thoroughbred/reports/20261002_busan_7_9/analysis_manifest.json').read_text())
latest_reviews={7:'9는 4착으로 축 실패. 모델보다 올린 3·11은 2·3착. 8은 초반부터 마지막 200m까지 계속 1위로 우승해, 경합 위험을 크게 본 것보다 편하게 경주를 풀었다. 여섯 번째 3-8-11이 적중했으며 첫 주력은 실패했다.',8:'10은 5위권에서 따라가 마지막 200m 12.9초로 우승. 강하게 붙인 11은 10착, 거리 검증을 이유로 올린 9는 11착. 낮춘 4가 2착, 후미에서 3F-G 39.0초·1F-G 12.9초를 쓴 6이 3착. 첫 거리라는 이유만으로 성장 후보를 과도하게 낮춰서는 안 된다.',9:'10은 S1F부터 G2F까지 1위였지만 최종 4착. 4는 3위권에서 올라와 우승, 2는 2착, 5는 후미에서 G3F 38.4초로 3착. 실제 흐름이 10 소진 대비 시나리오와 맞아 다섯 번째 2-4-5가 적중. 첫 주력은 실패했다.'}
for n in (7,8,9):
 p=manifest['plans'][str(n)]
 human[3,n]=dict(axis=[9] if n==7 else [10] if n==8 else [10,4],tickets=[t[0] for t in p['tickets']],review=latest_reviews[n])

c=sqlite3.connect('file:'+str(ROOT/'data/horse_racing.sqlite3')+'?mode=ro',uri=True)
c.row_factory=sqlite3.Row
rows=[]
for meet,p in sources.items():
 with (p/'runner_probabilities.csv').open() as f:pred=list(csv.DictReader(f))
 rank_col='model_rank' if meet==2 else 'pred_rank';number_col='race_number' if meet==2 else 'race_no';prob_col='prob_top3' if meet==2 else 'top3_probability'
 b=json.loads((p/('combination_verification_fixture.json' if meet==2 else 'combination_predictions.json')).read_text())
 for n in sorted({int(q[number_col]) for q in pred}):
  official=json.loads((OUT/f'official/meet{meet}_race{n}.json').read_text())
  rid=c.execute('SELECT r.id FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id WHERE rc.kra_meet_code=? AND r.race_date_local=? AND r.race_number=?',(meet,'2026-10-02',n)).fetchone()[0]
  results=[dict(x) for x in c.execute('SELECT e.horse_number,h.name_ko,rr.finish_position,rr.finish_time_ms FROM race_entries e JOIN horses h ON h.id=e.horse_id JOIN race_results rr ON rr.race_entry_id=e.id WHERE e.race_id=? ORDER BY rr.finish_position',(rid,))]
  top=[q['horse_number'] for q in results if 1<=q['finish_position']<=3]
  assert top==official['top3'],(meet,n,top,official['top3'])
  ranked=sorted([q for q in pred if int(q[number_col])==n],key=lambda q:int(q[rank_col]))
  sets=[[int(re.match(r'\d+',v).group()) for v in t['horses']] for t in next(z for z in b if int(z['race_number'])==n)['top10_sets']] if meet==2 else [z['horse_numbers'] for z in b if int(z['race_no'])==n and z['target']=='B']
  rec=human.get((meet,n));actual=set(top)
  first=int(ranked[0]['horse_number']);finish=next(r['finish_position'] for r in results if r['horse_number']==first)
  matching=[sorted(t) for t in rec['tickets'] if set(t)==actual] if rec else []
  row=dict(meet=meet,venue='제주' if meet==2 else '부산',race=n,result_order=top,result_set=sorted(top),results=results,trio_dividend=official['trio_dividend'],source_url=official['url'],model_first=first,model_first_top3_probability=float(ranked[0][prob_col]),model_first_finish=finish,model_B_first=sets[0],model_B_first_hit=set(sets[0])==actual,model_B_top6_hit=any(set(t)==actual for t in sets[:6]),model_B_actual_rank=next((i+1 for i,t in enumerate(sets) if set(t)==actual),None),actual_model_ranks=[int(next(q for q in ranked if int(q['horse_number'])==i)[rank_col]) for i in top],actual_model_probabilities=[float(next(q for q in ranked if int(q['horse_number'])==i)[prob_col]) for i in top],human=rec,human_hits=matching,human_first_hit=bool(rec and set(rec['tickets'][0])==actual))
  rows.append(row)
human_rows=[r for r in rows if r['human']]
metrics=dict(model_races=len(rows),human_races=len(human_rows),human_main_hits=sum(r['human_first_hit'] for r in human_rows),human_any_hits=sum(bool(r['human_hits']) for r in human_rows),model_B_first_hits=sum(r['model_B_first_hit'] for r in rows),model_B_top6_hits_all=sum(r['model_B_top6_hit'] for r in rows),model_B_top6_hits_matched=sum(r['model_B_top6_hit'] for r in human_rows),model_A_first_top3_hits=sum(r['model_first_finish']<=3 for r in rows),model_A_first_wins=sum(r['model_first_finish']==1 for r in rows),human_ticket_count=sum(len(r['human']['tickets']) for r in human_rows),latest_busan_human_hits=sum(bool(r['human_hits']) for r in rows if r['meet']==3 and r['race']>=7))
output=dict(target_date='2026-10-02',generated_at_kst=datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),metrics=metrics,rows=rows,evaluation_rule='Freeze prior recommendations; use latest bounded tickets when revised; do not count individually named horses or model reference as a human winning ticket; no post-result changes.',source_hashes={str(p.relative_to(ROOT)):hashlib.sha256((p/'runner_probabilities.csv').read_bytes()).hexdigest() for p in sources.values()})
(OUT/'audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
style='body{font:15px/1.7 -apple-system,"Apple SD Gothic Neo",sans-serif;background:#f3f6fa;color:#182c43;margin:0}main{max-width:1200px;margin:auto;padding:30px 22px}h1{font-size:30px}h2{font-size:21px;margin-top:30px}.box{background:white;border:1px solid #dce4ed;border-radius:10px;padding:20px;margin:16px 0}.metrics{display:flex;gap:20px;flex-wrap:wrap}.metrics b{font-size:26px;display:block}.small{font-size:13px;color:#617286}.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:12px 8px;border-bottom:1px solid #dde5ee;text-align:left;vertical-align:top}th{background:#eef3f9}a{color:#175bc4}.hit{color:#087255;font-weight:bold}.miss{color:#90511c}.note{border-left:4px solid #175bc4;padding-left:15px}summary{cursor:pointer;font-weight:650}details{margin:10px 0}p{word-break:keep-all}@media print{body{background:white}.wrap{overflow:visible}tr{break-inside:avoid}}'
parts=['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>2026.10.02 예측·실제 결과 비교</title><style>'+style+'</style><main><h1>2026년 10월 2일 · 예측과 실제 결과</h1><p>제주 1–7경주, 부산 3–9경주의 사전 모델 예측과 대화에서 제시한 인간 분석을 대조했습니다. 부산 1·2경주는 사전 예측 대상이 아니므로 제외했습니다. 기존 예측 파일과 추천 조합은 수정하지 않았습니다.</p>']
parts.append(f'<div class="box metrics"><div>내 첫 주력 삼복<b>{metrics["human_main_hits"]} / {metrics["human_races"]}</b></div><div>내 제시 조합 중 적중<b>{metrics["human_any_hits"]} / {metrics["human_races"]}</b></div><div>모델 1순위 입상<b>{metrics["model_A_first_top3_hits"]} / {metrics["model_races"]}</b></div><div>모델 삼복 1순위 적중<b>{metrics["model_B_first_hits"]} / {metrics["model_races"]}</b></div></div>')
parts.append('<p class="note">내 적중 두 경주는 부산 7·9경주의 축 이탈 대비 조합이다. 첫 주력 적중으로 표현하지 않는다. 개별 입상마를 모두 언급해도 실제 조합이 없었다면 실패로 기록한다.</p><div class="box"><h2>실제 추천을 한 12경주</h2><div class="wrap"><table><thead><tr><th>경주</th><th>실제 1→2→3착</th><th>내 첫 주력</th><th>제시 조합 수</th><th>삼복 평가</th><th>입상마 모델순</th></tr></thead><tbody>')
for r in human_rows:
 hit=bool(r['human_hits']);first='-'.join(map(str,r['human']['tickets'][0]));order=' → '.join(map(str,r['result_order']));label=('적중 '+ '-'.join(map(str,r['human_hits'][0]))) if hit else '실패'
 parts.append(f'<tr><td><a href="{E(r["source_url"])}">{r["venue"]} {r["race"]}</a></td><td>{order}</td><td>{first}</td><td>{len(r["human"]["tickets"])}</td><td class="{"hit" if hit else "miss"}">{label}</td><td>{" / ".join(map(str,r["actual_model_ranks"]))}</td></tr>')
parts.append('</tbody></table></div><p class="small">삼복은 순서 없는 집합으로 비교했다. 실제 착순과 삼복 번호의 표시 순서는 다를 수 있다. 인간 조합 수는 3–8개로 경주마다 다르며 마지막 부산 세 경주만 각각 6개다.</p></div>')
parts.append(f'<div class="box"><h2>모델과 비교할 때의 기준</h2><p>모델 삼복 상위 6개 포함 적중은 전체 14경주에서 {metrics["model_B_top6_hits_all"]}/14, 인간 추천이 있는 같은 12경주에서 {metrics["model_B_top6_hits_matched"]}/12였다. 인간 실제 추천은 2/12였다. 조합 수가 일정하지 않아 이 숫자만으로 우열을 확정하지 않는다.</p><p>모델 입상 1순위가 실제 입상한 경주는 8/14, 그 말이 우승한 경주는 4/14다. 우승과 삼복 적중은 별개다. 모델 삼복 1순위는 0/14였다. 하루 14경주로 모델의 장기 확률 보정 수준을 판단하지 않는다.</p></div>')
parts.append('<div class="box"><h2>경주별 복기와 당시 조합</h2>')
for r in human_rows:
 parts.append(f'<details><summary>{r["venue"]} {r["race"]}경주 · 실제 {"-".join(map(str,r["result_order"]))}</summary><p>{E(r["human"]["review"])}</p><p class="small">당시 조합: {" / ".join("-".join(map(str,t)) for t in r["human"]["tickets"])}</p><p class="small">공식 삼복 배당 {r["trio_dividend"]:.1f}배. 실제 베팅 금액·실행 내역이 없어 실현 수익은 계산하지 않았다. <a href="{E(r["source_url"])}">공식 성적 확인</a></p></details>')
parts.append('</div><div class="box"><h2>전체 사전 모델 14경주</h2><div class="wrap"><table><thead><tr><th>경주</th><th>실제</th><th>모델 입상 1순위·확률</th><th>실제 착순</th><th>모델 삼복 1순위</th><th>정답 B 순위</th></tr></thead><tbody>')
for r in rows:
 parts.append(f'<tr><td>{r["venue"]} {r["race"]}</td><td>{"→".join(map(str,r["result_order"]))}</td><td>{r["model_first"]} · {r["model_first_top3_probability"]*100:.1f}%</td><td>{r["model_first_finish"]}착</td><td>{"-".join(map(str,r["model_B_first"]))}</td><td>{r["model_B_actual_rank"] or "저장 상위 10개 밖"}</td></tr>')
parts.append('</tbody></table></div><p class="small">제주 1·2경주는 모델만 예측했고 인간의 확정 삼복 조합은 제시하지 않아 인간 적중률 분모에서 제외했다. 모든 결과는 로컬 DB와 마사회 공식 페이지의 1·2·3착 번호가 일치하는지 확인했다. 제주 모델 이력은 9월 12일까지, 부산 모델은 9월 20일까지였다는 사전 자료 제한을 유지했다.</p></div></main></html>')
(OUT/'20261002_예측과실제결과_비교.html').write_text('\n'.join(parts))
print(json.dumps(metrics,ensure_ascii=False));print(OUT/'20261002_예측과실제결과_비교.html')
c.close()
