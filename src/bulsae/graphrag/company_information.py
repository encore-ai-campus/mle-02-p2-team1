"""Read collected company information without creating graph relationships."""
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from bulsae.graphrag.document_search import query_readonly
from bulsae.graphrag.entity_resolution import TARGET_IDS, mention_spans


def is_business_question(question):
    if any(word in question for word in ('전략', '협력', '관계', '매출', '재무', '비교', '행사', '대표', '앞으로', '키우', '육성', '목표', '계획', '성장')):
        return False
    return any(word in question for word in ('어떤 사업', '무슨 사업', '주요 사업', '사업 내용',
        '어떤 회사', '무슨 회사', '어떤 일을', '무슨 일을', '기업에 대해', '회사에 대해',
        '기업 소개', '기업소개', '회사 소개', '회사소개', '기업 정보', '기업정보'))


def fetch_company_business(db, name):
    rows = query_readonly(db, '''MATCH (c:BulsaeCompany), (i:BulsaeCompanyInfo)
      WHERE c.name=$name AND c.company_id IN $target_ids AND i.company_id=c.company_id
        AND none(label IN labels(c)+labels(i) WHERE label STARTS WITH 'B_')
      RETURN c.name AS name, c.company_id AS company_id, c.legal_name AS legal_name,
             i.industry AS industry, i.established_date AS established_date,
             i.employee_count AS employee_count, i.listing_status AS listing_status,
             i.main_business AS business, i.field_sources_json AS sources''',
      name=name, target_ids=TARGET_IDS)
    return [r.data() for r in rows]


def render_company_business(name, rows):
    valid = [r for r in rows if r.get('name') == name]
    if len(valid) != 1:
        return {'answer':f'{name}의 주요 사업 정보와 출처를 확인하지 못했어요.', 'status':'insufficient_evidence'}
    row = valid[0]
    try:
        fields = json.loads(row.get('sources') or '{}')
        sources = [s for s in fields.get('main_business', []) if isinstance(s, dict) and s.get('original_url')]
    except (ValueError, TypeError, AttributeError):
        fields, sources = {}, []
    citations = '\n'.join(f"- {s.get('title') or s.get('source_name') or '출처'} | {s['original_url']}" for s in sources)
    profile = []
    for key, label in [('legal_name','법인명'),('industry','업종'),('established_date','설립일'),
                       ('employee_count','직원 수'),('listing_status','상장 여부')]:
        value = row.get(key)
        if value is None or isinstance(value, bool) or not str(value).strip():
            continue
        field_sources = fields.get(key, []) if isinstance(fields, dict) else []
        url = next((s.get('original_url') for s in field_sources if isinstance(s, dict) and s.get('original_url')), None)
        profile.append({'label':label, 'value':str(value) + ('명' if key == 'employee_count' else ''),
                        'field':key, 'source_url':url, 'source_file':'companies.jsonl' if key == 'legal_name' else 'company_info.jsonl'})
    business = row.get('business') if sources else None
    if not business and not profile:
        return {'answer':f'{name}의 기업 정보와 출처를 확인하지 못했어요.', 'status':'insufficient_evidence'}
    return {'answer':f"{business}\n\n출처:\n{citations}" if business else f'{name}의 주요 사업 정보는 확인하지 못했어요.', 'status':'answered', 'trace_kind':'company_info',
            'company_profile':profile, 'company_business':business,
            'structured_sources':[{'document_id':row.get('company_id'), 'title':s.get('title') or s.get('source_name') or '기업 정보',
                'url':s['original_url'], 'evidence':business, 'from_name':name,
                'source_file':'company_info.jsonl'} for s in sources if business]}


RECENT_QUERY = '''
MATCH (c:BulsaeCompany), (d:BulsaeDocument)
WHERE c.name=$name AND c.company_id IN $target_ids AND c.company_id IN d.company_ids
  AND d.document_id STARTS WITH 'NEWS-' AND d.published_at IS NOT NULL
  AND d.title IS NOT NULL AND d.content IS NOT NULL AND d.original_url IS NOT NULL
  AND none(label IN labels(c)+labels(d) WHERE label STARTS WITH 'B_')
RETURN d.document_id AS document_id, d.title AS title, d.original_url AS url,
       d.published_at AS published_at, d.content AS content
ORDER BY d.published_at DESC LIMIT 200
'''


def recent_candidates(rows, name, now=None, limit=12):
    """Rank articles by publication date; it is not the event date."""
    now = now or datetime.now(timezone.utc)
    chosen = []
    for row in rows:
        try:
            published = datetime.fromisoformat(str(row.get('published_at','')).replace('Z','+00:00'))
            if published.tzinfo is None:
                continue
            if published > now:
                continue
        except (ValueError, TypeError):
            continue
        title, content = row.get('title') or '', row.get('content') or ''
        if not row.get('document_id') or not row.get('url') or not mention_spans(title, name):
            continue
        if not mention_spans(content, name):
            continue
        chosen.append((published, row))
    chosen.sort(key=lambda item: item[0], reverse=True)
    result, titles = [], []
    for _, row in chosen:
        title = re.sub(r'[^가-힣a-z0-9]', '', row['title'].lower())
        if any(SequenceMatcher(None,title,old).ratio() >= .85 for old in titles):
            continue
        content = row['content']
        mention = mention_spans(content, name)[0]
        start = max(0, mention[0] - 250)
        excerpt = content[start:start+6000]
        result.append({'document_id':row['document_id'], 'title':row['title'], 'url':row['url'],
                       'published_at':row['published_at'], 'evidence':excerpt, 'source_verified':True,
                       'source_kind':'document', 'relation':'DOCUMENT_EVIDENCE',
                       'representative_id':'document:' + row['document_id']})
        titles.append(title)
        if len(result) >= limit:
            break
    return result


def fetch_recent_company_news(db, name, generate, review):
    from bulsae.graphrag.document_search import validate_answer_claims
    rows = recent_candidates([r.data() for r in query_readonly(db, RECENT_QUERY, name=name, target_ids=TARGET_IDS)], name)
    if not rows:
        return []
    question = (f'{name}의 최근 기사에서 확인되는 기업의 사업·전략·행사·실적 소식을 소개해줘. '
                '기업과 직접 관련된 사실만 기사별로 설명하고, 기사 발행일을 사건이 발생한 날짜로 쓰지 마라.')
    claims = validate_answer_claims(generate(question, rows), rows)
    approved = review(question, claims, rows) if claims else set()
    items, seen = [], set()
    for index, claim in enumerate(claims):
        if index not in approved or not mention_spans(claim.exact_quote, name):
            continue
        row = rows[claim.evidence_index]
        if row['document_id'] in seen:
            continue
        seen.add(row['document_id'])
        items.append({'heading':claim.heading or row['title'], 'text':claim.text, 'kind':claim.kind,
                      'document_id':row['document_id'], 'title':row['title'], 'url':row['url'],
                      'published_at':row['published_at'], 'evidence':claim.exact_quote,
                      'source_kind':'document'})
    order = {r['document_id']: i for i,r in enumerate(rows)}
    unique = []
    for item in sorted(items,key=lambda item:order[item['document_id']]):
        def quoted_entities(text):
            return {re.sub(r'\s+', '', token).lower() for token in
                    re.findall(r"[‘'\"「]([^’'\"」]{4,60})[’'\"」]", text)}
        entities = quoted_entities(item['heading'] + ' ' + item['text'])
        title = re.sub(r'[^가-힣a-z0-9]', '', item['heading'].lower())
        duplicate = any(
            bool(entities & quoted_entities(old['heading'] + ' ' + old['text'])) or
            (title and SequenceMatcher(None, title, re.sub(r'[^가-힣a-z0-9]', '', old['heading'].lower())).ratio() >= .8)
            for old in unique)
        if not duplicate:
            unique.append(item)
        if len(unique) == 3:
            break
    return unique
