"""기업 목록을 그래프에 넣기 전, Company 노드 모양으로 살펴본다.

이 단계는 데이터베이스에 연결하거나 원본 파일을 수정하지 않는다.
"""

import json
from pathlib import Path


def make_company_nodes(file_path: Path) -> list[dict]:
    """JSONL의 기업 한 줄을 Company 노드 후보 하나로 바꾼다."""
    nodes = []
    seen_ids = set()

    with file_path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            company = json.loads(line)
            company_id = company["company_id"]
            if not isinstance(company_id, str) or not company_id.strip():
                raise ValueError(f"{line_number}번째 줄의 company_id가 비어 있습니다")
            if company_id in seen_ids:
                raise ValueError(f"중복된 company_id: {company_id}")
            seen_ids.add(company_id)

            nodes.append({
                "label": "Company",
                "company_id": company_id,
                "name": company["input_name"],
                "legal_name": company.get("legal_name"),
                "dart_corp_code": company.get("dart_corp_code"),
                "is_target": True,
            })
    return nodes


if __name__ == "__main__":
    path = Path("data/collected/companies.jsonl")
    company_nodes = make_company_nodes(path)
    print(f"기업 노드 후보: {len(company_nodes)}개")
    for node in company_nodes:
        print(f"{node['company_id']} | {node['name']} | 조사 대상: {node['is_target']}")
