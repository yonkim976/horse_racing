from horse_racing.analysis.jeju_steward_events_v2 import extract_events

R={i:dict(entry_id=i,horse_id=str(i),horse_name=n) for i,n in enumerate(['가마','나마','다마','라마'],1)}


def test_mutual_contact_roles_and_cause_not_all_mentioned():
    e=extract_events('3코너에서 ④“라마”의 주행이 불편했던 것에 대해, ①“가마”가 안으로 들어가 ②“나마”, ③“다마”, ④“라마”가 서로 접촉한 것이 원인으로 판단.',R)[0]
    assert {a['entry_id'] for a in e['affected']}=={2,3,4}


def test_official_review_is_not_entirely_interview():
    e=extract_events('결승선에서 ②“나마”의 주행이 불편하였음. 심판위원은 기수 진술 및 경주화면을 종합해 판단.',R)[0]
    assert e['status']=='explicit_rule_match'
    assert e['source_kind']=='official_decision_with_statement'
    assert extract_events('기수는 ②“나마”의 주행이 불편했다고 진술.',R)[0]['status']=='review_required'


def test_start_group_not_neighbour_or_interview():
    es=extract_events('출발 시 ①“가마”와 ②“나마”는 출발이 늦었고, ③“다마”는 바깥으로 나갔음. ④“라마”는 출발이 늦었음.',R)
    e=[e for e in es if 'start_delay' in e['event_types']][0]
    assert {a['entry_id'] for a in e['affected']}=={1,2,4}
    e=extract_events('경주 결과 ①“가마”는 출발이 늦어 부진했다고 기수가 진술.',R)[0]
    assert e['status']=='review_required'


def test_identity_conflict_abstains():
    e=extract_events('출발 시 ②“가마”는 출발이 늦었음.',R)[0]
    assert e['affected']==[] and e['status']=='review_required'
