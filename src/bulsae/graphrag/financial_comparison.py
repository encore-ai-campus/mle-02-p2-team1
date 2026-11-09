"""Read and compare the project's 2025 structured financial records."""
import json
import re
from bulsae.graphrag.document_search import query_readonly
from bulsae.graphrag.entity_resolution import TARGET_IDS

QUERY = """
MATCH (c:BulsaeCompany)-[r:HAS_FINANCIAL]->(f:BulsaeFinancial)
WHERE c.name IN $names AND c.company_id IN $target_ids
  AND f.company_id=c.company_id AND f.financial_id IS NOT NULL
  AND r.pipeline_version='document-kg-v1' AND r.source='financials.jsonl'
  AND none(label IN labels(c)+labels(f) WHERE label STARTS WITH 'B_')
RETURN c.name AS name, f.financial_id AS financial_id, f.fiscal_year AS year,
       f.period AS period, f.statement_scope AS scope, f.revenue_krw AS revenue,
       f.operating_profit_krw AS operating_profit, f.source_json AS source_json
"""


def is_financial_question(question):
    return any(word in question for word in ('매출', '영업이익', '재무', '실적', '손익', '순이익', '수익성', '자산', '부채'))


def financial_request(question):
    years = {int(x) for x in re.findall(r'(?<!\d)(20\d{2})(?:년)?(?!\d)', question)}
    if years and years != {2025}:
        return None, '현재 수집된 연간 재무는 2025년 자료라 다른 연도와 비교할 수 없어요.'
    if any(x in question for x in ('분기', '반기', '연결')) or re.search(r'(?i)\b(?:[1-4]\s*q|q\s*[1-4])\b', question):
        return None, '현재는 2025년 연간 개별 재무만 비교할 수 있어요.'
    if any(x in question for x in ('전년', '작년', '지난해', '올해', '금년', '현재', '최신', '지금', '최근', '이전', '변화', '변하', '변할', '변한', '변했', '바뀐', '바뀌', '달라', '증감', '증가', '감소', '상승', '하락', '올랐', '오른', '늘었', '줄었', '추이', '추세', '변동', '성장률', '대비')):
        return None, '요청한 기간이나 연도별 변화는 2025년 자료만으로 확인할 수 없어요.'
    if any(x in question for x in ('영업이익률', '비율', '수익률', '마진', '순이익', '비중', '배수', '몇 배', '몇배', '%', '퍼센트')):
        return None, '현재는 2025년 매출액과 영업이익 금액만 비교할 수 있어요.'
    if '이익' in question.replace('영업이익', ''):
        return None, '이익의 종류를 매출액 또는 영업이익으로 구체적으로 알려주세요.'
    if any(x in question for x in ('전략', '행사', '협력', '브랜드', '원인', '영향', '왜')):
        return None, '재무와 전략 등 여러 주제를 결합한 비교는 아직 지원하지 않아요.'
    metrics = [key for word, key in [('매출','revenue'),('영업이익','operating_profit')] if word in question]
    return metrics, None


def fetch_financials(db, names):
    rows = query_readonly(db, QUERY, names=names, target_ids=TARGET_IDS)
    return [r.data() for r in rows]


def compare_financials(question, names, rows):
    metrics, error = financial_request(question)
    if error:
        return {'answer':error, 'status':'unsupported_comparison'}
    if not metrics:
        return {'answer':'매출 또는 영업이익을 지정해 주세요.', 'status':'unsupported_comparison'}
    selected = []
    for name in names:
        matches = [r for r in rows if r.get('name') == name and r.get('year') == 2025
                   and r.get('period') == '연간' and r.get('scope') == '개별'
                   and all(isinstance(r.get(m), int) and not isinstance(r.get(m), bool) for m in metrics)]
        if len(matches) != 1:
            return {'answer':f'{name}의 2025년 연간 개별 재무 근거가 충분하지 않아 비교를 보류했어요.',
                    'status':'insufficient_evidence'}
        row = matches[0]
        try:
            sources = json.loads(row.get('source_json') or '[]')
            source = next(s for s in sources if s.get('original_url'))
        except (ValueError, TypeError, StopIteration, AttributeError):
            return {'answer':f'{name}의 재무 출처를 확인하지 못해 비교를 보류했어요.', 'status':'insufficient_evidence'}
        selected.append((name, row, source))
    labels = {'revenue':'매출액', 'operating_profit':'영업이익'}
    out = ['2025년 연간 개별 재무 기준이에요. 금액은 원 단위예요.' if len(names)==1
           else '수집한 2025년 연간 개별 재무자료를 비교했어요. 금액은 원 단위예요.']
    for name,row,source in selected:
        values = ' | '.join(f"{labels[m]}: {row[m]:,}원" for m in metrics)
        out.append(f"- {name}: {values}\n  근거: {source.get('source_name', '공시')} | {source['original_url']}")
    if len(selected) == 2:
        for m in metrics:
            name_a, row_a, _ = selected[0]; name_b, row_b, _ = selected[1]
            delta = row_a[m] - row_b[m]
            if delta == 0:
                out.append(f'{labels[m]}은 두 기업이 같습니다.')
            else:
                higher = name_a if delta > 0 else name_b
                out.append(f'{labels[m]} 차이는 {abs(delta):,}원으로, {higher} 쪽이 더 커요.')
    return {'answer':'\n\n'.join(out), 'status':'answered', 'trace_kind':'financial',
            'structured_sources': [{'document_id':row.get('financial_id'), 'title':f'{name} 2025년 연간 개별 재무',
                'url':source['original_url'], 'evidence':' | '.join(f'{labels[m]}: {row[m]:,}원' for m in metrics),
                'financial_metrics': {m: row[m] for m in metrics},
                'fiscal_year': row['year'], 'period': row['period'], 'statement_scope': row['scope'],
                'from_name':name, 'to_name':'2025년 연간 개별 재무', 'relation':'HAS_FINANCIAL',
                'source_file':'financials.jsonl'} for name,row,source in selected]}
