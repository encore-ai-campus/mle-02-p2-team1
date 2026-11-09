"""Read a bounded Company ← WORKS_AT ← Person → PARTICIPATED_IN → Event path."""
import re
from datetime import datetime
from bulsae.graphrag.document_search import query_readonly, source_matches_document, source_text
from bulsae.graphrag.entity_resolution import TARGET_IDS

WORK_QUERY = """
MATCH (c:BulsaeCompany)<-[w:WORKS_AT]-(p:BulsaePerson)
WHERE c.name=$name AND c.company_id IN $target_ids
  AND none(l IN labels(c)+labels(p) WHERE l STARTS WITH 'B_')
  AND (w.pipeline_version='document-kg-v1' OR
       (p.person_id='PERSON-CANDIDATE-NEWS-46c70231e3ee18db' AND w.observation_id STARTS WITH 'REL-CANDIDATE-'))
  AND coalesce(w.verification_status,'검토 전') <> '검토 필요'
  AND coalesce(w.bulsae_audit_status_v1,'') <> '검토 필요'
MATCH (p)-[path:NORMALIZED_AS*0..3]->(root:BulsaePerson)
WHERE all(x IN path WHERE x.normalization_version='identity-resolution-v1'
          AND coalesce(x.bulsae_audit_status_v1,'') <> '검토 필요')
  AND none(l IN labels(root) WHERE l STARTS WITH 'B_')
  AND NOT EXISTS { MATCH (root)-[out:NORMALIZED_AS {normalization_version:'identity-resolution-v1'}]->()
                   WHERE coalesce(out.bulsae_audit_status_v1,'') <> '검토 필요' }
MATCH (d:BulsaeDocument {document_id:w.source_document_id})
WHERE none(l IN labels(d) WHERE l STARTS WITH 'B_')
RETURN DISTINCT elementId(root) AS root_id,p.name AS person,w.source_document_id AS document_id,
       coalesce(w.kg_observation_id,w.observation_id,elementId(w)) AS observation_id,
       c.company_id AS company_id,p.person_id AS person_id,
       w.evidence_json AS evidence_json,w.evidence AS evidence,d.content AS content,d.original_url AS url,d.title AS title
LIMIT 1000
"""

EVENT_QUERY = """
UNWIND $roots AS root_id
MATCH (p:BulsaePerson)-[path:NORMALIZED_AS*0..3]->(root:BulsaePerson)
WHERE elementId(root)=root_id AND all(x IN path WHERE x.normalization_version='identity-resolution-v1'
      AND coalesce(x.bulsae_audit_status_v1,'') <> '검토 필요')
  AND none(l IN labels(p)+labels(root) WHERE l STARTS WITH 'B_')
MATCH (p)-[r:PARTICIPATED_IN]->(e:BulsaeEvent)
WHERE (r.pipeline_version='document-kg-v1' OR
       (p.person_id='PERSON-CANDIDATE-NEWS-46c70231e3ee18db' AND r.observation_id STARTS WITH 'REL-CANDIDATE-'))
  AND coalesce(r.verification_status,'검토 전') <> '검토 필요'
  AND coalesce(r.bulsae_audit_status_v1,'') <> '검토 필요'
  AND none(l IN labels(e) WHERE l STARTS WITH 'B_')
MATCH (d:BulsaeDocument {document_id:r.source_document_id})
WHERE none(l IN labels(d) WHERE l STARTS WITH 'B_')
RETURN DISTINCT root_id,p.name AS person,e.name AS event,r.source_document_id AS document_id,
       coalesce(r.kg_observation_id,r.observation_id,elementId(r)) AS observation_id,
       coalesce(e.event_id,e.candidate_id) AS event_id,coalesce(p.person_id,p.candidate_id) AS person_id,
       d.published_at AS published_at, r.reported_status AS reported_status,
       r.evidence_json AS evidence_json,r.evidence AS evidence,d.content AS content,d.original_url AS url,d.title AS title
LIMIT 1000
"""


def work_role_supported(person, company, role, text):
    label = r'(?:대표이사|대표)' if role == 'ceo' else r'회장'
    if not person or not company:
        return False
    pattern = re.escape(person) + r'\s+' + re.escape(company) + r'\s+' + label
    reverse = re.escape(company) + r'\s+' + re.escape(person) + r'\s*' + label
    return bool(re.search(pattern, text) or re.search(reverse, text))


def event_year_candidate(event, text, published_at=None):
    """Filter by event time, never by publication year alone. No exact date invention."""
    explicit = re.findall(r'(?<!\d)(20\d{2})(?!\d)', event or '')
    if len(set(explicit)) == 1:
        return int(explicit[0])
    try:
        published = datetime.fromisoformat(str(published_at).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None
    # Resolve only a date in the same source line as the named event.
    lines = [line for line in text.splitlines() if event and event in line]
    years = set()
    for line in lines:
        if re.search(r'지난해\s*\d{1,2}월', line):
            years.add(published.year - 1)
        elif re.search(r'(?:올해|지난)\s*\d{1,2}월', line):
            month = int(re.search(r'(?:올해|지난)\s*(\d{1,2})월', line)[1])
            if 1 <= month <= published.month:
                years.add(published.year)
        elif re.search(r'(?:지난\s*)?\b(\d{1,2})일\s*(?:열린|개최)', line):
            day = int(re.search(r'(?:지난\s*)?\b(\d{1,2})일\s*(?:열린|개최)', line)[1])
            if 1 <= day <= published.day:
                years.add(published.year)
    return next(iter(years)) if len(years) == 1 else None


def event_supported(person, event, year, text, published_at=None):
    if not person or not event or person not in text or event not in text:
        return False
    if year is not None and event_year_candidate(event, text, published_at) != year:
        return False
    return any(word in text for word in ('참석','참여','참가','발표','발언','공개','설명','밝혔','밝힌','말했','말했다','환영인사','인사말','단상에 섰'))


def fetch_executive_events(db, name, role, year):
    works = [r.data() for r in query_readonly(db, WORK_QUERY, name=name, target_ids=TARGET_IDS)]
    trusted = {}
    for row in works:
        if not row.get('url') or not source_matches_document(row, row.get('content')):
            continue
        if work_role_supported(row.get('person'), name, role, source_text(row)):
            trusted[(row['root_id'], row['document_id'], row['person'])] = row
    if not trusted:
        return []
    roots = list({key[0] for key in trusted})
    events = [r.data() for r in query_readonly(db, EVENT_QUERY, roots=roots)]
    paths, seen = [], set()
    for event in events:
        key = (event['root_id'], event['document_id'], event.get('person'))
        work = trusted.get(key)
        if not work or not event.get('url') or not source_matches_document(event,event.get('content')):
            continue
        quote = source_text(event)
        if event.get('reported_status') == '예정':
            continue
        if not event_supported(event.get('person'),event.get('event'),year,quote,event.get('published_at')):
            continue
        identity = (event['person'],event['event'],event['document_id'])
        if identity in seen:
            continue
        seen.add(identity)
        paths.append({'person':event['person'], 'event':event['event'], 'company':name,
                      'event_year':event_year_candidate(event['event'],quote,event.get('published_at')),
                      'person_id':event.get('person_id'), 'company_id':work.get('company_id'), 'event_id':event.get('event_id'),
                      'root_id':event['root_id'], 'work_observation_id':work.get('observation_id'),
                      'event_observation_id':event.get('observation_id'),
                      'document_id':event['document_id'], 'url':event['url'], 'title':event.get('title'),
                      'work_evidence':source_text(work), 'event_evidence':quote})
    return paths


def event_context_evidence(paths):
    """Pass only source-checked paths to the existing answer and review steps."""
    rows, counts = [], {}
    for path in paths:
        key = (path['company'], path['person'], path['event'],path.get('event_year'))
        if key not in counts and len(counts) >= 10:
            continue
        if counts.get(key, 0) >= 1:
            continue
        counts[key] = counts.get(key, 0) + 1
        lines = list(dict.fromkeys(path['work_evidence'].splitlines() + path['event_evidence'].splitlines()))
        rows.append({**path, 'representative_id': path.get('root_id') or path.get('person_id') or path['person'],
                     'relation': 'PARTICIPATED_IN', 'evidence': '\n'.join(lines), 'source_verified': True})
    return rows


def render_paths(paths, role, year):
    if not paths:
        return '인물의 직책과 행사 참여를 같은 기사에서 함께 확인한 근거를 찾지 못했어요.'
    role_name = '대표' if role == 'ceo' else '회장'
    lines = ['수집한 기사에 따르면 다음과 같아요.']
    groups = {}
    for row in paths:
        groups.setdefault((row['company'],row['person'],row['event'],row.get('event_year')), []).append(row)
    for (company,person,event,_), records in list(groups.items())[:10]:
        lines.append(f"{company}의 {role_name}로 소개된 {person} 님이 {event}에 참여한 것으로 보도됐어요.")
        for row in records[:3]:
            snippets = row['event_evidence'].splitlines()
            snippet = next((s for s in snippets if not s.startswith('![') and person in s and event in s),
                           row['event_evidence'])[:350]
            work_lines = row['work_evidence'].splitlines()
            work = next((s for s in work_lines if not s.startswith('![')
                         and work_role_supported(person, company, role, s)), row['work_evidence'])[:350]
            if work.strip() == snippet.strip():
                evidence = f"  직책·행사 근거: {work}"
            else:
                evidence = f"  직책 근거: {work}\n  행사 근거: {snippet}"
            lines.append(f"  근거 기사: {row['document_id']} | {row['url']}\n{evidence}")
    if len(groups) > 10:
        lines.append(f'행사 관계 후보 {len(groups)}건 중 10건을 표시했어요.')
    return '\n\n'.join(lines)
