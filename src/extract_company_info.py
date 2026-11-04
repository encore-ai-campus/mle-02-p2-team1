from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "data" / "collected"
RAW_COMPANIES = ROOT / "data" / "raw" / "companies"
TARGETS = ROOT / "config" / "targets.json"
COMPANY_IDS = {"이니스프리": "COMPANY-INNISFREE", "에스쁘아": "COMPANY-ESPOIR"}
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


def main() -> None:
    targets = read_json(TARGETS)["targets"]
    by_brand = {target["brand_name"]: target for target in targets}
    profiles: dict[str, dict[str, Any]] = {}
    for brand in by_brand:
        path = RAW_COMPANIES / brand / "company_info.json"
        payload = read_json(path) if path.exists() else {}
        profiles[brand] = payload.get("company_info", {})

    rows: list[dict[str, Any]] = []
    for owner_dir in DOCS.iterdir() if DOCS.exists() else []:
        docs_file = owner_dir / "documents.jsonl"
        if not docs_file.exists():
            continue
        owner = owner_dir.name
        prefix = OWNER_PREFIX.get(owner, owner[:2].upper())
        for doc in read_jsonl(docs_file):
            title = str(doc.get("title") or "")
            year_match = re.search(r"감사보고서\s*\((\d{4})\.12\)", title)
            brand = next((name for name in by_brand if name in doc.get("company_ids", []) or name == doc.get("brand_name")), None)
            if not year_match:
                # Support post-schema company IDs when brand_name is intentionally absent.
                brand = next((name for name, cid in COMPANY_IDS.items() if cid in doc.get("company_ids", [])), brand)
                if not re.search(r"감사보고서\s*\((\d{4})\.12\)", title):
                    continue
            if brand not in by_brand:
                brand = next((name for name, cid in COMPANY_IDS.items() if cid in doc.get("company_ids", [])), None)
            if brand not in by_brand:
                continue
            year = int(year_match.group(1))
            text = str(doc.get("clean_text") or doc.get("full_text") or "")
            values, evidence = extract_financials(text)
            if not values:
                continue
            revenue = values.get("revenue")
            operating = values.get("operating_profit")
            net = values.get("net_income")
            profile = profiles.get(brand, {})
            business = extract_business(text)
            business_content = f"주요 사업 설명: {business}. " if business else ""
            summaries = [f"{year} 회계연도 감사보고서의 연간 재무 수치."]
            if revenue is not None: summaries.append(f"매출액 {revenue:,}원")
            if operating is not None: summaries.append(f"영업이익 {operating:,}원")
            if net is not None: summaries.append(f"당기순이익 {net:,}원")
            excerpt = "\n".join(evidence.values()) or None
            record = {
                "record_id": f"COMPANY_INFO-{prefix}-{len(rows) + 1:03d}",
                "company_id": COMPANY_IDS[brand],
                "document_id": doc["document_id"],
                "domain": "company_info",
                "content": business_content + "; ".join(summaries),
                "evidence_text": excerpt,
                "evidence_location": "감사보고서 재무제표 손익계산서",
                "as_of_date": f"{year}-12-31",
                "verification_status": "확인됨" if revenue is not None and operating is not None else "확인 필요",
                "industry": "화장품" if business and "화장품" in business else None,
                "main_business": business,
                "revenue_krw": revenue,
                "operating_profit_krw": operating,
                "listing_status": None,
                "employee_count": None,
                "established_date": iso_date(profile.get("est_dt")),
                "fiscal_year": year,
                "period": "연간",
                "statement_scope": "개별",
            }
            rows.append(record)

    # Keep year-level rows deterministic, then add one profile record per company/API response.
    rows.sort(key=lambda r: (r["company_id"], r["fiscal_year"], r["document_id"]))
    for index, row in enumerate(rows, 1):
        row["record_id"] = f"COMPANY_INFO-SY-{index:03d}"
    now = datetime.now(timezone.utc).isoformat()
    for brand in by_brand:
        profile = profiles.get(brand, {})
        cid = COMPANY_IDS.get(brand)
        api_doc_id = f"DOC-SY-API-{profile.get('corp_code', '')}"
        content = (
            f"Open DART 기업개황: 법인명 {profile.get('corp_name')}; 대표자 {profile.get('ceo_nm')}; "
            f"설립일 {iso_date(profile.get('est_dt'))}; 주소 {profile.get('adres')}; "
            f"업종분류코드 {profile.get('induty_code')}; 결산월 {profile.get('acc_mt')}월."
        )
        rows.append({
            "record_id": f"COMPANY_INFO-SY-{len(rows) + 1:03d}",
            "company_id": cid,
            "document_id": api_doc_id,
            "domain": "company_info",
            "content": content,
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
    for index, row in enumerate(rows, 1):
        row["record_id"] = f"COMPANY_INFO-SY-{index:03d}"
    output = DOCS / "suyeon" / "company_info.jsonl"
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"CONNECT 스키마 기업정보 {len(rows)}건 저장: {output.relative_to(ROOT)}")
    print("연도별 수치와 원 단위는 원문에 연결되어 있습니다. 확인되지 않은 값은 null로 유지했습니다.")


if __name__ == "__main__":
    main()
