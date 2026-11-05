from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlsplit

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable


ROOT = Path(__file__).resolve().parents[1]
COLLECTED = ROOT / "data" / "collected" / "suyeon"
COMPANIES_FILE = ROOT / "data" / "shared" / "companies.jsonl"
TARGET_IDS = {"COMPANY-INNISFREE", "COMPANY-ESPOIR"}
FACT_FILES = (
    "company_info.jsonl",
    "social_issues.jsonl",
    "politics.jsonl",
    "market.jsonl",
    "strategies.jsonl",
    "owners.jsonl",
)
BATCH_SIZE = 100


class DataError(Exception):
    pass


class ConnectionConfigError(Exception):
    pass


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise DataError(f"필수 파일이 없습니다: {path.relative_to(ROOT)}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DataError(
                f"{path.relative_to(ROOT)}:{line_number} JSON 오류: {exc.msg}"
            ) from None
        if not isinstance(row, dict):
            raise DataError(f"{path.relative_to(ROOT)}:{line_number} 객체가 아닙니다.")
        rows.append(row)
    return rows


def load_suyeon_data() -> dict[str, Any]:
    companies = [
        row for row in read_jsonl(COMPANIES_FILE)
        if row.get("company_id") in TARGET_IDS
    ]
    companies_by_id = {row["company_id"]: row for row in companies}
    if set(companies_by_id) != TARGET_IDS:
        raise DataError("공통 기업 목록에 이니스프리·에스쁘아 ID가 모두 있어야 합니다.")

    documents = read_jsonl(COLLECTED / "documents.jsonl")
    documents_by_id = {row["document_id"]: row for row in documents}
    if len(documents_by_id) != len(documents):
        raise DataError("documents.jsonl에 중복 document_id가 있습니다.")

    facts: list[dict[str, Any]] = []
    per_file: dict[str, int] = {}
    for filename in FACT_FILES:
        rows = read_jsonl(COLLECTED / filename)
        per_file[filename] = len(rows)
        facts.extend(rows)

    fact_ids = [row.get("record_id") for row in facts]
    if len(fact_ids) != len(set(fact_ids)):
        raise DataError("조사 파일 사이에 중복 record_id가 있습니다.")

    for document in documents:
        unknown = set(document.get("company_ids") or []) - set(companies_by_id)
        if unknown:
            raise DataError(
                f"{document.get('document_id')}가 수연 범위 밖 회사 ID를 참조합니다: "
                + ", ".join(sorted(unknown))
            )
        if not document.get("clean_text"):
            raise DataError(f"{document.get('document_id')}의 clean_text가 비어 있습니다.")
        if re.search(
            r"(ServiceKey|OPENDART_API_KEY|DATA_GO_KR_API_KEY)\s*=",
            document.get("original_url") or "",
            re.IGNORECASE,
        ):
            raise DataError(f"{document.get('document_id')} URL에 인증정보가 있습니다.")

    for fact in facts:
        if fact.get("company_id") not in companies_by_id:
            raise DataError(f"{fact.get('record_id')}의 company_id가 수연 범위와 다릅니다.")
        if fact.get("document_id") not in documents_by_id:
            raise DataError(f"{fact.get('record_id')}의 document_id가 없습니다.")

    return {
        "companies": companies,
        "documents": documents,
        "facts": facts,
        "fact_counts": per_file,
    }


def safe_properties(row: dict[str, Any], excluded: set[str]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for key, value in row.items():
        if key in excluded or value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            props[key] = value
        elif isinstance(value, list) and all(
            isinstance(item, (str, int, float, bool)) for item in value
        ):
            props[key] = value
        else:
            props[key] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return props


def chunks(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [rows[i : i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]


def load_connection_settings() -> tuple[str, str, str, str]:
    load_dotenv(ROOT / ".env")
    uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687").strip()
    username = os.getenv("NEO4J_USERNAME", "neo4j").strip()
    password = os.getenv("NEO4J_PASSWORD", "")
    database = os.getenv("NEO4J_DATABASE", "neo4j").strip()
    parsed = urlsplit(uri)
    if not parsed.scheme or not parsed.hostname:
        raise ConnectionConfigError("NEO4J_URI 형식이 올바르지 않습니다.")
    if parsed.username or parsed.password:
        raise ConnectionConfigError(
            "NEO4J_URI에 사용자명·비밀번호를 넣지 말고 별도 환경변수로 설정하세요."
        )
    if not username or not password:
        raise ConnectionConfigError(
            ".env에 NEO4J_USERNAME과 NEO4J_PASSWORD를 설정해야 합니다. "
            "비밀번호는 채팅에 보내지 마세요."
        )
    return uri, username, password, database


def create_driver():
    uri, username, password, _ = load_connection_settings()
    return GraphDatabase.driver(uri, auth=(username, password))


def verify_connection() -> str:
    _, _, _, database = load_connection_settings()
    try:
        with create_driver() as driver:
            driver.verify_connectivity()
            record = driver.execute_query(
                "RETURN 1 AS ok",
                database_=database,
            ).records[0]
            if record["ok"] != 1:
                raise ConnectionConfigError("Neo4j 연결 확인 쿼리가 예상과 다릅니다.")
            return driver.get_server_info().agent
    except AuthError:
        raise ConnectionConfigError(
            "Neo4j 인증에 실패했습니다. 로컬 .env의 URI·사용자명·비밀번호를 확인하세요."
        ) from None
    except ServiceUnavailable:
        raise ConnectionConfigError(
            "Neo4j 주소에 연결할 수 없습니다. 서버 실행 상태와 NEO4J_URI를 확인하세요."
        ) from None
    except Neo4jError as exc:
        raise ConnectionConfigError(
            f"Neo4j 요청 실패: {type(exc).__name__}"
        ) from None


def ensure_schema(tx) -> None:
    tx.run(
        "CREATE CONSTRAINT connect_company_id IF NOT EXISTS "
        "FOR (c:Company) REQUIRE c.company_id IS UNIQUE"
    ).consume()
    tx.run(
        "CREATE CONSTRAINT connect_document_id IF NOT EXISTS "
        "FOR (d:Document) REQUIRE d.document_id IS UNIQUE"
    ).consume()
    tx.run(
        "CREATE CONSTRAINT connect_fact_record_id IF NOT EXISTS "
        "FOR (f:Fact) REQUIRE f.record_id IS UNIQUE"
    ).consume()
    tx.run(
        "CREATE FULLTEXT INDEX connect_suyeon_fact_search IF NOT EXISTS "
        "FOR (f:Fact) ON EACH [f.content, f.evidence_text]"
    ).consume()


def merge_companies(tx, rows: list[dict[str, Any]]) -> None:
    tx.run(
        "UNWIND $rows AS row "
        "MERGE (c:Company {company_id: row.company_id}) "
        "SET c += row.properties",
        rows=rows,
    ).consume()


def merge_documents(tx, rows: list[dict[str, Any]]) -> None:
    tx.run(
        "UNWIND $rows AS row "
        "MERGE (d:Document {document_id: row.document_id}) "
        "SET d += row.properties",
        rows=rows,
    ).consume()
    links = [
        {"company_id": company_id, "document_id": row["document_id"]}
        for row in rows
        for company_id in row.get("company_ids", [])
        if company_id in TARGET_IDS
    ]
    if links:
        tx.run(
            "UNWIND $rows AS row "
            "MATCH (c:Company {company_id: row.company_id}) "
            "MATCH (d:Document {document_id: row.document_id}) "
            "MERGE (c)-[:HAS_DOCUMENT]->(d)",
            rows=links,
        ).consume()


def merge_facts(tx, rows: list[dict[str, Any]]) -> None:
    tx.run(
        "UNWIND $rows AS row "
        "MERGE (f:Fact {record_id: row.record_id}) "
        "SET f += row.properties "
        "WITH f, row "
        "MATCH (c:Company {company_id: row.company_id}) "
        "MATCH (d:Document {document_id: row.document_id}) "
        "MERGE (c)-[:HAS_FACT]->(f) "
        "MERGE (f)-[:SUPPORTED_BY]->(d)",
        rows=rows,
    ).consume()


def load_data() -> dict[str, Any]:
    data = load_suyeon_data()
    _, _, _, database = load_connection_settings()
    company_rows = [
        {
            "company_id": row["company_id"],
            "properties": safe_properties(row, {"company_id"}),
        }
        for row in data["companies"]
    ]
    document_rows = [
        {
            "document_id": row["document_id"],
            "company_ids": row.get("company_ids") or [],
            "properties": safe_properties(
                row, {"document_id", "company_ids", "raw_path"}
            ),
        }
        for row in data["documents"]
    ]
    fact_rows = [
        {
            "record_id": row["record_id"],
            "company_id": row["company_id"],
            "document_id": row["document_id"],
            "properties": safe_properties(row, {"record_id"}),
        }
        for row in data["facts"]
    ]
    with create_driver() as driver:
        with driver.session(database=database) as session:
            session.execute_write(ensure_schema)
            for batch in chunks(company_rows):
                session.execute_write(merge_companies, batch)
            for batch in chunks(document_rows):
                session.execute_write(merge_documents, batch)
            for batch in chunks(fact_rows):
                session.execute_write(merge_facts, batch)
            counts = session.run(
                "MATCH (c:Company) WHERE c.company_id IN $ids "
                "WITH collect(c) AS companies "
                "UNWIND companies AS c "
                "OPTIONAL MATCH (c)-[:HAS_DOCUMENT]->(d:Document) "
                "WITH companies, collect(DISTINCT d) AS documents "
                "UNWIND companies AS c "
                "OPTIONAL MATCH (c)-[:HAS_FACT]->(f:Fact) "
                "RETURN size(companies) AS companies, "
                "size(documents) AS documents, count(DISTINCT f) AS facts",
                ids=sorted(TARGET_IDS),
            ).single()
    return {
        "companies": len(data["companies"]),
        "documents": len(data["documents"]),
        "facts": len(data["facts"]),
        "fact_counts": data["fact_counts"],
        "database_counts": dict(counts) if counts else {},
    }


class SearchState(TypedDict):
    query: str
    limit: int
    hits: list[dict[str, Any]]


def escape_lucene_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z0-9가-힣]+", query)
    if not terms:
        return ""
    return " OR ".join(f'"{term}"' for term in terms)


def search_facts(query: str, limit: int = 5) -> list[dict[str, Any]]:
    search_expression = escape_lucene_query(query)
    if not search_expression:
        return []
    _, _, _, database = load_connection_settings()
    cypher = (
        "CALL db.index.fulltext.queryNodes('connect_suyeon_fact_search', $search) "
        "YIELD node, score "
        "MATCH (company:Company)-[:HAS_FACT]->(node) "
        "OPTIONAL MATCH (node)-[:SUPPORTED_BY]->(document:Document) "
        "RETURN company.input_name AS company, node.record_id AS record_id, "
        "node.domain AS domain, node.content AS content, "
        "node.evidence_text AS evidence_text, "
        "node.evidence_location AS evidence_location, "
        "document.title AS source_title, document.original_url AS source_url, "
        "score ORDER BY score DESC LIMIT $limit"
    )
    with create_driver() as driver:
        with driver.session(database=database) as session:
            return [
                record.data()
                for record in session.run(
                    cypher,
                    search=search_expression,
                    limit=max(1, min(limit, 20)),
                )
            ]


def build_search_graph():
    def retrieve(state: SearchState) -> dict[str, Any]:
        return {"hits": search_facts(state["query"], state.get("limit", 5))}

    graph = StateGraph(SearchState)
    graph.add_node("retrieve", retrieve)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", END)
    return graph.compile()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="이니스프리·에스쁘아 JSONL 자료를 Neo4j에 적재하고 근거를 검색합니다."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="JSONL과 참조 연결을 확인합니다.")
    commands.add_parser("check", help="Neo4j 연결만 확인합니다.")
    commands.add_parser("load", help="수연 담당 노드와 관계를 멱등 적재합니다.")
    search = commands.add_parser("search", help="LangGraph로 적재된 근거를 검색합니다.")
    search.add_argument("query", help="검색어")
    search.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    try:
        if args.command == "validate":
            data = load_suyeon_data()
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "companies": len(data["companies"]),
                        "documents": len(data["documents"]),
                        "facts": len(data["facts"]),
                        "fact_counts": data["fact_counts"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "check":
            print(f"Neo4j 연결 확인 완료: {verify_connection()}")
        elif args.command == "load":
            print(json.dumps(load_data(), ensure_ascii=False, indent=2))
        elif args.command == "search":
            if not args.query.strip():
                raise DataError("검색어를 입력하세요.")
            result = build_search_graph().invoke(
                {"query": args.query, "limit": args.limit, "hits": []}
            )
            print(json.dumps(result["hits"], ensure_ascii=False, indent=2))
        return 0
    except (DataError, ConnectionConfigError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    except AuthError:
        print(
            "오류: Neo4j 인증에 실패했습니다. 로컬 .env 설정을 확인하세요.",
            file=sys.stderr,
        )
        return 3
    except ServiceUnavailable:
        print(
            "오류: Neo4j 서버에 연결할 수 없습니다. 서버와 NEO4J_URI를 확인하세요.",
            file=sys.stderr,
        )
        return 4
    except Neo4jError as exc:
        print(f"Neo4j 요청 실패: {type(exc).__name__}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
