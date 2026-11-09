"""Export unresolved Bulsae identity candidates for review without modifying Neo4j."""
import argparse
import json
import os
from collections import Counter
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    load_dotenv()
    db = GraphDatabase.driver(os.environ['NEO4J_URI'],auth=(os.environ['NEO4J_USERNAME'],os.environ['NEO4J_PASSWORD']))
    try:
        rows,_,_=db.execute_query('''MATCH (n:BulsaeKGCandidate)
          WHERE n.pipeline_version='document-kg-v1' AND (n:BulsaePerson OR n:BulsaeCompany)
            AND n.name IS NOT NULL AND none(l IN labels(n) WHERE l STARTS WITH 'B_')
            AND NOT EXISTS { MATCH (n)-[r:NORMALIZED_AS {normalization_version:'identity-resolution-v1'}]->()
                             WHERE coalesce(r.bulsae_audit_status_v1,'') <> '검토 필요' }
          WITH n.entity_type AS kind,n.name AS name,collect({candidate_id:n.candidate_id,
               source_document_id:n.source_document_id,identity_status:n.identity_status}) AS nodes
          WHERE size(nodes)>1
          RETURN kind,name,nodes ORDER BY kind,name''',
          database_=os.environ.get('NEO4J_DATABASE','neo4j'),routing_='r')
        grouped=[r.data() for r in rows]
        with args.output.open('x',encoding='utf-8') as out:
            for row in grouped:
                out.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(json.dumps({'groups':len(grouped),'by_kind':dict(Counter(r['kind'] for r in grouped)),
                          'candidates':sum(len(r['nodes']) for r in grouped),'file':str(args.output)},ensure_ascii=False))
    finally:
        db.close()


if __name__ == '__main__':
    main()
