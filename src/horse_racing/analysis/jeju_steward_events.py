"""Conservative, provenance-preserving route event extraction; not an NLP oracle."""
import hashlib
import re
from datetime import timedelta

MARKERS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯'
MENTION = re.compile(r'([' + MARKERS + r'])\s*[“「"]([^”」"]+)[”」"]')
SIGNAL = re.compile(r'진로.{0,20}(?:막|여의치)|갇|주행이 불편|크게 돌')
RESTRICT = re.compile(r'진로.{0,20}(?:막|여의치)|갇')


def norm(text):
    return re.sub(r'\s+', '', str(text or ''))


def extract(bullet, roster):
    """Roster maps number to entry_id, horse_id, horse_name; abstain on doubt.

    Only the first sentence is eligible. Later affected horses force review.
    Mention is deliberately distinct from affected role.
    """
    mentions = []
    for m in MENTION.finditer(bullet):
        number = MARKERS.index(m[1]) + 1
        r = roster.get(number)
        mentions.append(dict(number=number, name=m[2], start=m.start(), end=m.end(),
            matched=bool(r and norm(r['horse_name']) == norm(m[2])),
            entry_id=r['entry_id'] if r else None, horse_id=r['horse_id'] if r else None))
    signal = SIGNAL.search(bullet)
    if not signal:
        return None
    source_kind = 'rider_statement' if '진술' in bullet else 'steward_narrative'
    prefix = bullet[:mentions[0]['start']] if mentions else bullet[:80]
    segment = 'finish_straight' if '결승선' in prefix else 'corner' if '코너' in prefix else 'after_start' if '출발' in prefix else 'unknown'
    result = dict(raw_bullet=bullet, bullet_sha256=hashlib.sha256(bullet.encode()).hexdigest(),
        mentions=mentions, source_kind=source_kind, segment=segment, segment_raw=prefix.strip(),
        distance_markers_m=re.findall(r'약\s*(\d+)\s*m', prefix), affected=[],
        status='review_required', rule=None, event_types=[])
    if source_kind == 'rider_statement':
        result['rule'] = 'statement_requires_review'
        return result
    sentence = bullet.split('.')[0]
    if SIGNAL.search(bullet[len(sentence)+1:]):
        result['rule'] = 'multiple_event_sentences'
        return result
    ms = [m for m in mentions if m['start'] < len(sentence)]
    victims = []
    # An explicitly named possessive subject anchors discomfort to the victim,
    # even when another horse caused the incident earlier in the sentence.
    for i, m in enumerate(ms):
        end = ms[i+1]['start'] if i+1 < len(ms) else len(sentence)
        tail = sentence[m['end']:end]
        if re.match(r'의\s*주행이\s*불편', tail):
            group = [m]
            j = i - 1
            while j >= 0 and re.fullmatch(r'\s*(?:과|와|,|및)\s*', sentence[ms[j]['end']:ms[j+1]['start']]):
                group.insert(0, ms[j]); j -= 1
            victims.extend(group)
    if victims:
        result['rule'] = 'explicit_affected_possessive'
        result['event_types'] = ['running_interference']
        # Indirectly affected preceding horses ('A가 밀리며 B의 ...') need review.
        before = sentence[:min(m['start'] for m in victims)]
        if '밀리' in before:
            result['rule'] = 'multiple_affected_chain_requires_review'
            return result
    else:
        sig = SIGNAL.search(sentence)
        prior = [m for m in ms if sig and m['end'] <= sig.start()]
        if not prior:
            return result
        # Direct subject(s), with no intervening named horse or causal subject.
        last = prior[-1]
        tail = sentence[last['end']:sig.start()]
        direct = bool(re.match(r'\s*(?:은|는|가|이)\s', tail) or re.match(r'\s*기승기수\s*\S+(?:은|는)\s', tail))
        if not direct or re.search(r'과정에서|나가|나와|들어가|우려|계획', tail):
            return result
        group = [last]
        j = len(prior) - 2
        while j >= 0 and re.fullmatch(r'\s*(?:과|와|,|및)\s*', sentence[prior[j]['end']:prior[j+1]['start']]):
            group.insert(0, prior[j]); j -= 1
        # Earlier named horses imply a multi-actor sentence; hold it for review.
        if len(group) != len(prior):
            return result
        victims = group
        result['rule'] = 'direct_subject_route_event'
        result['event_types'] = ([] if not RESTRICT.search(sentence) else ['route_restriction'])
        if '크게 돌' in sentence:
            result['event_types'].append('wide_trip')
        if '주행이 불편' in sentence:
            result['event_types'].append('running_interference')
    if not victims or not all(m['matched'] for m in victims):
        result['rule'] = 'roster_mismatch'
        return result
    result['affected'] = list({m['entry_id']: dict(entry_id=m['entry_id'], horse_id=m['horse_id'],
                         horse_number=m['number'], horse_name=m['name'], role='affected') for m in victims}.values())
    result['status'] = 'explicit_rule_match'
    return result


def historical_features(targets, history, report_keys, events):
    """Previous start only; unknown reports stay unknown, never 'normal'."""
    by_horse = {}
    event_by_entry = {}
    for e in events:
        if e['status'] == 'explicit_rule_match' and e['field'] == 'judgement':
            for a in e['affected']:
                event_by_entry.setdefault(a['entry_id'], []).append(e)
    for r in history:
        by_horse.setdefault(r['horse_id'], []).append(r)
    for rows in by_horse.values():
        rows.sort(key=lambda r: (r['event_date'], r['entry_id']))
    out = []
    for t in targets:
        past = [r for r in by_horse[t['horse_id']] if r['event_date'] <= t['event_date']-timedelta(days=2)]
        p = past[-1] if past else None
        key = (p['event_date'].isoformat(), p['event_number']) if p else None
        known = key in report_keys
        es = event_by_entry.get(p['entry_id'], []) if p else []
        types = set(x for e in es for x in e['event_types'])
        out.append(dict(entry_id=t['entry_id'], previous_entry_id=p['entry_id'] if p else None,
            previous_date=p['event_date'] if p else None,
            previous_report_known=known, previous_explicit_event=bool(es) if known else None,
            previous_route_restriction=('route_restriction' in types) if known else None,
            previous_wide_trip=('wide_trip' in types) if known else None,
            previous_running_interference=('running_interference' in types) if known else None,
            days_since_previous=(t['event_date']-p['event_date']).days if p else None,
            source_event_ids=[e['event_id'] for e in es],
            availability_basis='race_date_T_minus_2_assumption_publication_time_unverified'))
    return out
