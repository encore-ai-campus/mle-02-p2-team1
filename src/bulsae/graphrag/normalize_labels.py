"""One-time, transactional normalization of document-kg-v1 candidate type labels.

Only labels change: candidate IDs, nodes, relationships and properties remain.
The generic candidate label remains for identity and its uniqueness constraint.
"""
import json
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

from bulsae.graphrag.document_graph import LABELS, VERSION


def normalize(tx):
    before = tx.run("""
        MATCH (n:BulsaeKGCandidate {pipeline_version: $version})
        RETURN n.entity_type AS kind, count(*) AS count
    """, version=VERSION).data()
    counts = {row['kind']: row['count'] for row in before}
    if not counts or any(kind not in LABELS for kind in counts):
        raise ValueError('Unexpected or missing candidate types; no labels changed')

    total_before = tx.run('MATCH (n) RETURN count(n) AS n').single()['n']
    rel_before = tx.run('MATCH ()-[r]->() RETURN count(r) AS n').single()['n']
    changes = {}
    for kind, canonical in LABELS.items():
        legacy = 'BulsaeKG' + kind
        row = tx.run(f"""
            MATCH (n:BulsaeKGCandidate {{pipeline_version: $version, entity_type: $kind}})
            WITH collect(n) AS nodes
            FOREACH (n IN nodes | SET n:`{canonical}` REMOVE n:`{legacy}`)
            RETURN size(nodes) AS n
        """, version=VERSION, kind=kind).single()
        changes[canonical] = row['n']
        check = tx.run(f"""
            MATCH (n:BulsaeKGCandidate {{pipeline_version: $version, entity_type: $kind}})
            RETURN count(n) AS total,
                   count(CASE WHEN n:`{canonical}` AND NOT n:`{legacy}` THEN 1 END) AS correct
        """, version=VERSION, kind=kind).single()
        if check['total'] != counts.get(kind, 0) or check['correct'] != check['total']:
            raise ValueError(f'Label validation failed for {kind}; transaction rolled back')
    if tx.run('MATCH (n) RETURN count(n) AS n').single()['n'] != total_before:
        raise ValueError('Node count changed; transaction rolled back')
    if tx.run('MATCH ()-[r]->() RETURN count(r) AS n').single()['n'] != rel_before:
        raise ValueError('Relationship count changed; transaction rolled back')
    return {'candidate_labels': changes, 'all_nodes': total_before, 'all_relationships': rel_before}


def main():
    load_dotenv()
    driver = GraphDatabase.driver(os.environ['NEO4J_URI'], auth=(
        os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']))
    try:
        with driver.session(database=os.environ.get('NEO4J_DATABASE', 'neo4j')) as session:
            print(json.dumps(session.execute_write(normalize), ensure_ascii=False, indent=2))
    finally:
        driver.close()


if __name__ == '__main__':
    main()
