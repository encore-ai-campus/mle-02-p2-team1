"""Read collected company information without creating graph relationships."""
import json
from bulsae.graphrag.document_search import query_readonly
from bulsae.graphrag.entity_resolution import TARGET_IDS


def is_business_question(question):
    if any(word in question for word in ('전략', '협력', '관계', '매출', '재무', '비교', '행사', '대표', '앞으로', '키우', '육성', '목표', '계획', '성장')):
        return False
    return any(word in question for word in ('어떤 사업', '무슨 사업', '주요 사업', '사업 내용',
                                               '어떤 회사', '무슨 회사', '어떤 일을', '무슨 일을'))


def fetch_company_business(db, name):
    rows = query_readonly(db, '''MATCH (c:BulsaeCompany), (i:BulsaeCompanyInfo)
      WHERE c.name=$name AND c.company_id IN $target_ids AND i.company_id=c.company_id
        AND none(label IN labels(c)+labels(i) WHERE label STARTS WITH 'B_')
      RETURN c.name AS name, c.company_id AS company_id, i.main_business AS business, i.field_sources_json AS sources''',
      name=name, target_ids=TARGET_IDS)
    return [r.data() for r in rows]


def render_company_business(name, rows):
    valid = [r for r in rows if r.get('name') == name and r.get('business') and r.get('sources')]
    if len(valid) != 1:
        return {'answer':f'{name}의 주요 사업 정보와 출처를 확인하지 못했어요.', 'status':'insufficient_evidence'}
    row = valid[0]
    try:
        fields = json.loads(row['sources'])
        sources = [s for s in fields.get('main_business', []) if s.get('original_url')]
    except (ValueError, TypeError, AttributeError):
        sources = []
    if not sources:
        return {'answer':f'{name}의 주요 사업 정보 출처를 확인하지 못했어요.', 'status':'insufficient_evidence'}
    citations = '\n'.join(f"- {s.get('title') or s.get('source_name') or '출처'} | {s['original_url']}" for s in sources)
    return {'answer':f"{row['business']}\n\n출처:\n{citations}", 'status':'answered', 'trace_kind':'company_info',
            'structured_sources':[{'document_id':row.get('company_id'), 'title':s.get('title') or s.get('source_name') or '기업 정보',
                'url':s['original_url'], 'evidence':row['business'], 'from_name':name,
                'source_file':'company_info.jsonl'} for s in sources]}
