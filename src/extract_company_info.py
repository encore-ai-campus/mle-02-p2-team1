from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "data" / "collected"
RAW_COMPANIES = ROOT / "data" / "raw" / "companies"
TARGETS_FILE = ROOT / "config" / "targets.json"
OWNER_PREFIX = {"suyeon": "SY", "anna": "AN", "seonghyeon": "SH"}
METRICS = {
    "revenue": re.compile(r"^매출액\s*\|"),
    "operating_profit": re.compile(r"^영업이익(?:\(손실\))?\s*\||^영업손실\s*\|"),
    "net_income": re.compile(r"^당기순이익(?:\(손실\))?\s*\|"),
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def iso_date(value: Any) -> str | None:
    text = str(value or "")
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    return None


def parse_amount(value: str) -> int | None:
    value = value.strip().replace(",", "")
    if not value:
        return None
    negative = value.startswith("(") and value.endswith(")")
    value = value.strip("()")
    if not re.fullmatch(r"-?\d+", value):
        return None
    amount = int(value)
    return -amount if negative else amount


def current_period_value(line: str) -> str | None:
    cells = [cell.strip() for cell in line.split("|")]
    return cells[3] if len(cells) > 3 and cells[3] else None


def extract_financials(text: str) -> tuple[dict[str, int], dict[str, str]]:
    financials: dict[str, int] = {}
    evidence: dict[str, str] = {}
    for line in str(text).splitlines():
        clean = line.strip()
        for metric, pattern in METRICS.items():
            if metric not in financials and pattern.match(clean):
                raw = current_period_value(clean)
                value = parse_amount(raw) if raw else None
                if value is not None:
                    financials[metric] = value
                    evidence[metric] = clean
    return financials, evidence


def statement_scope(text: str, evidence: dict[str, str]) -> str | None:
    if not evidence:
        return None
    first_line = next(iter(evidence.values()))
    index = text.find(first_line)
    if index < 0:
        return None
    headings = list(re.finditer(r"(?:연결\s*)?(?:포괄\s*)?손익\s*계산서", text[:index]))
    if not headings:
        return None
    return "연결" if "연결" in headings[-1].group(0) else "개별"


def extract_business(text: str) -> str | None:
    patterns = [
        r"회사는\s*(.{1,100}?)(?:을|를)\s*영위할\s*목적으로",
        r"회사는\s*(.{1,100}?)(?:을|를)\s*목적으로\s*설립",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" .")
    return None


def next_id(prefix: str, used: set[str]) -> str:
    index = 1
    while f"{prefix}-{index:03d}" in used:
        index += 1
    value = f"{prefix}-{index:03d}"
    used.add(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="담당 기업별 감사보고서 재무정보 추출")
    parser.add_argument("--owner", choices=sorted(OWNER_PREFIX), help="특정 담당자 폴더만 갱신")
    args = parser.parse_args()

    targets = read_json(TARGETS_FILE)["targets"]
    by_id = {str(target["company_id"]): target for target in targets}
    owners = sorted({str(target["collector"]) for target in targets})
    if args.owner:
        owners = [args.owner]

    profiles: dict[str, dict[str, Any]] = {}
    for target in targets:
        path = RAW_COMPANIES / target["brand_name"] / "company_info.json"
        payload = read_json(path) if path.exists() else {}
        profiles[target["company_id"]] = payload.get("company_info", {})

    for owner in owners:
        prefix = OWNER_PREFIX.get(owner, owner[:2].upper())
        docs_file = DOCS / owner / "documents.jsonl"
        documents = read_jsonl(docs_file)
        existing = read_jsonl(DOCS / owner / "company_info.jsonl")
        targets_for_owner = [t for t in targets if t["collector"] == owner]
        brand_by_id = {t["company_id"]: t for t in targets_for_owner}

        generated: list[dict[str, Any]] = []
        generated_doc_ids: set[str] = set()
        for doc in documents:
            company_id = next((cid for cid in doc.get("company_ids", []) if cid in brand_by_id), None)
            target = brand_by_id.get(company_id or "")
            if not target:
                continue
            title = str(doc.get("title") or "")
            year_match = re.search(r"(?:감사보고서|사업보고서)\s*\((\d{4})\.12\)", title)
            if not year_match:
                continue
            year = int(year_match.group(1))
            text = str(doc.get("clean_text") or doc.get("full_text") or "")
            values, evidence = extract_financials(text)
            if not values:
                continue
            revenue = values.get("revenue")
            operating = values.get("operating_profit")
            net = values.get("net_income")
            business = extract_business(text)
            summary = [f"{year} 회계연도 감사·사업보고서 재무 수치."]
            if revenue is not None:
                summary.append(f"매출액 {revenue:,}원")
            if operating is not None:
                summary.append(f"영업이익 {operating:,}원")
            if net is not None:
                summary.append(f"당기순이익 {net:,}원")
            generated.append({
                "company_id": company_id,
                "document_id": doc["document_id"],
                "domain": "company_info",
                "content": ((f"주요 사업 설명: {business}. " if business else "") + "; ".join(summary)),
                "evidence_text": "\n".join(evidence.values()) or None,
                "evidence_location": "감사·사업보고서 재무제표 손익계산서",
                "as_of_date": f"{year}-12-31",
                "verification_status": "확인 필요",
                "industry": None,
                "main_business": business,
                "revenue_krw": revenue,
                "operating_profit_krw": operating,
                "listing_status": None,
                "employee_count": None,
                "established_date": iso_date(profiles.get(company_id, {}).get("est_dt")),
                "fiscal_year": year,
                "period": "연간",
                "statement_scope": statement_scope(text, evidence),
            })
            generated_doc_ids.add(str(doc["document_id"]))

        generated.sort(key=lambda row: (row["company_id"], row["fiscal_year"], row["document_id"]))
        preserved = [row for row in existing if str(row.get("document_id")) not in generated_doc_ids]
        rows = list(preserved)
        used_ids = {str(row.get("record_id")) for row in rows if row.get("record_id")}
        for row in generated:
            row["record_id"] = next_id(f"COMPANY_INFO-{prefix}", used_ids)
            rows.append(row)

        existing_company_info_ids = {str(row.get("document_id")) for row in rows}
        for target in targets_for_owner:
            profile = profiles.get(target["company_id"], {})
            corp_code = str(target["corp_code"])
            doc_id = f"DOC-{prefix}-API-{corp_code}"
            if not profile or doc_id in existing_company_info_ids:
                continue
            rows.append({
                "record_id": next_id(f"COMPANY_INFO-{prefix}", used_ids),
                "company_id": target["company_id"],
                "document_id": doc_id,
                "domain": "company_info",
                "content": (
                    f"Open DART 기업개황: 법인명 {profile.get('corp_name')}; 대표자 {profile.get('ceo_nm')}; "
                    f"설립일 {iso_date(profile.get('est_dt'))}; 주소 {profile.get('adres')}; "
                    f"업종분류코드 {profile.get('induty_code')}; 결산월 {profile.get('acc_mt')}월."
                ),
                "evidence_text": None,
                "evidence_location": "Open DART 기업개황 응답의 corp_name, ceo_nm, est_dt, adres, induty_code, acc_mt",
                "as_of_date": None,
                "verification_status": "확인됨" if profile.get("status") == "000" else "확인 필요",
                "industry": None,
                "main_business": None,
                "revenue_krw": None,
                "operating_profit_krw": None,
                "listing_status": None,
                "employee_count": None,
                "established_date": iso_date(profile.get("est_dt")),
                "fiscal_year": None,
                "period": None,
                "statement_scope": None,
            })

        rows.sort(key=lambda row: (str(row.get("company_id", "")), str(row.get("as_of_date") or ""), str(row.get("record_id", ""))))
        output = DOCS / owner / "company_info.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f"{owner}: 기업정보 {len(rows)}건 저장: {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
