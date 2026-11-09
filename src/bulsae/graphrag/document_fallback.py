"""Bounded, read-only retrieval from stored articles, independent of KG edges."""
import re

from bulsae.graphrag.document_search import query_readonly
from bulsae.graphrag.entity_resolution import mention_spans

TOPICS = (
    (('이슈', '관여', '논란'), ('논란', '갈등', '주장', '반박', '해명', '입장', '가맹', '구조조정')),
    (('정원',), ('정원', '공동', '조성', '재활용')),
    (('앞으로', '키우', '중점', '방향'), ('전략', '계획', '육성', '목표', '추진')),
    (('매출','영업이익','실적'), ('매출','영업이익','실적','성장','판매','수익성')),
    (('행사', '참석', '참가', '포럼', '박람회'), ('행사', '참석', '참여', '참가', '발표', '총회', '포럼', 'Summit', '환영인사', '인사말', '협약식', '기념식', '단상')),
    (('협력', '파트너', '관계'), ('협력', '협약', '공동', '파트너', '제휴', '인수', '계열')),
    (('공급',), ('공급', '납품', '원료', '제조')),
    (('전략', '성장', '진출', '해외'), ('전략', '성장', '진출', '해외', '목표', '확대', '육성')),
    (('브랜드', '제품'), ('브랜드', '제품', '출시', '운영')),
)

DOCUMENT_QUERY = """
MATCH (d:BulsaeDocument)
WHERE none(l IN labels(d) WHERE l STARTS WITH 'B_')
  AND d.document_id STARTS WITH 'NEWS-'
  AND any(name IN $names WHERE replace(d.content,' ','') CONTAINS replace(name,' ',''))
  AND any(term IN $terms WHERE toLower(d.content) CONTAINS toLower(term))
RETURN d.document_id AS document_id,d.title AS title,d.original_url AS url,
       d.published_at AS published_at,d.content AS content
ORDER BY d.document_id
"""


def topic_terms(question):
    if any(t in question for t in ('이슈', '논란', '갈등')):
        return ['논란', '갈등', '가맹점', '구조조정', '희망퇴직', '노조', '시위', '해명', '반박']
    # Product/brand words describe the object in supply questions, not the task.
    if any(t in question for t in ('공급','납품')):
        return ['공급','납품','OEM','ODM','제조']
    if any(t in question for t in ('협력','파트너')) and '관계도' not in question:
        return ['협력','협약','공동','파트너','제휴']
    terms = []
    focus = question.partition('분석 초점: ')[2]
    if focus:
        terms.extend(focus.split())
    if '분기' in question:
        terms.extend(['1분기', '2분기', '3분기', '4분기'])
    for triggers, words in TOPICS:
        if any(t in question for t in triggers):
            terms.extend(words)
    return list(dict.fromkeys(terms)) or ['사업', '기업', '회사']


def rank_documents(question, names, documents, limit=12):
    """Rank every matching stored document before taking a bounded sample.

    Excerpts are literal contiguous windows; article dates are metadata only.
    Round-robin across topic words prevents one repeated event monopolizing results.
    """
    terms = topic_terms(question)
    focus = [w for w in ('제주', '정원', '대학', '연세', '컬리', '공통', '연구', '이슈', '가맹', '전략', '목표', '제품', '성장') if w in question]
    facet_terms = question.partition('분석 초점: ')[2].split()
    future = any(w in question for w in ('전략', '목표', '키우', '앞으로', '방향', '중점'))
    financial = any(w in question for w in ('매출', '영업이익', '실적'))
    years = re.findall(r'(?<!\d)20\d{2}(?!\d)', question)
    candidates = []
    for doc in documents:
        content = doc.get('content') or ''
        if any(t in question for t in ('이슈', '논란', '갈등')) and not any(t in content for t in terms):
            continue
        if not doc.get('document_id') or not doc.get('url') or not any(mention_spans(content, n) for n in names):
            continue
        lines = content.splitlines(keepends=True)
        offset, windows = 0, []
        for line in lines:
            hits = {term for term in terms if term.lower() in line.lower()}
            if hits and not line.lstrip().startswith('!['):
                score = len(hits) + 5 * sum(bool(mention_spans(line, n)) for n in names)
                score += 4 * sum(w in line for w in focus)
                score += 12 * sum(w in line for w in facet_terms)
                if future:
                    score += 7 * int(any(w in line for w in ('전략', '계획', '목표', '육성')))
                if any(x in question for x in ('대표', '회장', 'CEO')):
                    score += 7 * int(bool(re.search(r'대표(?:이사)?|회장', line)))
                windows.append((score, offset, offset + len(line), hits))
            offset += len(line)
        if not windows:
            continue
        best = max(windows, key=lambda w: w[0])
        start, end = max(0, best[1] - 500), min(len(content), best[2] + 500)
        if len(content) <= 6000:
            start, end = 0, len(content)
        excerpt = content[start:end][:6000]
        requested_years = re.findall(r'(?<!\d)20\d{2}(?!\d)', question)
        year_bonus = 8 * int(any(y in (doc.get('title') or '') or y in excerpt for y in requested_years))
        if requested_years and any(w in question for w in ('매출','영업이익')) and '분기' not in question:
            title = doc.get('title') or ''
            annual = any(y in title for y in requested_years) and not any(w in title for w in ('분기','반기'))
            year_bonus += 12 * int(annual)
        specificity = 6 * sum(w in (doc.get('title') or '') for w in focus)
        # Explicit counterparts must co-occur; a long single-company article is not a better match.
        specificity += 12 * sum(bool(mention_spans(content, n)) for n in names)
        period_priority = 0
        if financial and years:
            title = doc.get('title') or ''
            # Prefer the legal entity's results over repeated holding-group releases.
            specificity += 20 * sum(bool(mention_spans(title, n)) for n in names)
            period_results = any(re.search(re.escape(y) + r'년?[^\n.!?]{0,90}(?:매출|영업이익|실적|연결|개별|별도)', content)
                                 for y in years)
            specificity += 18 * int(period_results)
            specificity += 12 * int(period_results and any(w in content for w in ('별도', '개별')))
            specificity += 8 * int(period_results and bool(re.search(r'회사[^\n]{0,120}(?:설명|밝혔)', content)))
            annual_title = (any(y in title for y in years) and any(w in title for w in ('매출', '영업이익', '실적'))
                            and not re.search(r'분기|반기|[1-4]Q|Q[1-4]|전망|목표', title, re.I))
            legal_title = any(re.search(re.escape(n) + r'(?!\s*(?:그룹|홀딩스|재단))', title) for n in names)
            period_priority = int(period_results) + int(annual_title) + int(annual_title and legal_title)
            if period_results and legal_title and '공시' in content and any(w in content for w in ('별도', '개별')):
                period_priority += 2
        candidates.append({**doc, 'evidence': excerpt, 'source_verified': True,
            'source_kind': 'document', 'relation': 'DOCUMENT_EVIDENCE',
            'representative_id': 'document:' + doc['document_id'],
            'excerpt_start': start, 'excerpt_end': start + len(excerpt),
            '_period_priority':period_priority,
            '_score': best[0] + year_bonus + specificity + sum(t.lower() in (doc.get('title') or '').lower() for t in terms),
            '_hits': set().union(*(w[3] for w in windows))})
    candidates.sort(key=lambda r: (-r['_period_priority'], -r['_score'], r['document_id']))
    chosen, seen, signatures = [], set(), set()
    fingerprints = []
    for term in ([''] * limit if financial else terms + [''] * limit):
        for row in candidates:
            signature = re.sub(r'\s+', '', row['evidence'])
            if row['document_id'] in seen or signature in signatures or (term and term not in row['_hits']):
                continue
            fingerprint = {signature[i:i+5] for i in range(max(0, len(signature)-4))}
            if financial and any(len(fingerprint & old) / max(1, min(len(fingerprint), len(old))) > .65
                                 for old in fingerprints):
                continue
            chosen.append(row); seen.add(row['document_id']); signatures.add(signature)
            fingerprints.append(fingerprint)
            break
        if len(chosen) >= limit:
            break
    return [{k:v for k,v in row.items() if k not in ('content', '_score', '_hits', '_period_priority')} for row in chosen]


def fetch_document_evidence(db, question, names, limit=12):
    names = list(dict.fromkeys(n for n in names if isinstance(n, str) and len(n.strip()) >= 2))[:5]
    if not names:
        return []
    rows = [r.data() for r in query_readonly(db, DOCUMENT_QUERY, names=names, terms=topic_terms(question))]
    return rank_documents(question, names, rows, limit)


def merge_evidence(graph_rows, document_rows, max_graph=24):
    # Keep source types separate: a document excerpt is never a claimed graph edge.
    unique, seen = [], set()
    for row in list(graph_rows)[:max_graph] + list(document_rows):
        key = (row.get('document_id'), row.get('relation'), row.get('comparison_company'), row.get('evidence'))
        if key not in seen:
            unique.append(row); seen.add(key)
    return unique
