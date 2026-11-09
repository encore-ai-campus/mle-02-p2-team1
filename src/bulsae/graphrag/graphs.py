"""LangGraph question flow over the document-grounded Bulsae graph.

External connections are supplied as dependencies. The graph holds no clients,
credentials or embeddings, has no checkpoint, and performs no database writes.
"""
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import re
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from bulsae.graphrag.document_search import AnswerClaim, company_event_supported, render_answer, select_evidence, validate_answer_claims
from bulsae.graphrag.entity_resolution import mention_spans
from bulsae.graphrag.financial_comparison import is_financial_question, financial_request, compare_financials
from bulsae.graphrag.company_information import is_business_question, render_company_business
from bulsae.graphrag.question_analysis import is_executive_event_question
from bulsae.graphrag.multihop_search import render_paths, event_context_evidence
from bulsae.graphrag.document_fallback import merge_evidence

ABSTAIN = '질문에 답할 수 있는 원문 근거를 확인하지 못했어요.'
FAILURE = '검색 또는 답변 확인 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.'


def executive_context_supported(quote):
    """A legal representative in a company parenthesis is not an attendee."""
    parenthetical = re.findall(r'[（(][^）)]*(?:대표|회장)[^）)]*[）)]', quote)
    if not parenthetical:
        return True
    without_roles = quote
    for part in parenthetical:
        without_roles = without_roles.replace(part, '')
    names = [name for part in parenthetical
             for name in re.findall(r'(?:대표이사|대표|회장)\s*([가-힣]{2,4})', part)]
    return bool(names) and any(name in without_roles for name in names)


def financial_background_supported(claim: AnswerClaim) -> bool:
    """Annual standalone amounts come only from the structured finance source."""
    text = claim.heading + ' ' + claim.text
    if '개별' not in claim.exact_quote:
        if '개별' in claim.heading:
            return False
        for sentence in re.split(r'(?<=[.!?])\s+', claim.text):
            if '개별' not in sentence:
                continue
            # Explicitly saying the consolidated background does NOT establish
            # standalone causality is a scope limitation, not an invented scope.
            limitation = re.search(
                r'개별[^.!?]{0,45}(?:인과관계|원인|기여액|기여도)[^.!?]{0,55}'
                r'(?:확인[^.!?]{0,12}않|확인[^.!?]{0,12}없|단정[^.!?]{0,12}없|알 수 없)', sentence)
            if not limitation or re.search(r'개별[^.!?]{0,25}(?:성장했|증가했|늘었|기여했)', sentence):
                return False
    # Article amounts may describe consolidated, group, or quarterly figures.
    # Keep qualitative business context; do not reintroduce competing totals.
    if any(term in text for term in ('매출', '이익', '실적')) and re.search(
            r'\d[\d,.]*\s*(?:조|억|만|원|달러|엔|위안|%|퍼센트)', text):
        return False
    return True


class QueryState(TypedDict, total=False):
    name: str
    joint_query: bool
    kind: str
    question: str
    company_context: str | None
    candidates: list[dict]
    entities: list[dict]
    missing_names: list[str]
    limit: int
    evidence: list[dict]
    claims: list[dict]
    supported: list[int]
    financial_answer: str
    financial_context_kind: str
    evidence_question: str
    context_attempts: int
    analysis: dict
    paths: list[dict]
    structured_sources: list[dict]
    trace_kind: str
    document_search_count: int
    answer: str
    status: str
    related_points: list[dict]
    related_evidence: list[dict]
    related_search_query: str
    related_status: str
    related_errors: list[dict]
    related_diagnostics: dict
    related_graph_paths: list[dict]
    basic_answer: str
    final_output: dict


@dataclass(frozen=True)
class QueryDeps:
    search: Callable[[str, str, int], list[dict]]
    generate: Callable[[str, list[dict]], list[AnswerClaim]]
    review: Callable[[str, list[AnswerClaim], list[dict]], set[int]]
    identify: Callable[[str], dict] | None = None
    financial: Callable[[list[str]], list[dict]] | None = None
    strategy: Callable[[str, int | None], list[dict]] | None = None
    context: Callable[[list[str]], list[dict]] | None = None
    company_info: Callable[[str], list[dict]] | None = None
    analyze: Callable[[str, str], dict] | None = None
    multihop: Callable[[str, str, int | None], list[dict]] | None = None
    documents: Callable[[str, list[str]], list[dict]] | None = None
    business_paths: Callable[[str, str], list[dict]] | None = None
    related: Callable[[str, str, list[dict], bool], list[dict]] | None = None
    compose: Callable[[str, dict], dict] | None = None


def build_query_graph(deps: QueryDeps):
    def finalize(state):
        if deps.compose is None or state.get('status') not in ('answered','partial_evidence'):
            return {}
        try:
            return {'final_output':deps.compose(state['question'], state)}
        except Exception as exc:
            return {'final_output':{'sections':[], 'diagnostics':{'status':'error','error_type':type(exc).__name__}}}

    def enrich(state):
        if deps.related is None or state.get('status') not in ('answered', 'partial_evidence'):
            return {'related_points':[], 'related_status':'skipped'}
        from bulsae.graphrag.related_analysis import related_queries, select_related_evidence, relevant_points, novel_points, missing_financial_facets
        names = [e['name'] for e in state['entities']] if state.get('entities') else [state['name']]
        financial = bool(state.get('financial_answer') or state.get('trace_kind') == 'financial')
        search_questions = related_queries(state['question'], financial)
        search_question = search_questions[0]
        errors = []
        try:
            raw = list(state.get('evidence', []))
            for name in names:
                try:
                    if financial and deps.business_paths is not None:
                        raw.extend(deps.business_paths(name, state['question']))
                    else:
                        raw.extend(deps.search(name, state.get('kind', 'company'), 100))
                except Exception as exc:
                    errors.append({'stage':'related_graph_search', 'type':type(exc).__name__})
            graph_rows = select_related_evidence(state['question'], names, raw, financial)
            missing = missing_financial_facets(state['question'], names, graph_rows) if financial else []
            # Search only a missing company's facet. A complete graph context
            # avoids the article corpus search entirely.
            requests = [(item['query'], [item['company']]) for item in missing] if financial else [(search_question, names)]
            document_rows = []
            if deps.documents is not None and requests:
                with ThreadPoolExecutor(max_workers=3) as executor:
                    jobs = [executor.submit(deps.documents, query, targets) for query,targets in requests]
                    for job in jobs:
                        try:
                            document_rows.extend(job.result())
                        except Exception as exc:
                            errors.append({'stage':'related_document_search', 'type':type(exc).__name__})
            # Keep graph provenance if an article is also returned by fallback.
            graph_docs = {r['document_id'] for r in graph_rows}
            document_rows = [r for r in document_rows if r.get('document_id') not in graph_docs]
            rows = select_related_evidence(state['question'], names, (graph_rows[:10] if document_rows else graph_rows) + document_rows, financial)
            analysis_result = deps.related(state['question'], state.get('answer', ''), rows, financial) if rows else []
            diagnostics = dict(analysis_result.get('diagnostics', {})) if isinstance(analysis_result, dict) else {}
            points = analysis_result.get('points', []) if isinstance(analysis_result, dict) else analysis_result
            # Keyword coverage is not semantic adequacy. If graph-only claims
            # fail review, allow one bounded document fallback, never a loop.
            graph_attempt = dict(diagnostics)
            needs_explanation = any(w in state['question'] for w in ('왜','원인','이유','분석','배경'))
            explanation_missing = needs_explanation and not any(
                p.get('kind') in ('company_explanation','interpretation') for p in points)
            if financial and (not points or explanation_missing) and not requests and deps.documents is not None:
                graph_points = list(points)
                graph_evidence = list(rows)
                missing = [{'company':n, 'facet':facet, 'reason':'그래프 근거의 답변 후보가 인용·의미 검사에 통과하지 못함', 'query':query}
                           for n in names for facet,query in zip(('매출과 판매','비용과 수익성','회사의 실적 설명'), search_questions)]
                if points:
                    missing = [dict(item, reason='사업 사실은 확인했지만 질문한 실적의 원인 설명·종합 해석 근거가 부족함')
                               for item in missing if item['facet'] != '매출과 판매']
                requests = [(item['query'], [item['company']]) for item in missing]
                with ThreadPoolExecutor(max_workers=3) as executor:
                    jobs = [executor.submit(deps.documents, query, targets) for query,targets in requests]
                    for job in jobs:
                        try:
                            document_rows.extend(job.result())
                        except Exception as exc:
                            errors.append({'stage':'semantic_fallback_search', 'type':type(exc).__name__})
                document_rows = [r for r in document_rows if r.get('document_id') not in graph_docs]
                rows = select_related_evidence(state['question'], names, graph_rows[:10] + document_rows, financial)
                analysis_result = deps.related(state['question'], state.get('answer', ''), rows, financial) if rows else []
                diagnostics = dict(analysis_result.get('diagnostics', {})) if isinstance(analysis_result, dict) else {}
                points = analysis_result.get('points', []) if isinstance(analysis_result, dict) else analysis_result
                if not points and graph_points:
                    # A failed supplement must not remove already supported
                    # graph facts or leave their citation indices pointing elsewhere.
                    points, rows = graph_points, graph_evidence
                diagnostics.update(graph_only_attempt=graph_attempt, semantic_fallback_attempts=1)
            diagnostics.update(search_queries=[q for q,_ in requests], retrieved_candidates=len(raw)+len(document_rows),
                               selected_documents=len({r['document_id'] for r in rows}),
                               graph_candidates=len(raw), graph_selected=len(graph_rows),
                               fallback_reasons=missing, retrieval_order='graph_then_missing_documents')
            from bulsae.graphrag.related_analysis import LABELS
            basic = state.get('answer', '')
            points = relevant_points(state['question'], novel_points(points, basic))
            additions = '\n\n'.join(LABELS[p['kind']] + ' · ' + p['heading'] + '\n' + p['text'] for p in points)
            return {'basic_answer':basic, 'answer':basic + ('\n\n' + additions if additions else ''),
                    'related_points':points, 'related_evidence':rows, 'related_search_query':search_question,
                    'related_status':'supported' if points else ('unavailable' if errors and not rows else 'insufficient_evidence'),
                    'related_errors':errors, 'related_diagnostics':diagnostics,
                    'related_graph_paths':[{'path':r['graph_path'], 'document_id':r['document_id'],
                        'eligible_for_analysis':r in graph_rows} for r in raw if r.get('graph_path')]}
        except Exception as exc:
            # Optional enrichment must never erase an already grounded basic answer.
            return {'basic_answer':state.get('answer', ''), 'related_points':[], 'related_status':'unavailable',
                    'related_search_query':search_question,
                    'related_errors':errors + [{'stage':'related_analysis', 'type':type(exc).__name__}]}

    def document_rows(state, names):
        if deps.documents is None:
            return []
        rows = deps.documents(state.get('evidence_question', state['question']), names)
        return [r for r in rows if r.get('source_verified') and r.get('document_id') and r.get('url')]

    def identify(state):
        if state.get('name') and state.get('kind') in ('person', 'company'):
            return {'status': 'resolved'}
        try:
            if deps.identify is None:
                return {'status': 'not_found', 'candidates': []}
            result = deps.identify(state['question'])
            if result.get('status') in ('resolved_compare', 'resolved_multi'):
                entities = result.get('entities', [])
                if 2 <= len(entities) <= 4 and all(e.get('kind') == 'company' and e.get('name') for e in entities):
                    return {'entities': entities, 'name':entities[0]['name'], 'kind':'company',
                            'joint_query':result['status'] == 'resolved_multi', 'status':result['status']}
            if result.get('status') == 'resolved' and result.get('kind') in ('person', 'company') and result.get('name'):
                return {'name':result['name'], 'kind':result['kind'],
                        'company_context':result.get('company_context'), 'status':'resolved'}
            return {'status':result.get('status', 'not_found'), 'candidates':result.get('candidates', [])}
        except Exception:
            return {'status': 'search_error', 'candidates': []}

    def retrieve(state):
        try:
            if state.get('entities') and state.get('joint_query'):
                names = [e['name'] for e in state['entities']]
                rows = []
                for name in names:
                    rows.extend(select_evidence(state['question'], deps.search(name, 'company', state.get('limit', 100))))
                originals = document_rows(state, names)
                return {'evidence':merge_evidence(originals, rows[:24], max_graph=24), 'status':'retrieved',
                        'document_search_count':len(originals)}
            if state.get('entities'):
                evidence, missing = [], []
                years = set(re.findall(r'(?<!\d)(20\d{2})(?:년)?(?!\d)', state['question']))
                if len(years) > 1:
                    return {'evidence': [], 'status': 'unsupported_news_years'}
                for entity in state['entities']:
                    name = entity['name']
                    rows = select_evidence(state['question'], deps.search(name, 'company', state.get('limit', 100)))
                    # Do not attribute a quote to a company it does not mention.
                    from bulsae.graphrag.document_search import source_text
                    rows = [{**r, 'comparison_company':name} for r in rows
                            if mention_spans(source_text(r), name)]
                    if years:
                        year = next(iter(years))
                        rows = [r for r in rows if year in source_text(r)]
                    if any(word in state['question'] for word in ('행사', '참석')):
                        rows = [r for r in rows if company_event_supported(name, r.get('other_name'), source_text(r))]
                    originals = [{**r, 'comparison_company':name} for r in document_rows(state, [name])]
                    rows = merge_evidence(rows, originals)
                    if not rows:
                        missing.append(name)
                    evidence.extend(rows)
                if missing:
                    return {'evidence': evidence, 'missing_names': missing, 'status':'missing_comparison_evidence'}
                return {'evidence':evidence, 'status':'retrieved'}
            if state.get('kind') == 'company' and '전략' in state['question'] and deps.strategy is not None:
                years = set(re.findall(r'(?<!\d)(20\d{2})(?:년)?(?!\d)', state['question']))
                if len(years) > 1:
                    return {'evidence': [], 'status': 'unsupported_news_years'}
                rows = deps.strategy(state['name'], int(next(iter(years))) if years else None)
            else:
                rows = deps.search(state['name'], state['kind'], state.get('limit', 100))
            if state.get('kind') == 'person' and state.get('company_context'):
                company = state['company_context']
                matching = {r['representative_id'] for r in rows if r.get('relation') == 'WORKS_AT'
                            and r.get('other_name') == company and r.get('source_verified')}
                rows = [r for r in rows if r.get('representative_id') in matching]
            selected = select_evidence(state['question'], rows)
            names = [state['name']] + ([state['company_context']] if state.get('company_context') else [])
            originals = document_rows(state, names)
            return {'evidence': merge_evidence(originals, selected[:24]), 'status': 'retrieved',
                    'document_search_count':len(originals)}
        except Exception:
            return {'evidence': [], 'status': 'search_error'}

    def generate(state):
        try:
            if state.get('entities') and not state.get('joint_query'):
                def generate_for_company(entity):
                    indices = [i for i,r in enumerate(state['evidence'])
                               if r.get('comparison_company') == entity['name']]
                    subset = [state['evidence'][i] for i in indices]
                    local_claims = validate_answer_claims(deps.generate(state.get('evidence_question', state['question']), subset), subset)
                    return [c.model_copy(update={'evidence_index':indices[c.evidence_index]}) for c in local_claims]
                with ThreadPoolExecutor(max_workers=min(4, len(state['entities']))) as pool:
                    results = list(pool.map(generate_for_company, state['entities']))
                missing = [entity['name'] for entity, claims in zip(state['entities'], results) if not claims]
                if missing:
                    return {'claims':[], 'missing_names':missing, 'status':'missing_comparison_evidence'}
                return {'claims':[c.model_dump() for claims in results for c in claims], 'status':'generated'}
            claims = deps.generate(state.get('evidence_question', state['question']), state['evidence'])
            claims = validate_answer_claims(claims, state['evidence'])
            return {'claims': [c.model_dump() for c in claims], 'status': 'generated'}
        except Exception:
            return {'claims': [], 'status': 'generation_error'}

    def review(state):
        try:
            claims = [AnswerClaim.model_validate(c) for c in state['claims']]
            accepted = deps.review(state.get('evidence_question', state['question']), claims, state['evidence'])
            valid = sorted(i for i in accepted if isinstance(i, int) and 0 <= i < len(claims))
            if state.get('kind') == 'company' and not state.get('entities') and any(w in state['question'] for w in ('협력', '관계', '연결')):
                valid = [i for i in valid if mention_spans(claims[i].exact_quote, state['name'])]
            if state.get('financial_context_kind') == 'background':
                valid = [i for i in valid if financial_background_supported(claims[i])]
            if state.get('entities') and not state.get('joint_query'):
                valid = [i for i in valid if mention_spans(
                    claims[i].text, state['evidence'][claims[i].evidence_index].get('comparison_company'))]
                if any(word in state['question'] for word in ('행사', '참석')):
                    valid = [i for i in valid if company_event_supported(
                        state['evidence'][claims[i].evidence_index].get('comparison_company'),
                        state['evidence'][claims[i].evidence_index].get('other_name'), claims[i].text)
                        or state['evidence'][claims[i].evidence_index].get('source_kind') == 'document']
                covered = {state['evidence'][claims[i].evidence_index]['comparison_company'] for i in valid}
                missing = [e['name'] for e in state['entities'] if e['name'] not in covered]
                if missing:
                    return {'supported': [], 'missing_names': missing, 'status':'missing_comparison_evidence'}
            return {'supported': valid, 'status': 'reviewed'}
        except Exception:
            return {'supported': [], 'status': 'review_error'}

    def expand_context(state):
        try:
            if deps.context is None:
                raise RuntimeError('document context unavailable')
            originals = state.get('evidence', [])
            selected, seen = [], set()
            group_counts = {}
            for row in originals:
                group = row.get('comparison_company') or '_single'
                key = (group, row.get('document_id'))
                if not key[1] or key in seen or group_counts.get(group, 0) >= 3:
                    continue
                selected.append(row)
                seen.add(key)
                group_counts[group] = group_counts.get(group, 0) + 1
            ids = list(dict.fromkeys(r['document_id'] for r in selected))[:12]
            documents = {r['document_id']:r for r in deps.context(ids)
                         if r.get('document_id') in ids and r.get('content') and r.get('url')}
            rows = []
            for row in selected:
                doc = documents.get(row.get('document_id'))
                if not doc:
                    continue
                # Keep original association and use only literal stored document text.
                rows.append({**row, 'evidence':doc['content'][:12000], 'evidence_json':None,
                             'url':doc['url'], 'source_verified':True})
            return {'evidence':rows, 'context_attempts':1, 'status':'context_retrieved'}
        except Exception:
            return {'evidence':[], 'context_attempts':1, 'status':'context_error'}

    def answer(state):
        claims = [AnswerClaim.model_validate(c) for c in state['claims']]
        answer_text = render_answer(claims, set(state['supported']), state['evidence'])
        if state.get('financial_answer'):
            if state.get('financial_context_kind') == 'background':
                return {'answer':state['financial_answer'] + '\n\n관련 기사에서 확인한 사업 배경입니다.\n\n' + answer_text
                        + '\n\n기사의 사업 배경만으로 개별 매출 금액 전체의 원인을 단정할 수는 없어요.', 'status':'answered'}
            answer_text = (state['financial_answer'] + '\n\n2025년에 보도된 전략 근거입니다. '
                           '기사 발행 연도이며 실제 발표일은 별도 확인이 필요합니다.\n\n' + answer_text +
                           '\n\n재무 수치와 전략 사이의 인과관계는 이 자료만으로 확인되지 않습니다.')
        return {'answer': answer_text, 'status': 'answered'}

    def abstain(state):
        is_error = state.get('status', '').endswith('_error')
        if state.get('financial_answer'):
            detail = '매출 발생 이유' if state.get('financial_context_kind') == 'background' else '2025년 전략'
            return {'answer':state['financial_answer'] + f'\n\n{detail}에 대해서는 질문에 맞는 근거를 확인하지 못했어요.',
                    'status':'partial_evidence'}
        if state.get('status') == 'missing_comparison_evidence':
            return {'answer':f"{', '.join(state.get('missing_names', []))}의 질문에 맞는 근거가 부족해 전체 비교를 보류했어요.",
                    'status':'insufficient_evidence'}
        if state.get('status') == 'unsupported_news_years':
            return {'answer':'여러 연도에 걸친 뉴스 비교는 아직 지원하지 않아요.', 'status':'unsupported_comparison'}
        return {'answer': FAILURE if is_error else ABSTAIN,
                'status': state['status'] if is_error else 'insufficient_evidence'}

    def clarify(state):
        if state.get('status') == 'search_error':
            return {'answer': FAILURE, 'status': 'search_error'}
        candidates = state.get('candidates', [])
        if state.get('status') == 'comparison_needs_names':
            return {'answer':'비교할 기업 이름을 2개 이상 4개 이하로 구체적으로 알려주세요.',
                    'status':'comparison_needs_names'}
        if candidates:
            labels = ', '.join(c['name'] for c in candidates[:6])
            return {'answer': f'질문에서 여러 대상을 찾았어요: {labels}. 알고 싶은 인물이나 기업을 하나로 구체적으로 알려주세요.',
                    'status': 'ambiguous_entity'}
        return {'answer': '질문에서 검색할 인물이나 기업 이름을 찾지 못했어요. 이름을 포함해서 다시 질문해 주세요.',
                'status': 'entity_not_found'}

    def financial(state):
        names = [e['name'] for e in state['entities']] if state.get('entities') else [state['name']]
        _, error = financial_request(state['question'])
        if error:
            return {'answer':error, 'status':'unsupported_comparison'}
        try:
            if deps.financial is None:
                raise RuntimeError('financial dependency unavailable')
            return compare_financials(state['question'], names, deps.financial(names))
        except Exception:
            return {'answer':FAILURE, 'status':'financial_error'}

    def mixed(state):
        question = state['question']
        _, error = financial_request(question)
        if error and not error.startswith('재무와 전략'):
            return {'answer':error, 'status':'unsupported_comparison'}
        names = [e['name'] for e in state['entities']] if state.get('entities') else [state['name']]
        # Group news is not the legal company's standalone financial record.
        financial_names = [n for n in names if not n.endswith(('그룹', '홀딩스', 'Group'))]
        metrics = [m for m in ('매출', '영업이익') if m in question]
        try:
            finance = compare_financials('2025년 ' + ' '.join(metrics), financial_names, deps.financial(financial_names))
            if finance['status'] != 'answered':
                return finance
            if deps.related is not None and deps.business_paths is not None:
                return finance
            originals = document_rows(state, names)
            rows = []
            if deps.strategy is not None:
                for name in names:
                    rows.extend(deps.strategy(name, 2025))
            rows = merge_evidence(originals, rows)
            return {'financial_answer':finance['answer'], 'structured_sources':finance.get('structured_sources', []),
                    'evidence':rows, 'joint_query':True,
                    'evidence_question':question + '\n연간 개별 재무 금액은 별도 정형 자료로 이미 답했다. 뉴스에서는 나머지 전략·목표·사업 배경을 답하라. 회사와 그룹의 범위를 구분하고 수치를 원인과 연결하지 마라.',
                    'document_search_count':len(originals), 'status':'retrieved'}
        except Exception:
            return {'answer':FAILURE, 'status':'search_error'}

    def company_info(state):
        try:
            if deps.company_info is None:
                raise RuntimeError('company information dependency unavailable')
            return render_company_business(state['name'], deps.company_info(state['name']))
        except Exception:
            return {'answer':FAILURE, 'status':'search_error'}

    def financial_background(state):
        years = set(re.findall(r'(?<!\d)(20\d{2})(?!\d)', state['question']))
        if years != {'2025'} or any(w in state['question'] for w in ('분기','반기','연결','전년','증감','추이')):
            return {'answer':'현재 수집된 정형 재무는 2025년 연간 개별 기준이에요. 이 기준의 수치와 관련 사업 배경을 살펴볼 수 있어요.', 'status':'unsupported_comparison'}
        metrics = [m for m in ('매출','영업이익') if m in state['question']]
        try:
            finance = compare_financials('2025년 ' + ' '.join(metrics), [state['name']], deps.financial([state['name']]))
            if finance['status'] != 'answered':
                return finance
            if deps.related is not None:
                return finance
            rows = document_rows(state, [state['name']])
            question = (f"{state['name']}의 2025년 매출과 관련된 사업 배경을 설명해줘. "
                        f"수집된 금액은 2025년 연간 개별 재무다. 그룹·홀딩스 전체의 실적 수치를 다시 제시하지 말고 {state['name']} 법인의 사업 배경을 골라라. "
                        '연결 실적의 배경이면 그 범위를 명시하고 개별 매출의 원인으로 단정하지 마라. '
                        '금액은 별도의 정형 재무 답변에 이미 있다. 기사 매출액·이익 금액과 증감률을 반복하지 말고 사업 배경만 설명하라. '
                        '2025년 사업 실적을 직접 다룬 근거에서 브랜드·제품·판매 채널·해외 사업 내용을 2~3개 문단으로 설명하라. '
                        '제목에 2025년이 있더라도 인용문에 연도가 없으면 문단의 소제목에 연도를 반복하지 마라. '
                        '발표 계획을 실현 성과로 쓰지 마라. 인과관계가 명시되지 않으면 이유를 추정하지 마라.')
            return {'financial_answer':finance['answer'], 'structured_sources':finance.get('structured_sources',[]),
                    'financial_context_kind':'background', 'evidence':rows, 'evidence_question':question,
                    'document_search_count':len(rows), 'status':'retrieved'}
        except Exception:
            return {'answer':FAILURE, 'status':'search_error'}

    def analyze(state):
        try:
            if deps.analyze is None:
                return {'status':'analysis_unavailable'}
            plan = deps.analyze(state['question'], state['name'])
            if plan.get('status') != 'executive_events' or plan.get('role') not in ('ceo','chair'):
                return {'status':'analysis_unavailable'}
            years = {int(y) for y in re.findall(r'(?<!\d)(20\d{2})(?:년)?(?!\d)',state['question'])}
            if '회장' in state['question'] and ('대표' in state['question'] or 'CEO' in state['question']):
                return {'status':'analysis_unavailable'}
            expected = 'chair' if '회장' in state['question'] else 'ceo'
            if len(years) > 1 or plan['role'] != expected or plan.get('year') != (next(iter(years)) if years else None):
                return {'status':'analysis_unavailable'}
            return {'analysis':plan, 'status':'analyzed'}
        except Exception:
            return {'status':'analysis_error'}

    def multihop(state):
        try:
            if deps.multihop is None:
                return {'answer':'대표와 행사 관계를 아직 조회할 수 없어요.', 'status':'unsupported_query'}
            plan = state['analysis']
            paths = deps.multihop(state['name'], plan['role'], plan.get('year'))
            return {'paths':paths, 'answer':render_paths(paths,plan['role'],plan.get('year')),
                    'status':'answered' if paths else 'insufficient_evidence'}
        except Exception:
            return {'answer':FAILURE, 'status':'search_error'}

    def event_context(state):
        paths = state.get('paths', [])
        names = [state['name']] + sorted({p['person'] for p in paths})
        try:
            originals = document_rows(state, names)
        except Exception:
            originals = []
        evidence = merge_evidence(event_context_evidence(paths), originals, max_graph=30)
        question = (state['question'] + '\n기사의 보도 당시 직책을 기준으로 답하고 현재 직책으로 단정하지 마라. '
                    '서로 다른 행사마다 소제목과 문단을 작성하고 인물의 직책, 행사 성격, 실제 참여 활동을 설명하라. '
                    '참석 이유가 원문에 직접 나타나면 함께 설명하되 없으면 추측하지 마라. '
                    '해당 기사에서, 기사에 따르면 같은 표현을 반복하지 말고 자연스럽게 설명하라. '
                    '같은 행사 내용을 여러 문단으로 반복하지 마라. '
                    '한 행사당 원문에 있는 참석 사실과 활동을 1~2문장으로 설명하고, 원문에 없는 해석은 넣지 마라. '
                    '행사명만 나열하지 말고 이 인물이 행사에서 무엇을 발표하거나 했는지, '
                    '어떤 배경·목표와 연결되는지 근거가 있는 내용을 이어서 설명하라. '
                    '참석 동기나 실제 사업 성과는 근거에 명시될 때만 포함하라. '
                    '기업명 뒤 괄호 속 대표 이름은 법인 소개일 뿐 개인 참석 근거가 아니다. '
                    '회사나 연구팀만 참석·발표한 행사는 대표 개인의 행사 목록에서 제외하라. '
                    '발표한 목표를 달성된 결과로 쓰지 마라. 항목을 억지로 채우지 마라.')
        try:
            claims = validate_answer_claims(deps.generate(question, evidence), evidence)
            claims = [claim for claim in claims if executive_context_supported(claim.exact_quote)]
            accepted = deps.review(question, claims, evidence) if claims else set()
            accepted = sorted(i for i in accepted if isinstance(i, int) and 0 <= i < len(claims))
            return {'evidence': evidence, 'claims': [c.model_dump() for c in claims],
                    'supported': accepted, 'trace_kind': 'executive_events',
                    'document_search_count':len(originals),
                    'status':'answered' if accepted or paths else 'insufficient_evidence',
                    'answer':render_answer(claims, set(accepted), evidence) if accepted else state['answer']}
        except Exception:
            # The source-checked participation answer remains available.
            return {'evidence': evidence, 'claims': [], 'supported': [], 'trace_kind': 'executive_events',
                    'document_search_count':len(originals)}

    graph = StateGraph(QueryState)
    for name, node in (('finalize', finalize), ('enrich', enrich), ('financial_background', financial_background), ('identify', identify), ('retrieve', retrieve), ('generate', generate),
                       ('review', review), ('answer', answer), ('abstain', abstain), ('clarify', clarify), ('financial', financial), ('mixed', mixed), ('expand_context', expand_context), ('company_info', company_info), ('analyze', analyze), ('multihop', multihop), ('event_context', event_context)):
        graph.add_node(name, node)
    graph.add_edge(START, 'identify')
    def route_identify(s):
        resolved = s.get('status') in ('resolved', 'resolved_compare', 'resolved_multi')
        if resolved and s.get('kind', 'company') == 'company' and is_financial_question(s['question']):
            q = s['question']
            names = [e['name'] for e in s['entities']] if s.get('entities') else [s['name']]
            # News can answer quarterly/group questions; do not substitute annual standalone data.
            if any(w in q for w in ('분기', '반기', '연결')) or all(n.endswith(('그룹', '홀딩스', 'Group')) for n in names):
                return 'retrieve'
            if any(w in q for w in ('전략', '성장', '목표', '방향')) and '2025' in q:
                return 'mixed'
            if s.get('status') == 'resolved' and any(w in q for w in ('이유','원인','배경','분석','왜')):
                return 'financial_background'
            return 'financial'
        if s.get('status') in ('resolved_compare', 'resolved_multi'):
            return 'retrieve'
        if s.get('status') == 'resolved' and s.get('kind') == 'company' and is_business_question(s['question']):
            return 'company_info'
        if s.get('status') == 'resolved' and s.get('kind') == 'company' and is_executive_event_question(s['question']):
            return 'analyze'
        return 'retrieve' if s.get('status') == 'resolved' else 'clarify'
    graph.add_conditional_edges('identify', route_identify, ['retrieve', 'financial', 'financial_background', 'mixed', 'company_info', 'analyze', 'clarify'])
    graph.add_conditional_edges('financial_background', lambda s: 'enrich' if s.get('status') == 'answered' else ('generate' if s.get('evidence') else ('abstain' if s.get('financial_answer') else END)), ['enrich','generate','abstain',END])
    graph.add_conditional_edges('analyze', lambda s: 'multihop' if s.get('status') == 'analyzed' else 'abstain', ['multihop','abstain'])
    graph.add_conditional_edges('mixed', lambda s: 'enrich' if s.get('status') == 'answered' else ('generate' if s.get('evidence') else ('abstain' if s.get('financial_answer') else END)), ['enrich', 'generate', 'abstain', END])
    graph.add_conditional_edges('retrieve', lambda s: 'generate' if s.get('evidence') and s.get('status') != 'missing_comparison_evidence' else 'abstain', ['generate', 'abstain'])
    def retry_or_abstain(s):
        if (deps.context is not None and not s.get('context_attempts') and s.get('evidence')
                and not s.get('status', '').endswith('_error')):
            return 'expand_context'
        return 'abstain'
    graph.add_conditional_edges('generate', lambda s: 'review' if s.get('claims') else retry_or_abstain(s), ['review', 'expand_context', 'abstain'])
    graph.add_conditional_edges('review', lambda s: 'answer' if s.get('supported') else retry_or_abstain(s), ['answer', 'expand_context', 'abstain'])
    graph.add_conditional_edges('expand_context', lambda s: 'generate' if s.get('evidence') else 'abstain', ['generate', 'abstain'])
    graph.add_edge('answer', 'enrich')
    graph.add_edge('abstain', 'enrich')
    graph.add_edge('clarify', END)
    graph.add_edge('financial', 'enrich')
    graph.add_edge('company_info', 'enrich')
    graph.add_conditional_edges('multihop', lambda s: 'event_context' if s.get('paths') or (deps.documents is not None and s.get('status') != 'search_error') else END, ['event_context', END])
    graph.add_edge('event_context', 'enrich')
    graph.add_edge('enrich', 'finalize')
    graph.add_edge('finalize', END)
    return graph.compile()
