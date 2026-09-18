from datetime import date
from horse_racing.analysis.jeju_steward_events import extract, historical_features

ROSTER = {i: dict(entry_id=i, horse_id=str(i), horse_name=n) for i,n in [(1,'가'),(2,'나'),(3,'다')]}


def test_explicit_victim_not_causer():
    x=extract('출발 후 약 150m 지점에서 ①“가” 기승기수 홍길동이 안으로 진로를 변경하는 과정에서 ②“나”의 주행이 불편했던 것에 대해 주의.',ROSTER)
    assert [a['horse_number'] for a in x['affected']]==[2]


def test_multi_horse_subject_and_name_validation():
    text='3-4코너 구간에서 ①“가”와 ②“나”는 안쪽 말들로 인해 바깥쪽으로 크게 돌며 주행하였음.'
    assert len(extract(text,ROSTER)['affected'])==2
    assert extract(text.replace('“나”','“잘못된이름”'),ROSTER)['affected']==[]


def test_statement_hypothetical_and_compound_abstain():
    assert extract('경주 결과 ①“가”는 크게 돌 것이 우려되어 선행했다고 진술.',ROSTER)['affected']==[]
    assert extract('①“가”는 진로가 막혔음. ②“나”도 주행이 불편하였음.',ROSTER)['affected']==[]


def test_missing_not_normal_and_T_minus_2():
    history=[dict(entry_id=i,horse_id='h',event_date=date(2025,1,i),event_number=1) for i in [1,3,4]]
    target=dict(entry_id=4,horse_id='h',event_date=date(2025,1,4))
    a=historical_features([target],history,set(),[])[0]
    assert a['previous_entry_id']==1 and a['previous_explicit_event'] is None
    b=historical_features([target],history,{('2025-01-01',1)},[])[0]
    assert b['previous_explicit_event'] is False and b['previous_report_known']
