"""M5 결과의 서로 다른 세 시상식 오병합을 원문 근거 기준으로 분리한다.

입력 ZIP을 수정하지 않는다. DB에 접근하지 않는다.
세 행사에 속한 문서 ID와 원래 개체 ID를 고정한 재현 가능한 교정이다.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import zipfile

PREFIX = 'M5_remaining_quick/'
OLD_ID = 'EVENT-RULE-c54dfcd323152a767b51'
EXPECTED_SHA256 = 'b5672d880c7a941fd02760f3c8cb48bbf036fb41fcd47d0b617549b816855f35'
NEW_STATUS = 'M8_원문확인_행사분리_관계검토필요'
GROUPS = {
    '2024': {'id':'EVENT-M8-2024-JEJU-GREEN-AWARDS', 'name':'2024 제주 그린어워드 시상식',
             'chunks': ['NEWS-4a5ceaf475a9e95d-C00001', 'NEWS-10ab280be958bd7d-C00001']},
    '2025': {'id':'EVENT-M8-2025-JEJU-GREEN-AWARDS', 'name':'2025 제주 그린어워드 시상식',
             'chunks': ['NEWS-9935a01d1eed55f8-C00001']},
    '2026': {'id':'EVENT-M8-2026-KAS-BRAND-AWARDS', 'name':'한국광고학회 2026 올해의 브랜드상 시상식',
             'chunks': ['NEWS-b1153bd4291d51f7-C00001', 'NEWS-5e799eb705740d49-C00001',
                        'NEWS-2393422a77ceee94-C00001', 'NEWS-b7f8133d03f2528c-C00001',
                        'NEWS-3c5234422dfa5279-C00001', 'NEWS-3b21321e80d0a5d0-C00001',
                        'NEWS-3843a7d236eacb14-C00001']},
}


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8') + b'\n'


def read_lines(blob):
    return [(line, json.loads(line)) for line in blob.splitlines(keepends=True) if line.strip()]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--audit',type=Path,required=True)
    args=parser.parse_args()
    if not args.input.is_file(): raise FileNotFoundError(args.input)
    if args.output.resolve()==args.input.resolve() or args.output.exists() or args.audit.exists():
        raise ValueError('입력을 덮어쓰지 않으며 출력 파일은 새 이름이어야 합니다.')
    if sha(args.input)!=EXPECTED_SHA256:
        raise ValueError('입력 ZIP이 검증한 M5 스냅샷과 다릅니다. 교정 중단.')
    chunk_to_key={chunk:key for key,g in GROUPS.items() for chunk in g['chunks']}
    with zipfile.ZipFile(args.input) as z:
        content={i.filename:z.read(i.filename) for i in z.infolist() if not i.is_dir()}
    result_dir=PREFIX+'results/'
    maps=read_lines(content[result_dir+'nonperson_mention_mappings.jsonl'])
    target_maps=[row for _,row in maps if row.get('new_entity_id')==OLD_ID]
    if len(target_maps)!=10: raise ValueError('원본 행사 언급이 예상한 10개가 아닙니다.')
    if {row['source_mention']['chunk_id'] for row in target_maps}!=set(chunk_to_key):
        raise ValueError('행사별 원본 청크 구성이 검증한 목록과 다릅니다.')
    old_to_key={row['old_entity_id']:chunk_to_key[row['source_mention']['chunk_id']] for row in target_maps}
    if len(old_to_key)!=10: raise ValueError('원래 개체 ID가 중복됩니다.')
    target_ids=set(old_to_key)
    rel_lines=read_lines(content[result_dir+'news_relations_in_scope.jsonl'])
    target_rels=[]; new_rel_lines=[]; rel_audit=[]
    for raw,r in rel_lines:
        sides=[side for side in ('subject','object') if r.get(side+'_id')==OLD_ID]
        if not sides:
            new_rel_lines.append(raw);continue
        if len(sides)!=1: raise ValueError('교정할 관계의 대상 면이 유일하지 않습니다.')
        side=sides[0];original=r.get('original_'+side+'_id');chunk=r.get('evidence',{}).get('chunk_id')
        if original not in old_to_key or chunk_to_key.get(chunk)!=old_to_key[original]:
            raise ValueError(f"원래 개체와 근거 청크가 다른 행사로 연결됨: {r['relation_id']}")
        key=old_to_key[original]; out=copy.deepcopy(r)
        out[side+'_id']=GROUPS[key]['id'];out[side+'_resolution']=NEW_STATUS
        # 나머지 원문·출처·수치·날짜·기존 관계 ID는 변경하지 않는다.
        target_rels.append((r,out));new_rel_lines.append(dump(out))
        rel_audit.append({'relation_id':r['relation_id'],'side':side,'before_id':OLD_ID,
                          'after_id':out[side+'_id'],'original_mention_id':original,
                          'document_id':r['evidence']['document_id'],'chunk_id':chunk,
                          'event_group':key})
    if len(target_rels)!=11: raise ValueError('교정 대상 관계가 예상한 11개가 아닙니다.')
    expected_rel_ids={rid for row in target_maps for rid in row['related_relation_ids']}
    if expected_rel_ids!={r['relation_id'] for r,_ in target_rels}:
        raise ValueError('개체 언급별 관계와 교정 대상 관계가 다릅니다.')
    content[result_dir+'news_relations_in_scope.jsonl']=b''.join(new_rel_lines)
    for _,row in maps:
        if row.get('new_entity_id')==OLD_ID:
            row['new_entity_id']=GROUPS[old_to_key[row['old_entity_id']]]['id']
            row['identity_status']=NEW_STATUS
    # 변경하지 않은 줄은 원본 바이트를 그대로 유지한다.
    content[result_dir+'nonperson_mention_mappings.jsonl']=b''.join(
        dump(row) if row.get('old_entity_id') in target_ids else raw for raw,row in maps)
    created_nodes=None
    for name in ('new_nonperson_nodes.jsonl','nodes_in_scope.jsonl'):
        rows=read_lines(content[result_dir+name]);original=[row for _,row in rows if row.get('entity_id')==OLD_ID]
        if len(original)!=1 or set(original[0]['old_ids'])!=target_ids:
            raise ValueError(f'{name}: 대상 노드 또는 원본 언급 구성이 다릅니다.')
        existing={row.get('entity_id') for _,row in rows}
        if any(g['id'] in existing for g in GROUPS.values()):raise ValueError('새 노드 ID가 이미 존재합니다.')
        new=[]
        for key,g in GROUPS.items():
            node=copy.deepcopy(original[0]);node['entity_id']=g['id'];node['name']=g['name']
            node['identity_status']=NEW_STATUS
            node['old_ids']=[oid for oid in original[0]['old_ids'] if old_to_key[oid]==key]
            node['review_flags']=['M8_시상식_원문기준_분리','관계별_추가검토필요']
            new.append(node)
        if created_nodes is None:created_nodes=new
        elif created_nodes!=new:raise ValueError('두 노드 파일의 교정 결과가 다릅니다.')
        content[result_dir+name]=b''.join((b''.join(dump(n) for n in new) if row.get('entity_id')==OLD_ID else raw) for raw,row in rows)
    summary=json.loads(content[result_dir+'summary.json']);previous_nodes=summary['in_scope_nodes']
    if previous_nodes!=12247:raise ValueError('기준 노드 건수가 다릅니다.')
    summary['in_scope_nodes']=previous_nodes+2
    counts=summary['new_nodes_by_status'];counts['행사_동일표기_연도구분_잠정']-=1;counts[NEW_STATUS]=3
    summary['m8_event_split']={'original_entity_id':OLD_ID,'new_entity_ids':[g['id'] for g in GROUPS.values()],
        'original_mentions':10,'changed_news_relations':11,'source_input_sha256':EXPECTED_SHA256,
        'meaning':'각 원문을 검토해 서로 다른 시상식을 분리; 전체 데이터의 사실 검증은 아님'}
    summary['status']='M5 잠정 결과에 M8 시상식 1건 오병합 분리 반영; 나머지 사실·관계 검토 필요'
    content[result_dir+'summary.json']=json.dumps(summary,ensure_ascii=False,indent=2).encode('utf8')+b'\n'
    manifest={'correction':'M8_EVENT_SPLIT_001','input_sha256':EXPECTED_SHA256,'old_entity_id':OLD_ID,
      'groups':[{'key':k,'entity_id':g['id'],'name':g['name'],'chunks':g['chunks'],
                 'old_mention_ids':[x for x in old_to_key if old_to_key[x]==k]} for k,g in GROUPS.items()],
      'relations':rel_audit,'before_node':original[0],'after_nodes':created_nodes}
    content[PREFIX+'M8_event_split_audit.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8')+b'\n'
    intro=('# M8 시상식 오병합 교정본\n\n서로 다른 시상식 3개를 분리한 **별도 결과**입니다. '
           '원본 ZIP은 변경하지 않았습니다. `resolve_remaining.py`만 재실행하면 원래 오병합이 다시 생깁니다. '
           '교정 과정과 전후 ID는 `M8_event_split_audit.json`, 교정 코드는 별도 M8 패키지를 확인하세요. '
           '노드 12,249개, 뉴스 관계 17,698건, 구조화·공시 관계 28건입니다. '
           '아래 설명은 교정 전 M5 기준의 과거 기록입니다.\n\n---\n\n')
    content[PREFIX+'README.md']=intro.encode('utf8')+content[PREFIX+'README.md']
    args.output.parent.mkdir(parents=True,exist_ok=True);args.audit.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.output,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name,blob in content.items():z.writestr(name,blob)
    args.audit.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'input_sha256':EXPECTED_SHA256,'output_sha256':sha(args.output),
      'old_id':OLD_ID,'new_ids':[g['id'] for g in GROUPS.values()],
      'nodes_before':previous_nodes,'nodes_after':summary['in_scope_nodes'],
      'mentions_changed':len(target_maps),'relations_changed':len(target_rels)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
