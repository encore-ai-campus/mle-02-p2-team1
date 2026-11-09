"""Audit only document-kg-v1 relationships; never certify disputed facts."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase
from bulsae.graphrag.document_graph import PATTERNS

KEYWORDS = {
    'PARTNERS_WITH': ('협력','협업','제휴','파트너','협약','협정','공동','함께','MOU','맞손'),
    'PARENT_OF': ('자회사','모회사','계열사','인수','보유','지분','편입','종속','지주','소유'),
    'ANNOUNCED_STRATEGY': ('전략','계획','목표','추진','발표','비전','방침'),
}


def flags(row):
    result = []
    content = row.get('content')
    if not isinstance(content, str):
        return ['source_document_missing']
    if row.get('hash') != hashlib.sha256(content.encode('utf-8')).hexdigest():
        result.append('source_content_changed')
    try:
        items = json.loads(row.get('evidence') or '[]')
        if not isinstance(items,list) or not items:
            raise ValueError('empty evidence')
        for item in items:
            text, start, end = item['text'], item['start'], item['end']
            if not isinstance(text,str) or not isinstance(start,int) or not isinstance(end,int) or content[start:end] != text:
                result.append('evidence_offset_mismatch')
                break
        passage = '\n'.join(i.get('text','') for i in items)
    except (ValueError, TypeError, KeyError, AttributeError):
        return result + ['invalid_evidence']
    if (row.get('source_type'), row.get('target_type')) not in PATTERNS.get(row.get('relation'), set()):
        result.append('invalid_relation_pattern')
    keywords = KEYWORDS.get(row.get('relation'))
    if keywords and not any(word.casefold() in passage.casefold() for word in keywords):
        result.append('relation_word_not_obvious')
    return list(dict.fromkeys(result))


def audit(db, database):
    rows,_,_=db.execute_query('''MATCH (a)-[r]->(b)
      WHERE r.pipeline_version='document-kg-v1' AND r.kg_observation_id IS NOT NULL
        AND none(l IN labels(a)+labels(b) WHERE l STARTS WITH 'B_')
      OPTIONAL MATCH (d:BulsaeDocument {document_id:r.source_document_id})
      WHERE none(l IN labels(d) WHERE l STARTS WITH 'B_')
      RETURN elementId(r) AS id,r.kg_observation_id AS observation_id,
             type(r) AS relation,coalesce(a.entity_type, CASE WHEN a:BulsaeCompany THEN 'Company' END) AS source_type,
             coalesce(b.entity_type, CASE WHEN b:BulsaeCompany THEN 'Company' END) AS target_type,
             r.document_content_sha256 AS hash,r.evidence_json AS evidence,d.content AS content''',
      database_=database,routing_='r')
    result=[]
    for record in rows:
        row=record.data()
        issues=flags(row)
        if issues:
            result.append({'id':row['id'],'observation_id':row['observation_id'],
                           'relation':row['relation'],'flags':issues})
    return len(rows),result


def mark(tx, issues):
    # Explicit scope and distinct technical properties; no original evidence,
    # relationship or other project's data is overwritten or removed.
    result=tx.run('''UNWIND $rows AS row MATCH (a)-[r]->(b)
      WHERE elementId(r)=row.id AND r.kg_observation_id=row.observation_id
        AND r.pipeline_version='document-kg-v1'
        AND none(l IN labels(a)+labels(b) WHERE l STARTS WITH 'B_')
      SET r.bulsae_audit_status_v1='검토 필요', r.bulsae_audit_flags_v1=row.flags
      RETURN count(r) AS n''',rows=issues).single()['n']
    if result != len(issues):
        raise ValueError('audit candidates changed; transaction rolled back')
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mark',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    load_dotenv()
    db=GraphDatabase.driver(os.environ['NEO4J_URI'],auth=(os.environ['NEO4J_USERNAME'],os.environ['NEO4J_PASSWORD']))
    database=os.environ.get('NEO4J_DATABASE','neo4j')
    try:
        total, issues=audit(db,database)
        report={'total':total,'flagged':len(issues),'flags':dict(Counter(f for r in issues for f in r['flags'])),
                'issues':issues}
        with args.output.open('x',encoding='utf-8') as out:
            json.dump(report,out,ensure_ascii=False,indent=2)
        print(json.dumps({k:v for k,v in report.items() if k!='issues'},ensure_ascii=False),flush=True)
        if args.mark and issues:
            with db.session(database=database) as session:
                print('검토 필요로 표시:',session.execute_write(mark,issues),flush=True)
    finally:
        db.close()


if __name__ == '__main__':
    main()
