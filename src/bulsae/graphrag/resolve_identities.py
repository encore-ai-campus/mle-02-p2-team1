"""Conservatively link well-evidenced duplicate candidates to representative nodes.

No nodes or source relationships are removed. Identity links are provisional,
and must be traversed explicitly when retrieving a representative's evidence.
"""
import argparse
from collections import defaultdict
import json
import os
import re
import unicodedata

from dotenv import load_dotenv
from neo4j import GraphDatabase

PERSON_ROLES = {
    '김승환': r'대표(?:이사)?',
    '권순철': r'안전환경\s*디비전',
    '심혜영': r'인사조직실\s*부사장',
    '이현희': r'지속가능경영센터\s*부장',
}
VERSION = 'identity-resolution-v1'


def backed_texts(row):
    """Only use quoted evidence actually present in the referenced DB document."""
    try:
        items = json.loads(row['evidence'] or '[]')
    except (ValueError, TypeError):
        return []
    content = row['content'] or ''
    return [item.get('text', '') for item in items if isinstance(item, dict)
            and item.get('text') and item['text'] in content]


def find_plan(driver, database):
    with driver.session(database=database, default_access_mode='READ') as session:
        people = session.run("""
          MATCH (p:BulsaePerson:BulsaeKGCandidate)-[r:WORKS_AT]->
                (c:BulsaeCompany {company_id:'COMPANY-AMOREPACIFIC'})
          MATCH (d:BulsaeDocument {document_id:r.source_document_id})
          WHERE p.name IN $names AND r.pipeline_version='document-kg-v1'
          RETURN elementId(p) AS node_id,p.candidate_id AS candidate_id,p.name AS name,
                 r.source_document_id AS document_id,r.kg_observation_id AS observation_id,
                 r.evidence_json AS evidence,d.content AS content
        """, names=list(PERSON_ROLES)).data()
        anchor = session.run("""
          MATCH (p:BulsaePerson {person_id:'PERSON-CANDIDATE-NEWS-46c70231e3ee18db', name:'김승환'})
          RETURN elementId(p) AS node_id
        """).data()
        companies = session.run("""
          MATCH (p:BulsaeCompany:BulsaeKGCandidate)-[r]-(other)
          MATCH (d:BulsaeDocument {document_id:r.source_document_id})
          WHERE r.pipeline_version='document-kg-v1'
            AND (p.name STARTS WITH '㈜' OR p.name STARTS WITH '(주)')
          RETURN elementId(p) AS node_id,p.candidate_id AS candidate_id,p.name AS name,
                 r.source_document_id AS document_id,r.kg_observation_id AS observation_id,
                 r.evidence_json AS evidence,d.content AS content
        """).data()
        targets = session.run("""
          MATCH (c:BulsaeCompany) WHERE c.company_id IS NOT NULL
          RETURN elementId(c) AS node_id,c.company_id AS company_id,c.name AS name
        """).data()

    by_person = defaultdict(dict)
    for row in people:
        name = row['name']
        pattern = re.compile(re.escape(name) + r'.{0,12}아모레퍼시픽.{0,16}' + PERSON_ROLES[name])
        if row['observation_id'] and any(pattern.search(t) for t in backed_texts(row)):
            by_person[name][row['node_id']] = row
    plan = []
    for name, nodes in by_person.items():
        if len(nodes) < 2:
            continue
        representative = anchor[0]['node_id'] if name == '김승환' and len(anchor) == 1 else min(nodes)
        for node_id, row in nodes.items():
            if node_id != representative:
                plan.append({'source': node_id, 'target': representative, 'kind': 'Person',
                             'name': name, 'document_id': row['document_id'],
                             'observation_id': row['observation_id'],
                             'method': 'same_name_company_and_role_in_source'})

    # Legal marker, exact name and source evidence are required; brand mentions
    # without a legal marker are deliberately excluded.
    by_company = {r['name']: r for r in targets}
    seen = set()
    for row in companies:
        normalized = unicodedata.normalize('NFKC', row['name'] or '').replace(' ', '')
        for name, target in by_company.items():
            legal = '(주)' + name.replace(' ', '')
            if normalized != legal or row['node_id'] in seen or not row['observation_id']:
                continue
            if not any(legal in unicodedata.normalize('NFKC', t).replace(' ', '') for t in backed_texts(row)):
                continue
            plan.append({'source': row['node_id'], 'target': target['node_id'], 'kind': 'Company',
                         'name': name, 'document_id': row['document_id'],
                         'observation_id': row['observation_id'], 'method': 'exact_legal_name_in_source'})
            seen.add(row['node_id'])
    return plan


def apply_plan(tx, plan):
    before = tx.run("MATCH ()-[r]->() WHERE r.pipeline_version='document-kg-v1' RETURN count(r) AS n").single()['n']
    nodes_before = tx.run('MATCH (n) RETURN count(n) AS n').single()['n']
    conflict = tx.run("""
      UNWIND $rows AS row
      MATCH (s)-[r:NORMALIZED_AS]->(t)
      WHERE elementId(s)=row.source AND elementId(t)<>row.target
      RETURN count(r) AS n
    """, rows=plan).single()['n']
    if conflict:
        raise ValueError('Candidate already has a different representative; rolled back')
    result = tx.run("""
      UNWIND $rows AS row
      MATCH (s:BulsaeKGCandidate {pipeline_version:'document-kg-v1'}), (t)
      WHERE elementId(s)=row.source AND elementId(t)=row.target
        AND none(label IN labels(s) WHERE label STARTS WITH 'B_')
        AND none(label IN labels(t) WHERE label STARTS WITH 'B_')
        AND (t.pipeline_version='document-kg-v1' OR t.company_id STARTS WITH 'COMPANY-'
             OR t.person_id='PERSON-CANDIDATE-NEWS-46c70231e3ee18db')
      MERGE (s)-[r:NORMALIZED_AS {normalization_version:$version}]->(t)
      ON CREATE SET r.method=row.method, r.source_document_id=row.document_id,
                    r.source_observation_id=row.observation_id, r.verification_status='검토 전'
      RETURN count(*) AS processed
    """, rows=plan, version=VERSION).single()['processed']
    if result != len(plan):
        raise ValueError('Missing or duplicate endpoints; rolled back')
    if tx.run('MATCH (n) RETURN count(n) AS n').single()['n'] != nodes_before:
        raise ValueError('Node count changed; rolled back')
    if tx.run("MATCH ()-[r]->() WHERE r.pipeline_version='document-kg-v1' RETURN count(r) AS n").single()['n'] != before:
        raise ValueError('Source relationship count changed; rolled back')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    load_dotenv()
    driver = GraphDatabase.driver(os.environ['NEO4J_URI'], auth=(os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']))
    try:
        database = os.environ.get('NEO4J_DATABASE', 'neo4j')
        plan = find_plan(driver, database)
        counts = defaultdict(int)
        for row in plan:
            counts[row['kind'] + ':' + row['name']] += 1
        print(json.dumps({'candidate_links': dict(counts), 'total': len(plan), 'applied': args.apply}, ensure_ascii=False))
        if args.apply and plan:
            with driver.session(database=database) as session:
                print('processed:', session.execute_write(apply_plan, plan))
    finally:
        driver.close()


if __name__ == '__main__':
    main()
