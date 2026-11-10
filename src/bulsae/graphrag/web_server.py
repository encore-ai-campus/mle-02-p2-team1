"""Local, read-only HTTP bridge to the existing LangGraph question flow."""
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / '.env')
WEB = ROOT / 'connect-ui' / 'dist'
PORT = 8769
ALLOWED = {'http://127.0.0.1:8769', 'http://localhost:8769',
           'https://connect-graphrag-test.dkssk136136.chatgpt.site'}
if os.environ.get('BULSAE_UI_ORIGIN'):
    ALLOWED.add(os.environ['BULSAE_UI_ORIGIN'].rstrip('/'))
SLOTS = threading.BoundedSemaphore(2)


def merge_repeated_sections(sections):
    kept = []
    for section in sections:
        incoming = ' '.join(section['text'].split())
        duplicate = None
        if section.get('section_type') == 'basic':
            for other in kept:
                existing = ' '.join(other['text'].split())
                if (other.get('section_type') == 'basic' and other.get('kind') == section.get('kind')
                        and incoming == existing):
                    duplicate = other
                    break
        if duplicate is None:
            kept.append({**section, 'sources':list(section.get('sources', []))})
        else:
            duplicate['sources'] = list(dict.fromkeys(duplicate['sources'] + section.get('sources', [])))
    return kept


def present_combined_response(result):
    """Combine independently verified task results while keeping citation mappings."""
    merged = {'answer':'', 'status':result['status'], 'lead':'', 'sections':[], 'sources':[],
              'financial_cards':[], 'event_cards':[], 'company_profiles':[], 'trace':{'connections':[], 'graph_paths':[],
              'answer_graph_paths':[], 'steps':['질문 분석과 검색 계획', '요청별 검색 및 근거 확인'],
              'components':[], 'search_plan':result.get('combined_plan', {}), 'hops':0, 'retrieved_records':0}}
    source_map = {}
    answers = []
    for item in result['component_runs']:
        part = present_response(item['result'])
        merged['trace']['components'].append({'task':item['task'], 'status':part['status'],
            'executed_nodes':item['executed_nodes'], 'trace':part['trace']})
        if part['status'] not in ('answered','partial_evidence'):
            merged['sections'].append({'heading':'확인하지 못한 항목', 'text':part['answer'],
                                       'sources':[], 'section_type':'basic'})
            answers.append(part['answer'])
            continue
        nums = {}
        for source in part['sources']:
            key = (source.get('document_id'), source.get('url'))
            if key not in source_map:
                source_map[key] = len(merged['sources']) + 1
                merged['sources'].append({**source, 'number':source_map[key], 'quotes':list(source.get('quotes', []))})
            else:
                existing = merged['sources'][source_map[key]-1]['quotes']
                for quote in source.get('quotes', []):
                    if quote not in existing:
                        existing.append(quote)
            nums[source['number']] = source_map[key]
        if part.get('company_overview'):
            overview = part['company_overview']
            merged['company_profiles'].append({**overview,
                'fields':[{**f,'source_number':nums.get(f.get('source_number'))} for f in overview['fields']],
                'business_sources':[nums[n] for n in overview.get('business_sources', []) if n in nums],
                'news':[{**n,'source_number':nums.get(n.get('source_number'))} for n in overview['news']]})
        if part.get('lead') and not part.get('company_overview'):
            heading = '기업 기본정보' if item['task'] == 'company_info' else ('재무 기준' if item['task'] == 'financial' else '확인한 내용')
            merged['sections'].append({'heading':heading, 'text':part['lead'],
                'sources':[nums[s['number']] for s in part['sources']], 'section_type':'basic'})
        for section in part.get('sections', []):
            if part.get('company_overview') and section.get('section_type') != 'additional':
                continue
            merged['sections'].append({**section, 'sources':[nums[n] for n in section.get('sources', []) if n in nums]})
        for card in part.get('financial_cards', []):
            merged['financial_cards'].append({**card, 'source_number':nums.get(card.get('source_number'))})
        for card in part.get('event_cards', []):
            merged['event_cards'].append({**card, 'sources':[nums[n] for n in card.get('sources', []) if n in nums]})
        for connection in part['trace'].get('connections', []):
            merged['trace']['connections'].append({**connection, 'source_number':nums.get(connection.get('source_number'))})
        for key in ('graph_paths','answer_graph_paths'):
            merged['trace'][key].extend(part['trace'].get(key, []))
        merged['trace']['hops'] = max(merged['trace']['hops'], part['trace'].get('hops', 0))
        merged['trace']['retrieved_records'] += part['trace'].get('retrieved_records', 0)
        answers.append(part['answer'])
    merged['sections'] = merge_repeated_sections(merged['sections'])
    merged['answer'] = '\n\n'.join(answers)
    if merged['event_cards']:
        from bulsae.graphrag.related_analysis import merge_event_cards
        merged['event_cards'] = merge_event_cards(merged['event_cards'])
    if any(s.get('kind') == 'interpretation' for s in merged['sections']):
        from bulsae.graphrag.related_analysis import INFERENCE_NOTICE
        merged['analysis_notice'] = INFERENCE_NOTICE
    return merged


def present_response(result):
    """Separate readable explanations from their original, deduplicated sources."""
    if result.get('component_runs'):
        return present_combined_response(result)
    if 'basic_answer' in result:
        result = {**result, 'answer':result['basic_answer']}
    response = {'answer': result.get('answer', '답변을 만들지 못했어요.'),
                'status': result.get('status', 'unknown'), 'lead': '', 'sections': [], 'sources': [], 'financial_cards': [],
                'trace': {'connections': [], 'retrieved_records': len(result.get('evidence', [])) or len(result.get('paths', [])) or len(result.get('structured_sources', [])),
                          'accepted_paragraphs': len(result.get('supported', [])),
                          'document_search_count': result.get('document_search_count', 0),
                          'mode': result.get('trace_kind', 'graph_relations')}}
    if result.get('status') not in ('answered', 'partial_evidence'):
        return response
    sources, sections = response['sources'], response['sections']
    source_keys = {}

    def add_source(row, quotes):
        key = (row['document_id'], row['url'])
        if key not in source_keys:
            source_keys[key] = len(sources) + 1
            sources.append({'number': len(sources) + 1, 'title': row.get('title') or '근거 기사',
                            'url': row['url'], 'document_id': row.get('document_id'), 'source_file': row.get('source_file'),
                            'source_kind':row.get('source_kind', 'graph'), 'quotes': []})
        number = source_keys[key]
        existing = sources[number - 1]['quotes']
        lines = [line.strip() for quote in quotes for line in quote.splitlines() if line.strip()]
        for quote in lines:
            # A stored image caption is often repeated as a plain text line.
            if quote.startswith('![') and '](' in quote:
                caption = quote[2:quote.rfind('](')]
                if ' '.join(caption.split()) in {' '.join(line.split()) for line in lines if not line.startswith('![')}:
                    continue
            if ' '.join(quote.split()) not in {' '.join(q.split()) for q in existing}:
                existing.append(quote)
        return number

    connections = response['trace']['connections']
    seen_connections = set()

    def connect(start, relation, end, source_number, observation_id=None):
        key = (start, relation, end, source_number, observation_id)
        if not start or not end or not relation or key in seen_connections:
            return
        seen_connections.add(key)
        connections.append({'from': start, 'relation': relation, 'to': end,
                            'source_number': source_number, 'observation_id': observation_id})

    if result.get('paths'):
        groups = {}
        for row in result['paths']:
            groups.setdefault((row['company'], row['person'], row['event'],row.get('event_year')), []).append(row)
        role = '대표' if result['analysis']['role'] == 'ceo' else '회장'
        for (company, person, event,event_year), rows in list(groups.items())[:10]:
            refs = []
            for row in rows[:3]:
                number = add_source(row, [row['work_evidence'], row['event_evidence']])
                connect(person, 'WORKS_AT', company, number, row.get('work_observation_id'))
                connect(person, 'PARTICIPATED_IN', event, number, row.get('event_observation_id'))
                if number not in refs:
                    refs.append(number)
            has_intro = any(all(name in result['claims'][i]['text'] for name in (company, person, event))
                            for i in result.get('supported', []))
            if not has_intro:
                heading = f'{event_year}년 {event}' if event_year and str(event_year) not in event else event
                sections.append({'heading': heading,
                                 'text': f'{company} {role} {person}은 {event}에 참여했어요.',
                                 'sources': refs})
        response['trace']['hops'] = 2
        response['trace']['mode'] = 'executive_events'

    if result.get('supported'):
        for i in result['supported']:
            claim = result['claims'][i]
            row = result['evidence'][claim['evidence_index']]
            number = add_source(row, [claim['exact_quote']])
            if not result.get('paths'):
                connect(row.get('from_name'), row.get('relation'), row.get('to_name'), number, row.get('observation_id'))
            duplicate = next((section for section in sections if section['text'] == claim['text']), None)
            if duplicate is not None:
                if number not in duplicate['sources']:
                    duplicate['sources'].append(number)
            else:
                heading = claim.get('heading') or row.get('comparison_company') or ''
                if any(w in claim['text'] for w in ('언급되지 않았', '확인되지 않았', '확인하지 못')) and any(w in heading for w in ('아니', '없음', '안 했')):
                    heading = '자료에서 확인한 범위'
                if claim.get('kind') == 'company_explanation':
                    heading = '회사가 밝힌 원인 · ' + heading
                sections.append({'heading': heading, 'text': claim['text'], 'sources': [number],
                                 'kind':claim.get('kind', 'reported_fact'), 'section_type':'basic'})

    financial_refs=[]
    for row in result.get('structured_sources', []):
        number = add_source(row, [row['evidence']])
        financial_refs.append(number)
        for metric, label in (('revenue', '매출액'), ('operating_profit', '영업이익')):
            value = row.get('financial_metrics', {}).get(metric)
            if isinstance(value, int) and not isinstance(value, bool):
                response['financial_cards'].append({'company':row.get('from_name'), 'label':label,
                    'value':value, 'year':row.get('fiscal_year'), 'period':row.get('period'),
                    'scope':row.get('statement_scope'), 'source_number':number})
        connect(row.get('from_name'), row.get('relation'), row.get('to_name'), number)
    if not sections and result.get('structured_sources'):
        # Structured financial calculations remain deterministic.
        paragraphs = ([result['structured_sources'][0]['evidence']] if result.get('trace_kind') == 'company_info'
                      else result['answer'].split('\n\n'))
        for paragraph in paragraphs:
            clean = '\n'.join(line for line in paragraph.splitlines() if not line.strip().startswith('근거:'))
            sections.append({'heading':'', 'text':clean, 'sources':[s['number'] for s in sources]})
    if result.get('trace_kind') == 'company_info':
        profile = []
        company_id = next((s.get('document_id') for s in result.get('structured_sources', [])), result.get('name', 'company'))
        for field in result.get('company_profile', []):
            number = add_source({'document_id':company_id, 'url':field.get('source_url') or '',
                'title':field['label'] + ' 정보', 'source_file':field['source_file'], 'source_kind':'structured'},
                [field['label'] + ': ' + field['value']])
            profile.append({**field, 'source_number':number})
        news = []
        for item in result.get('recent_news', [])[:3]:
            number = add_source(item, [item['evidence']])
            news.append({**item, 'source_number':number})
            sections.append({'heading':item['heading'], 'text':item['text'], 'sources':[number],
                             'kind':item.get('kind','reported_fact'), 'section_type':'basic'})
        response['company_overview'] = {'name':result.get('name',''), 'fields':profile,
            'business':result.get('company_business'), 'business_sources':financial_refs,
            'news':news, 'recent_status':result.get('recent_status','unavailable')}
    if sections:
        response['answer'] = '\n\n'.join((section['heading'] + '\n' if section['heading'] else '') + section['text'] for section in sections)
        if result.get('financial_answer'):
            response['answer'] = result['financial_answer'] + '\n\n' + response['answer']
            sections.insert(0, {'heading':'재무 정보', 'text':result['financial_answer'], 'sources':financial_refs})
            if result.get('financial_context_kind') == 'background':
                sections.append({'heading':'해석 범위', 'text':'이 사업 배경과 연결·분기 실적을 연간 개별 매출의 원인으로 바로 단정할 수는 없어요. 기사에 설명된 범위에서 살펴본 내용이에요.', 'sources':[]})
                response['answer'] += '\n\n' + sections[-1]['text']
    from bulsae.graphrag.related_analysis import LABELS
    additions = []
    for point in result.get('related_points', []):
        refs = []
        for citation in point['citations']:
            row = result['related_evidence'][citation['evidence_index']]
            number = add_source(row, [citation['exact_quote']])
            if number not in refs:
                refs.append(number)
        heading = LABELS[point['kind']] + ' · ' + point['heading']
        additions.append({'heading':heading, 'text':point['text'], 'sources':refs, 'kind':point['kind'], 'section_type':'additional'})
    if additions:
        if not sections and response.get('answer'):
            sections.append({'heading':'기본 답변', 'text':response['answer'], 'sources':financial_refs})
        sections.extend(additions)
        response['answer'] += '\n\n' + '\n\n'.join(p['heading'] + '\n' + p['text'] for p in additions)
    elif (result.get('trace_kind') == 'financial' and result.get('related_status') not in (None, 'skipped')
          and any(w in result.get('question', '') for w in ('왜', '원인', '이유', '배경', '분석'))):
        # An explicit analysis request must not silently look like a complete amount-only answer.
        metric_label = '영업이익은' if '영업이익' in result.get('question', '') and '매출' not in result.get('question', '') else '재무 수치는'
        text = (f'{metric_label} 확인했지만, 관련 기사에서 이 기간·재무 기준에 맞는 원인 설명이나 해석을 뒷받침할 근거는 충분히 확보하지 못했어요.'
                if result.get('related_status') != 'unavailable' else
                f'{metric_label} 확인했지만, 관련 기사 검색·분석을 완료하지 못해 실적 배경은 이번 답변에 담지 못했어요.')
        if not sections and response.get('answer'):
            sections.append({'heading':'기본 답변', 'text':response['answer'], 'sources':financial_refs})
        sections.append({'heading':'분석에서 확인한 범위', 'text':text, 'sources':[], 'section_type':'additional'})
        response['status'] = 'partial_evidence'
    response['trace']['related_status'] = result.get('related_status', 'skipped')
    response['trace']['related_errors'] = result.get('related_errors', [])
    response['trace']['related_diagnostics'] = result.get('related_diagnostics', {})
    response['trace']['related_search_query'] = result.get('related_search_query')
    response['trace']['related_records'] = len(result.get('related_evidence', []))
    response['trace']['related_points'] = len(additions)
    used_paths, path_keys = [], set()
    for point in result.get('related_points', []):
        for citation in point['citations']:
            row = result['related_evidence'][citation['evidence_index']]
            path = row.get('graph_path', [])
            key = tuple(e['observation_id'] for e in path)
            if path and key not in path_keys:
                path_keys.add(key)
                used_paths.append({'edges':path, 'hops':len(path), 'used_in_answer':True})
                for edge in path:
                    number = next((s['number'] for s in sources if s['document_id'] == edge['document_id']), None)
                    connect(edge['from_name'], edge['relation'], edge['to_name'], number, edge['observation_id'])
    retrieved_paths = []
    retrieved_keys = set()
    for record in result.get('related_graph_paths', []):
        key = tuple(e['observation_id'] for e in record['path'])
        if key not in retrieved_keys:
            retrieved_keys.add(key)
            retrieved_paths.append({'edges':record['path'], 'hops':len(record['path']),
                                    'used_in_answer':key in path_keys})
    response['trace']['graph_paths'] = retrieved_paths
    response['trace']['answer_graph_paths'] = used_paths
    response['trace']['retrieved_graph_hops'] = max((p['hops'] for p in retrieved_paths), default=0)
    response['trace']['hops'] = max(response['trace'].get('hops', 1 if connections else 0),
                                  max((p['hops'] for p in used_paths), default=0))
    response['trace']['source_count'] = len(sources)
    if result.get('search_plan'):
        response['trace']['search_plan'] = result['search_plan']
    response['trace']['steps'] = (['기업과 인물 식별', '재직 관계와 행사 참여 관계 조회', '연결된 기사 원문 대조', '질문에 맞는 설명 생성·검사']
        if result.get('paths') else ['대상 식별', '질문에 맞는 자료 조회', '근거 확인 및 답변 작성'])
    if result.get('related_status') not in (None, 'skipped'):
        response['trace']['steps'].extend(['원래 질문의 관련 자료 검색', '사실·회사 설명·종합 해석 구분 및 검증'])
    response['sections'] = merge_repeated_sections(sections)
    for section in response['sections']:
        section.setdefault('section_type', 'basic')
    if response['sections']:
        response['answer'] = '\n\n'.join((s['heading'] + '\n' if s['heading'] else '') + s['text'] for s in response['sections'])
    # The downloadable answer stays complete. Only exact structured amount
    # lines move to metric cards; comparison deltas and analysis stay in prose.
    metric_lines = {
        f"- {row.get('from_name')}: {row['evidence']}"
        for row in result.get('structured_sources', []) if row.get('financial_metrics')
    }
    display = []
    for section in response['sections']:
        lines = [line for line in section['text'].splitlines()
                 if line.strip() not in metric_lines and not line.strip().startswith('근거:')]
        text = '\n'.join(lines).strip()
        if text:
            display.append({**section, 'text': text})
    response['sections'] = display
    if result.get('structured_sources') and display and not display[0]['heading']:
        response['lead'] = display.pop(0)['text']
    final_output = result.get('final_output', {})
    response['trace']['final_composition'] = final_output.get('diagnostics', {})
    final_sections = final_output.get('sections', [])
    event_cards = final_output.get('event_cards', [])
    if final_sections or event_cards:
        response['trace']['accepted_sections_before_composition'] = response['sections']
        summaries = [s for s in final_sections if s['section_type'] == 'basic']
        analysis = [s for s in final_sections if s['section_type'] == 'additional']
        response['sections'] = (summaries or [{**s, 'section_type':'basic'} for s in response['sections']
            if s.get('kind') != 'interpretation']) + analysis
        # Source scope is a factual label, not another uncertainty disclaimer.
        # Keep it visible when prose is condensed beside standalone metric cards.
        for section in response['sections']:
            cited = [s for s in sources if s['number'] in section.get('sources', [])]
            if (any(re.search(r'연결\s*(?:기준|재무)', ' '.join(s['quotes'][:3])) for s in cited)
                    and '연결' not in section['heading'] + section['text']):
                section['heading'] = '연결 사업 · ' + section['heading']
        if summaries:
            response['lead'] = ''
        response['final_composed'] = True
        response['answer'] = '\n\n'.join((s['heading']+'\n' if s['heading'] else '')+s['text']
                                         for s in response['sections'])
        # Preserve all exact metric values in the downloadable answer as well.
        amounts = [f"{c['company']} · {c['year']}년 · {c['period']} · {c['scope']} · {c['label']}: {c['value']:,}원"
                   for c in response['financial_cards']]
        if amounts:
            response['answer'] = '\n'.join(amounts) + '\n\n' + response['answer']
        response['trace']['steps'].append('채택된 답변 데이터 요약 및 LLM 분석')
    if event_cards:
        from bulsae.graphrag.related_analysis import merge_event_cards, event_card_text
        # Only reviewed cards can enter this block. Count displayed editions,
        # never evidence records or the model's prose total.
        response['event_cards'] = merge_event_cards(event_cards)
        refs = {n for c in response['event_cards'] for n in c['sources']}
        response['event_dashboard'] = {
            'attended_count':len(response['event_cards']),
            'activity_count':sum(bool(c.get('activity', '').strip()) for c in response['event_cards']),
            'source_count':len({s.get('document_id') or s.get('url') for s in sources if s['number'] in refs}),
        }
        response['trace']['event_cards'] = response['event_cards']
        response['sections'] = [s for s in response['sections'] if s.get('section_type') == 'additional']
        response['lead'] = ''
        response['answer'] = ('자료에서 확인된 참석 행사: ' + str(len(response['event_cards'])) + '건\n\n' +
            '\n\n'.join(c['name'] + '\n' + event_card_text(c) for c in response['event_cards']) +
            '\n\n' + '\n\n'.join(s['heading'] + '\n' + s['text'] for s in response['sections']))
    if any(s.get('kind') == 'interpretation' for s in response['sections']):
        from bulsae.graphrag.related_analysis import INFERENCE_NOTICE
        response['analysis_notice'] = INFERENCE_NOTICE
        response['answer'] += '\n\n' + INFERENCE_NOTICE
    return response


def execute_question(question, *, limit=200, name=None, kind=None, model=None, review_model=None):
    """One dependency assembly for Streamlit, HTTP and the LangGraph CLI. Read-only."""
    started = time.monotonic()
    from openai import OpenAI
    from bulsae.graphrag.pipeline import driver
    from bulsae.graphrag.document_search import fetch_evidence, fetch_strategy_evidence, fetch_document_context, generate_claims, review_claims, fetch_business_paths
    from bulsae.graphrag.entity_resolution import resolve_question
    from bulsae.graphrag.financial_comparison import fetch_financials
    from bulsae.graphrag.company_information import fetch_company_business, fetch_recent_company_news
    from bulsae.graphrag.question_analysis import analyze_question, plan_company_question, plan_question
    from bulsae.graphrag.multihop_search import fetch_executive_events
    from bulsae.graphrag.document_fallback import fetch_document_evidence
    from bulsae.graphrag.graphs import QueryDeps, build_query_graph
    from bulsae.graphrag.related_analysis import generate_related_analysis, compose_final_answer
    model = model or os.getenv('BULSAE_LLM_MODEL', 'gpt-4.1')
    review_model = review_model or os.getenv('BULSAE_REVIEW_MODEL', 'gpt-4.1')
    with driver() as db:
        clients = []
        def client():
            if not clients:
                clients.append(OpenAI(timeout=90, max_retries=1))
            return clients[0]
        def related(question, basic, rows, financial):
            diagnostics = {}
            points = generate_related_analysis(client(), model, question, basic, rows, financial, review_model, diagnostics)
            return {'points':points, 'diagnostics':diagnostics}
        deps = QueryDeps(
            search=lambda name, kind, limit: fetch_evidence(db, name, kind, limit),
            generate=lambda question, evidence: generate_claims(client(), model, question, evidence),
            review=lambda question, claims, evidence: review_claims(client(), review_model, question, claims, evidence),
            identify=lambda question: resolve_question(db, question),
            financial=lambda names: fetch_financials(db, names),
            strategy=lambda name, year: fetch_strategy_evidence(db, name, year),
            context=lambda ids: fetch_document_context(db, ids),
            company_info=lambda name: fetch_company_business(db, name),
            recent_news=lambda name: fetch_recent_company_news(db, name,
                lambda question, evidence: generate_claims(client(), model, question, evidence),
                lambda question, claims, evidence: review_claims(client(), review_model, question, claims, evidence)),
            plan=lambda question, name: plan_company_question(client(), model, question, name),
            combined_plan=lambda question, names: plan_question(client(), model, question, names),
            analyze=lambda question, name: analyze_question(client(), model, question, name),
            multihop=lambda name, role, year: fetch_executive_events(db, name, role, year),
            documents=lambda question, names: fetch_document_evidence(db, question, names),
            business_paths=lambda name, question: fetch_business_paths(db, name, question),
            related=related,
            compose=lambda question, state: compose_final_answer(client(), model, question,
                present_response(state), review_model))
        initial = {'question': question, 'limit': limit}
        if name:
            initial.update(name=name, kind=kind)
        # Values are LangGraph's merged state; updates identify nodes actually run.
        executed_nodes = []
        node_timings = []
        step_started = time.monotonic()
        result = initial
        for mode, payload in build_query_graph(deps).stream(initial, stream_mode=['updates', 'values']):
            if mode == 'values':
                result = payload
            elif mode == 'updates':
                nodes = [key for key in payload if not key.startswith('__')]
                executed_nodes.extend(nodes)
                now = time.monotonic()
                if nodes:
                    node_timings.append({'nodes': nodes, 'elapsed_ms': round((now - step_started) * 1000)})
                    step_started = now
    return result, {'model': model, 'review_model': review_model,
                    'executed_nodes': executed_nodes, 'node_timings': node_timings, 'service_version': 'streamlit-unified-v1',
                    'elapsed_ms': round((time.monotonic() - started) * 1000)}


def answer_question(question):
    result, runtime = execute_question(question)
    response = present_response(result)
    response.update({'question': question, 'run_id': str(uuid.uuid4()),
                     'created_at': datetime.now(timezone.utc).isoformat(),
                     'elapsed_ms': runtime.pop('elapsed_ms')})
    response['trace'].update(runtime)
    response['trace']['answer_status'] = response['status']
    # Keep an auditable per-answer record locally; never write to Neo4j.
    directory = ROOT / 'private_data' / 'query_runs'
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / (response['run_id'] + '.json')).open('x', encoding='utf-8') as handle:
            json.dump(response, handle, ensure_ascii=False, indent=2)
        response['record_saved'] = True
    except OSError:
        response['record_saved'] = False
    return response


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    def headers_common(self, status, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        origin = self.headers.get('Origin')
        if origin in ALLOWED:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.end_headers()
    def send_json(self, status, body):
        self.headers_common(status, 'application/json; charset=utf-8')
        self.wfile.write(json.dumps(body, ensure_ascii=False).encode())
    def allowed(self):
        origin = self.headers.get('Origin')
        return origin is None or origin in ALLOWED
    def do_OPTIONS(self):
        if not self.allowed():
            return self.send_json(403, {'error': '허용되지 않은 요청입니다.'})
        self.headers_common(204, 'text/plain')
    def do_GET(self):
        if not self.allowed():
            return self.send_json(403, {'error': '허용되지 않은 요청입니다.'})
        if urlsplit(self.path).path == '/api/health':
            return self.send_json(200, {'ok': True})
        if urlsplit(self.path).path in ('/', '/index.html'):
            self.headers_common(200, 'text/html; charset=utf-8')
            return self.wfile.write((WEB / 'index.html').read_bytes())
        self.send_json(404, {'error': '찾을 수 없습니다.'})
    def do_POST(self):
        if not self.allowed():
            return self.send_json(403, {'error': '허용되지 않은 요청입니다.'})
        if urlsplit(self.path).path != '/api/ask':
            return self.send_json(404, {'error': '찾을 수 없습니다.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8192 or self.headers.get_content_type() != 'application/json':
                return self.send_json(400, {'error': '질문 형식을 확인해 주세요.'})
            data = json.loads(self.rfile.read(size))
            question = data.get('question')
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1000:
                return self.send_json(400, {'error': '질문은 1~1000자로 입력해 주세요.'})
        except (ValueError, TypeError, AttributeError):
            return self.send_json(400, {'error': '질문 형식을 확인해 주세요.'})
        if not SLOTS.acquire(blocking=False):
            return self.send_json(429, {'error': '다른 질문을 처리 중이에요. 잠시 후 다시 시도해 주세요.'})
        try:
            self.send_json(200, answer_question(question.strip()))
        except Exception:
            self.send_json(500, {'error': '질문 처리에 실패했어요. 서버 설정과 연결을 확인해 주세요.'})
        finally:
            SLOTS.release()


def main():
    print(f'CONNECT 테스트 화면: http://127.0.0.1:{PORT}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()

if __name__ == '__main__':
    main()
