"""M5 결과를 M2 유형·방향의 Neo4j 노드와 직접 관계 후보로 변환한다.

LLM 호출이나 DB 접속 없이 입력 ZIP의 내용을 검증하고 메모리 객체를 반환한다.
서로 다른 근거는 관계 속성의 JSON과 문자열 목록에 보존한다.
"""
from __future__ import annotations

import hashlib
import json
import math
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

# M2에서 허용한 개체 유형과 주어·목적어 방향.
RULES = {
    'HOLDS_POSITION': ({'Person'}, {'Company', 'Organization'}),
    'OWNS_STAKE': ({'Company', 'Person'}, {'Company'}),
    'PART_OF_GROUP': ({'Company'}, {'CorporateGroup'}),
    'OPERATES_BRAND': ({'Company'}, {'Brand'}),
    'PRODUCT_UNDER_BRAND': ({'Product'}, {'Brand'}),
    'PARTICIPATES_IN': ({'Company', 'CorporateGroup', 'Brand', 'Person', 'Organization'}, {'Event'}),
    'REPORTS_METRIC': ({'Company', 'CorporateGroup', 'Brand', 'Market', 'Product'}, {'MetricObservation'}),
    'MARKET_IN_PLACE': ({'Market'}, {'Place'}),
    'EVENT_IN_PLACE': ({'Event'}, {'Place'}),
    'PRODUCT_FEATURED_IN': ({'Product'}, {'Event'}),
    'EVENT_FEATURES': ({'Event'}, {'Character'}),
    'REGULATES': ({'Regulation'}, {'Product', 'Market'}),
}
TYPES = {'Company', 'CorporateGroup', 'Organization', 'Person', 'Character', 'Brand',
         'Product', 'Market', 'Event', 'Place', 'MetricObservation', 'Regulation'}


def dumps(value: Any) -> str:
    """같은 데이터에 대해 항상 같은 유니코드 JSON 문자열을 생성한다."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _read_rows(z: zipfile.ZipFile, filename: str) -> list[dict]:
    matches = [n for n in z.namelist() if n == filename or n.endswith('/' + filename)]
    if len(matches) != 1:
        raise ValueError(f'{filename}: 입력 ZIP 안에 정확히 한 파일이 필요합니다 (발견 {len(matches)}개).')
    result = []
    with z.open(matches[0]) as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError(f'{filename}:{line_no}: JSON 파싱 실패') from exc
            if not isinstance(value, dict):
                raise ValueError(f'{filename}:{line_no}: JSON 객체가 아닙니다.')
            result.append(value)
    return result


def _scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) and not (isinstance(value, float) and not math.isfinite(value))


def _safe_flat(target: dict, values: Any) -> None:
    """조회에 쓸 수 있는 단일 값을 추출하되 기존 중요 키는 덮어쓰지 않는다."""
    if not isinstance(values, dict):
        return
    for key, value in values.items():
        if key not in target and isinstance(key, str) and _scalar(value):
            target[key] = value


def _node(row: dict) -> dict:
    node_id, typ, name = row.get('entity_id'), row.get('type'), row.get('name')
    if not isinstance(node_id, str) or not node_id or typ not in TYPES or not isinstance(name, str) or not name:
        raise ValueError(f'노드 ID·유형·이름 오류: {node_id!r}, {typ!r}, {name!r}')
    properties = {'entity_id': node_id, 'name': name, 'entity_type': typ,
                  'm5_record_json': dumps(row)}
    if isinstance(row.get('identity_status'), str):
        properties['identity_status'] = row['identity_status']
    # 여러 원문 기록의 속성이 서로 다르면 단일 값으로 임의 선택하지 않는다.
    variants = [row.get('attributes')]
    variants.extend(row.get('attribute_variants') or [])
    for source in row.get('source_records', []):
        if isinstance(source, dict) and isinstance(source.get('record'), dict):
            variants.append(source['record'].get('properties'))
    candidates: dict[str, dict[str, Any]] = {}
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        for key, value in variant.items():
            if isinstance(key, str) and _scalar(value):
                candidates.setdefault(key, {})[dumps(value)] = value
    conflicts = []
    for key, values in candidates.items():
        if len(values) == 1 and key not in properties:
            properties[key] = next(iter(values.values()))
        elif len(values) > 1:
            conflicts.append(key)
    if conflicts:
        properties['conflicting_attribute_keys'] = sorted(conflicts)
    return {'id': node_id, 'labels': [typ], 'properties': properties}


def _url(evidence: Any) -> set[str]:
    if not isinstance(evidence, dict):
        return set()
    urls = set()
    meta = evidence.get('source_metadata') or {}
    document = evidence.get('document') or {}
    chunk = evidence.get('chunk') or {}
    for value in (meta.get('source_url'), document.get('url'), chunk.get('source_url')):
        if isinstance(value, str) and value:
            urls.add(value)
    for source in evidence.get('source') or []:
        if isinstance(source, dict) and isinstance(source.get('original_url'), str):
            urls.add(source['original_url'])
    return urls


def _scope_summary(z: zipfile.ZipFile) -> dict:
    files = [n for n in z.namelist() if n.endswith('/summary.json')]
    if len(files) != 1:
        raise ValueError('입력 ZIP에 요약 파일이 하나여야 합니다.')
    return json.loads(z.read(files[0]))


def build_graph(zip_path: str | Path) -> dict:
    """노드와 직접 관계 후보를 반환한다. 잘못된 데이터는 누락하지 않고 오류로 중단한다.

    관계는 주어 ID·관계 유형·목적어 ID·속성이 모두 같을 때만 묶는다.
    출처·인용·원래 관계 ID와 모든 원본 행은 별도 주장 노드 없이 관계 속성에 보존한다.
    """
    path = Path(zip_path)
    if not path.is_file():
        raise FileNotFoundError(f'M5 ZIP을 찾을 수 없습니다: {path}')
    with zipfile.ZipFile(path) as z:
        node_rows = _read_rows(z, 'nodes_in_scope.jsonl')
        news = _read_rows(z, 'news_relations_in_scope.jsonl')
        structured = _read_rows(z, 'structured_disclosure_relations.jsonl')
        chunks = _read_rows(z, 'disclosure_chunks.jsonl')
        summary = _scope_summary(z)
    if len(node_rows) != summary.get('in_scope_nodes') or len(news) != summary.get('in_scope_news_relations') or len(structured) != summary.get('structured_and_disclosure_relations'):
        raise ValueError('입력 건수가 M5 요약과 다릅니다.')
    nodes = [_node(row) for row in node_rows]
    node_by_id = {node['id']: node for node in nodes}
    if len(node_by_id) != len(nodes):
        raise ValueError('M5 노드 ID가 중복됩니다.')
    notes = {c.get('chunk_id'): c for c in chunks if c.get('chunk_id')}
    groups: dict[str, dict] = {}
    relation_ids = set()
    for row in news + structured:
        rid, sub, pred, obj = (row.get(k) for k in ('relation_id', 'subject_id', 'predicate', 'object_id'))
        if not isinstance(rid, str) or not rid or rid in relation_ids:
            raise ValueError(f'관계 ID 누락 또는 중복: {rid!r}')
        relation_ids.add(rid)
        if sub not in node_by_id or obj not in node_by_id:
            raise ValueError(f'{rid}: 연결 노드가 없습니다: {sub!r}, {obj!r}')
        if pred not in RULES:
            raise ValueError(f'{rid}: 허용되지 않은 관계 유형 {pred!r}')
        s_type, o_type = node_by_id[sub]['labels'][0], node_by_id[obj]['labels'][0]
        valid_subject, valid_object = RULES[pred]
        if s_type not in valid_subject or o_type not in valid_object:
            raise ValueError(f'{rid}: M2에 맞지 않는 연결 {s_type} - {pred} -> {o_type}')
        attrs = row.get('attributes')
        if not isinstance(attrs, dict):
            raise ValueError(f'{rid}: 관계 속성이 객체가 아닙니다.')
        ev = row.get('evidence')
        if not isinstance(ev, dict) or not ev:
            raise ValueError(f'{rid}: 관계의 출처 정보가 없습니다.')
        if row.get('source_kind') == 'news' and not all(ev.get(k) for k in ('document_id', 'chunk_id', 'quote')):
            raise ValueError(f'{rid}: 뉴스 문서·청크·원문 근거가 부족합니다.')
        # 모든 속성이 같은지 비교한다. 상태·시점·지분율이 다르면 별도의 관계다.
        semantic = dumps([sub, pred, obj, attrs])
        if semantic not in groups:
            eid = 'REL-' + hashlib.sha256(semantic.encode('utf-8')).hexdigest()
            groups[semantic] = {'id': eid, 'start': sub, 'end': obj, 'type': pred,
                                '_attributes': attrs, '_rows': [], '_urls': set(),
                                '_quotes': set(), '_docs': set(), '_notes': {}}
        group = groups[semantic]
        group['_rows'].append(row)
        group['_urls'].update(_url(ev))
        if isinstance(ev.get('quote'), str) and ev['quote']:
            group['_quotes'].add(ev['quote'])
        if isinstance(ev.get('document_id'), str):
            group['_docs'].add(ev['document_id'])
        elif isinstance(ev.get('document'), dict) and ev['document'].get('id'):
            group['_docs'].add(ev['document']['id'])
        for note_id in ev.get('related_note_chunk_ids') or []:
            if note_id not in notes:
                raise ValueError(f'{rid}: 공시 주석 청크 {note_id!r} 누락')
            group['_notes'][note_id] = notes[note_id]
    relationships = []
    for group in groups.values():
        raw = sorted(group['_rows'], key=lambda x: x['relation_id'])
        props = {'relation_id': group['id'], 'predicate': group['type'],
                 'evidence_count': len(raw), 'source_count': len(raw), 'source_relation_ids': [x['relation_id'] for x in raw],
                 'source_urls': sorted(group['_urls']), 'evidence_quotes': sorted(group['_quotes']),
                 'document_ids': sorted(group['_docs']),
                 'sources_json': dumps(raw),
                 'disclosure_notes_json': dumps(group['_notes']),
                 'attributes_json': dumps(group['_attributes'])}
        _safe_flat(props, group['_attributes'])
        relationships.append({'id': group['id'], 'start': group['start'], 'end': group['end'],
                              'type': group['type'], 'properties': props})
    relationships.sort(key=lambda x: x['id'])
    counts = Counter(r['type'] for r in relationships)
    report = {'input_zip': path.name, 'input_nodes': len(nodes), 'input_news_relations': len(news),
              'input_structured_relations': len(structured), 'input_relation_records': len(relation_ids),
              'mapped_nodes': len(nodes), 'mapped_relationships': len(relationships),
              'evidence_records': sum(r['properties']['evidence_count'] for r in relationships),
              'relationships_by_type': dict(sorted(counts.items())),
              'node_types': dict(sorted(Counter(n['labels'][0] for n in nodes).items())),
              'grouping': '같은 주어·서술어·목적어·전체 속성만 결합; 모든 기존 관계 기록 JSON 보존',
              'status': 'M5 잠정 결과의 형식 매핑; 사실성 검증이나 실제 DB 적재는 아님'}
    if report['evidence_records'] != len(relation_ids):
        raise AssertionError('출처별 관계 기록 보존 건수가 입력과 다릅니다.')
    return {'nodes': nodes, 'relationships': relationships, 'summary': report}
