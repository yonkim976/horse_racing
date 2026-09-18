"""Versioned, narrow role improvements; v1 artifacts remain immutable."""
import hashlib
import re

from horse_racing.analysis.jeju_steward_events import extract as extract_v1, MENTION, MARKERS, norm

JOIN = re.compile(r'\s*(?:과|와|,|및)\s*')
SENTENCE = re.compile(r'(?<!\d)\.(?!\d)')


def extract_events(bullet, roster):
    """Return independently attributed route and start-delay events.

    Explicit mutual contact participants are affected participants, not a claim
    of innocence or quantified loss. Statements and identity conflicts abstain.
    """
    ms=[]
    for m in MENTION.finditer(bullet):
        n=MARKERS.index(m[1])+1;r=roster.get(n)
        ms.append(dict(number=n,name=m[2],start=m.start(),end=m.end(),
            matched=bool(r and norm(r['horse_name'])==norm(m[2])),
            entry_id=r['entry_id'] if r else None,horse_id=r['horse_id'] if r else None))
    def affected(group):
        return list({m['entry_id']:dict(entry_id=m['entry_id'],horse_id=m['horse_id'],
            horse_number=m['number'],horse_name=m['name'],role='affected') for m in group}.values())
    source='official_decision_with_statement' if '심판위원' in bullet and '진술' in bullet else 'rider_statement' if '진술' in bullet else 'steward_narrative'
    original=extract_v1(bullet,roster)
    events=[]
    route=original
    # In an official review, only observation sentences before the statement/
    # deliberation sentence are eligible. Never parse an interview as fact.
    if source=='official_decision_with_statement':
        first=SENTENCE.split(bullet)[0]
        if '진술' not in first:
            route=extract_v1(first,roster)
            if route:
                route['source_kind']=source
    if route:
        route=dict(route,raw_bullet=bullet,bullet_sha256=hashlib.sha256(bullet.encode()).hexdigest())
        # Explicit A,B,C mutually contacted. Handles omitted intermediate victims
        # without assigning every mentioned horse in the paragraph as affected.
        if route['status']=='explicit_rule_match' and source!='rider_statement':
            extra=[]
            for i,m in enumerate(ms):
                tail=bullet[m['end']:ms[i+1]['start'] if i+1<len(ms) else len(bullet)]
                if re.match(r'\s*(?:가|이|는|은)\s*서로\s*접촉',tail):
                    group=[m];j=i-1
                    while j>=0 and JOIN.fullmatch(bullet[ms[j]['end']:ms[j+1]['start']]):
                        group.insert(0,ms[j]);j-=1
                    if len(group)>=2:
                        if not all(x['matched'] for x in group):
                            route.update(status='review_required',affected=[],rule='contact_group_identity_conflict');break
                        extra.extend(affected(group))
            if route['status']=='explicit_rule_match' and extra:
                route['affected']=list({a['entry_id']:a for a in route['affected']+extra}.values())
                route['rule']='explicit_affected_plus_mutual_contact'
        events.append(route)
    # New start-delay extraction: direct named subject within its own clause.
    # Only explicitly late starts; poor performance/condition is not inferred.
    if re.search(r'출발이\s*늦',bullet):
        e=dict(raw_bullet=bullet,bullet_sha256=hashlib.sha256(bullet.encode()).hexdigest(),
               mentions=ms,source_kind=source,segment='start',segment_raw='출발이 늦',
               distance_markers_m=[],affected=[],status='review_required',rule='start_delay_review',
               event_types=['start_delay'])
        if source=='steward_narrative' and bullet.lstrip().startswith('출발'):
            victims=[]
            for i,m in enumerate(ms):
                tail=bullet[m['end']:ms[i+1]['start'] if i+1<len(ms) else len(bullet)]
                tail=SENTENCE.split(tail)[0].split(',')[0]
                if re.match(r'\s*(?:은|는|이|가)\s',tail) and re.search(r'출발이\s*늦',tail):
                    group=[m];j=i-1
                    while j>=0 and JOIN.fullmatch(bullet[ms[j]['end']:ms[j+1]['start']]):
                        group.insert(0,ms[j]);j-=1
                    victims.extend(group)
            if victims and all(m['matched'] for m in victims):
                e.update(status='explicit_rule_match',affected=affected(victims),rule='explicit_start_delay_subject')
        events.append(e)
    return events
