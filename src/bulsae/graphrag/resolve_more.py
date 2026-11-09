"""Link further identity candidates with explicit evidence, leaving ambiguity unresolved."""
import argparse
from collections import Counter, defaultdict
import json
import os
import re
import unicodedata

from dotenv import load_dotenv
from neo4j import GraphDatabase
from bulsae.graphrag.resolve_identities import apply_plan, backed_texts

ROLE = re.compile(r'^(?:[가-힣A-Za-z· ]{0,16}?)(대표이사|사무총장|이사장|연구원장|부사장|센터장|대표|회장|사장|상무|파트너|총장|부장)(?:[은는이가을를,\.\s(]|$)')
DISTINCT_COMPANIES = {'아모레퍼시픽홀딩스', 'LG생활건강', '비올메디컬', '하이어코퍼레이션', '제네시스네스트'}


def person_key(row):
    name, company = row['name'] or '', row['company'] or ''
    if not re.fullmatch(r'[가-힣]{2,4}', name) or len(company) < 2:
        return None
    pattern = re.compile(re.escape(name) + r'\s+' + re.escape(company) + r'\s+')
    found = set()
    for text in backed_texts(row):
        for match in pattern.finditer(text):
            role = ROLE.match(text[match.end():])
            if role:
                found.add(role.group(1))
    return (name, company, next(iter(found))) if len(found) == 1 else None


def legal_key(row):
    name = unicodedata.normalize('NFKC', row['name'] or '').replace(' ', '')
    if not (name.startswith('(주)') and len(name) >= 5) and name not in DISTINCT_COMPANIES:
        return None
    for text in backed_texts(row):
        if name in unicodedata.normalize('NFKC', text).replace(' ', ''):
            return name
    return None


def make_plan(rows, existing, anchors, kind):
    groups = defaultdict(dict)
    for row in rows:
        key = person_key(row) if kind == 'Person' else legal_key(row)
        if key and row['observation_id']:
            groups[key][row['node_id']] = row
    # If evidence gives a candidate competing identities, do not resolve it.
    membership = Counter(node for nodes in groups.values() for node in nodes)
    result, skipped = [], 0
    for key, nodes in groups.items():
        nodes = {node: row for node, row in nodes.items() if membership[node] == 1}
        if len(nodes) < 2:
            continue
        known = {existing[node] for node in nodes if node in existing} | (set(nodes) & anchors)
        if len(known) > 1:
            skipped += 1
            continue
        representative = next(iter(known)) if known else min(nodes, key=lambda n: nodes[n]['candidate_id'])
        if representative in existing:
            skipped += 1
            continue
        for node, row in nodes.items():
            if node == representative or node in existing:
                continue
            result.append({'source': node, 'target': representative, 'kind': kind,
                           'name': row['name'], 'document_id': row['document_id'],
                           'observation_id': row['observation_id'],
                           'method': ('same_name_employer_role_in_source' if kind == 'Person'
                                      else 'exact_company_name_in_source')})
    return result, skipped


def run(driver, database):
    with driver.session(database=database, default_access_mode='READ') as s:
        people = s.run("""
          MATCH (p:BulsaePerson:BulsaeKGCandidate)-[r:WORKS_AT]->(c)
          MATCH (d:BulsaeDocument {document_id:r.source_document_id})
          WHERE r.pipeline_version='document-kg-v1' AND p.pipeline_version='document-kg-v1'
            AND (c:BulsaeCompany OR c:BulsaeOrganization)
            AND (c.pipeline_version='document-kg-v1' OR c.company_id STARTS WITH 'COMPANY-')
          RETURN elementId(p) AS node_id,p.candidate_id AS candidate_id,p.name AS name,
                 c.name AS company,r.source_document_id AS document_id,r.kg_observation_id AS observation_id,
                 r.evidence_json AS evidence,d.content AS content
        """).data()
        companies = s.run("""
          MATCH (p:BulsaeCompany:BulsaeKGCandidate)-[r]-(other)
          MATCH (d:BulsaeDocument {document_id:r.source_document_id})
          WHERE r.pipeline_version='document-kg-v1' AND p.pipeline_version='document-kg-v1'
            AND (p.name STARTS WITH '㈜' OR p.name STARTS WITH '(주)' OR p.name IN $names)
          RETURN elementId(p) AS node_id,p.candidate_id AS candidate_id,p.name AS name,
                 r.source_document_id AS document_id,r.kg_observation_id AS observation_id,
                 r.evidence_json AS evidence,d.content AS content
        """, names=sorted(DISTINCT_COMPANIES)).data()
        mappings = s.run("MATCH (s)-[:NORMALIZED_AS {normalization_version:'identity-resolution-v1'}]->(t) RETURN elementId(s) AS source,elementId(t) AS target").data()
    existing = {r['source']: r['target'] for r in mappings}
    anchors = {r['target'] for r in mappings}
    a, skip_a = make_plan(people, existing, anchors, 'Person')
    b, skip_b = make_plan(companies, existing, anchors, 'Company')
    return a+b, skip_a+skip_b


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    load_dotenv()
    db = GraphDatabase.driver(os.environ['NEO4J_URI'], auth=(os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']))
    database = os.environ.get('NEO4J_DATABASE', 'neo4j')
    try:
        plan, skipped = run(db, database)
        print(json.dumps({'by_kind':dict(Counter(p['kind'] for p in plan)),
                          'by_name':dict(Counter(p['name'] for p in plan)),
                          'ambiguous_groups_skipped':skipped,'total':len(plan)}, ensure_ascii=False), flush=True)
        if args.apply and plan:
            with db.session(database=database) as session:
                print('processed:', session.execute_write(apply_plan, plan), flush=True)
    finally:
        db.close()


if __name__ == '__main__':
    main()
