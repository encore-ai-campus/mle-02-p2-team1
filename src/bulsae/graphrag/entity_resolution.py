"""Find explicit person/company names in a question using only Bulsae nodes."""
import re

from bulsae.graphrag.document_search import query_readonly

TARGET_IDS = ['COMPANY-AMOREPACIFIC', 'COMPANY-INNISFREE', 'COMPANY-ESPOIR',
              'COMPANY-ETUDE', 'COMPANY-PACIFICTECH', 'COMPANY-AMOSPROFESSIONAL', 'COMPANY-COSRX']

NAME_QUERY = """
MATCH (n)
WHERE (n:BulsaePerson OR n:BulsaeCompany)
  AND none(label IN labels(n) WHERE label STARTS WITH 'B_')
  AND (n.pipeline_version='document-kg-v1' OR n.company_id IN $target_ids
       OR n.person_id='PERSON-CANDIDATE-NEWS-46c70231e3ee18db')
  AND n.name IS NOT NULL AND size(n.name) >= 2
  AND (toLower(replace($question,' ','')) CONTAINS toLower(replace(n.name,' ',''))
       OR (n.legal_name IS NOT NULL AND toLower(replace($question,' ','')) CONTAINS toLower(replace(n.legal_name,' ',''))))
RETURN DISTINCT n.name AS name, n.legal_name AS legal_name,
       CASE WHEN n:BulsaePerson THEN 'person' ELSE 'company' END AS kind
"""

# Korean particles may follow a name without a space. Do not match prefixes of
# longer names such as 아모레퍼시픽 inside 아모레퍼시픽그룹.
SUFFIX = ('에서', '에게', '부터', '까지', '으로', '으로는', '처럼', '보다',
          '대표', '회장', '사장', '이사', '님', '의', '은', '는', '이', '가',
          '을', '를', '와', '과', '도', '에', '로', '께', '랑', '하고')
COMPARISON_WORDS = ('비교', '차이', '각각', '다른 점', '어느 기업', '어느 회사', '어느 쪽',
                    '어떻게 달라', '더 큰', '더 높', '더 많은')


def mention_spans(question, name):
    if not name or len(name.strip()) < 2:
        return []
    spans = []
    pattern = r'\s*'.join(re.escape(c) for c in name if not c.isspace())
    for match in re.finditer(pattern, question, re.IGNORECASE):
        start, end = match.span()
        before = question[start-1] if start else ''
        after = question[end:]
        if before and re.match(r'[가-힣A-Za-z0-9]', before):
            continue
        if after and re.match(r'[가-힣A-Za-z0-9]', after[0]) and not after.startswith(SUFFIX):
            continue
        spans.append((start,end))
    return spans


def choose_entity(question, records):
    matches = []
    for record in records:
        name, kind = record.get('name'), record.get('kind')
        if kind not in ('person', 'company') or not name:
            continue
        if kind == 'person' and ('관계자' in name or name in ('대표', '회장', '사장')):
            continue
        for alias in {name, record.get('legal_name')} - {None, ''}:
            for start,end in mention_spans(question, alias):
                matches.append({'name':name, 'kind':kind, 'start':start, 'end':end, 'matched':alias})
    # A full, longer name wins only when it covers the shorter name's span.
    matches = [m for m in matches if not any(
        o['start'] <= m['start'] and o['end'] >= m['end'] and
        o['end'] - o['start'] > m['end'] - m['start'] for o in matches)]
    unique = {(m['kind'], m['name']):m for m in matches}
    people = [m for m in unique.values() if m['kind'] == 'person']
    companies = [m for m in unique.values() if m['kind'] == 'company']
    comparison = any(word in question for word in COMPARISON_WORDS)
    indirect_comparison = any(w in question for w in ('협력한 곳', '협력한 기업', '연결된 기업'))
    if comparison and not people and not indirect_comparison:
        if 2 <= len(companies) <= 4:
            ordered = sorted(companies, key=lambda m:m['start'])
            return {'status':'resolved_compare',
                    'entities':[{'name':m['name'], 'kind':'company'} for m in ordered]}
        return {'status':'comparison_needs_names',
                'candidates':[{'name':m['name'], 'kind':'company'} for m in companies]}
    if len(people) == 1 and len(companies) <= 1:
        # A named person is the target for event/attendance questions; the company
        # mention is retained as context, not used as proof of that person's identity.
        if not companies or any(word in question for word in ('행사', '참석', '참여')):
            return {'status':'resolved', 'name':people[0]['name'], 'kind':'person',
                    'company_context':companies[0]['name'] if companies else None}
    if len(companies) == 1 and not people:
        return {'status':'resolved', 'name':companies[0]['name'], 'kind':'company'}
    if 2 <= len(companies) <= 4 and not people:
        return {'status':'resolved_multi', 'entities':[
            {'name':m['name'], 'kind':'company'} for m in sorted(companies, key=lambda m:m['start'])]}
    candidates = sorted([{'name':m['name'], 'kind':m['kind']} for m in unique.values()],
                        key=lambda item:(item['kind'],item['name']))
    return {'status':'ambiguous' if candidates else 'not_found', 'candidates':candidates}


def resolve_question(db, question):
    if not question.strip():
        return {'status':'not_found', 'candidates':[]}
    records = query_readonly(db, NAME_QUERY, question=re.sub(r'\s+', ' ', question), target_ids=TARGET_IDS)
    return choose_entity(question, [r.data() for r in records])
