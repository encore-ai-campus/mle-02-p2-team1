from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
API = "https://opendart.fss.or.kr/api"
load_dotenv(ROOT / ".env")


def api_key() -> str:
    value = os.getenv("OPENDART_API_KEY", "").strip()
    if not value:
        raise SystemExit("OPENDART_API_KEY가 비어 있습니다. .env에 발급받은 키를 설정하세요.")
    return value


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", value).strip("_")
    return cleaned or "target"


def get_response(endpoint: str, params: dict[str, Any], *, timeout: int = 45) -> requests.Response:
    try:
        response = requests.get(f"{API}/{endpoint}", params=params, timeout=timeout)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        # Do not print request URLs: the authentication key is a query parameter.
        raise SystemExit(f"Open DART 요청 실패 ({endpoint}): {exc.__class__.__name__}") from None


def load_targets() -> list[dict[str, Any]]:
    return json.loads((ROOT / "config" / "targets.json").read_text(encoding="utf-8"))["targets"]


def discover_targets() -> None:
    key = api_key()
    response = get_response("corpCode.xml", {"crtfc_key": key})
    archive_path = ROOT / "data" / "raw" / "opendart_corp_codes.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(response.content)

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        if not xml_names:
            raise SystemExit("기업 고유번호 ZIP에서 XML 파일을 찾지 못했습니다.")
        root = ET.fromstring(archive.read(xml_names[0]))

    companies = []
    for item in root.findall(".//list"):
        companies.append({
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "corp_eng_name": (item.findtext("corp_eng_name") or "").strip(),
            "stock_code": (item.findtext("stock_code") or "").strip(),
            "modify_date": (item.findtext("modify_date") or "").strip(),
        })

    candidates = []
    for target in load_targets():
        aliases = {name.casefold().replace(" ", "") for name in target.get("aliases", [])}
        brand = target["brand_name"]
        for company in companies:
            names = [company["corp_name"], company["corp_eng_name"]]
            normalized = [name.casefold().replace(" ", "") for name in names if name]
            if any(name in aliases or any(alias and alias in name for alias in aliases) for name in normalized):
                candidates.append({"brand_name": brand, **company, "match_review": "수동 확인 필요"})

    output = ROOT / "data" / "raw" / "corporate_candidates.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["brand_name", "corp_code", "corp_name", "corp_eng_name", "stock_code", "modify_date", "match_review"]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(candidates)
    print(f"법인 후보 {len(candidates)}건을 저장했습니다: {output.relative_to(ROOT)}")
    print("후보를 자동 선택하지 않습니다. DART 기업개황에서 법인명과 공시 제출 여부를 확인하세요.")


def collect_filings(from_date: str, to_date: str, download_documents: bool) -> None:
    key = api_key()
    if not re.fullmatch(r"\d{8}", from_date) or not re.fullmatch(r"\d{8}", to_date):
        raise SystemExit("날짜는 YYYYMMDD 형식이어야 합니다.")
    targets = load_targets()
    for target in targets:
        corp_code = str(target.get("corp_code", "")).strip()
        if not corp_code:
            print(f"건너뜀: {target['brand_name']} — config/targets.json에서 법인 고유번호 확인 필요")
            continue
        company_response = get_response("company.json", {"crtfc_key": key, "corp_code": corp_code}).json()
        company_status = str(company_response.get("status", ""))
        if company_status != "000":
            raise SystemExit(
                f"{target['brand_name']} 기업개황 응답 확인 필요: "
                f"{company_status} / {company_response.get('message', '')}"
            )
        company_dir = ROOT / "data" / "raw" / "companies" / safe_name(target["brand_name"])
        company_dir.mkdir(parents=True, exist_ok=True)
        company_payload = {
            "target_brand": target["brand_name"],
            "collector": target.get("collector", "suyeon"),
            "requested_corp_code": corp_code,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "company_info": company_response,
        }
        (company_dir / "company_info.json").write_text(
            json.dumps(company_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        params = {
            "crtfc_key": key,
            "corp_code": corp_code,
            "bgn_de": from_date,
            "end_de": to_date,
            "page_no": 1,
            "page_count": 100,
        }
        first = get_response("list.json", params).json()
        status = str(first.get("status", ""))
        if status not in {"000", "013"}:
            raise SystemExit(f"{target['brand_name']} 공시 조회 응답 확인 필요: {status} / {first.get('message', '')}")
        total_pages = int(first.get("total_page", 1) or 1) if status == "000" else 0
        entries = list(first.get("list", []) or [])
        for page in range(2, total_pages + 1):
            params["page_no"] = page
            page_data = get_response("list.json", params).json()
            if page_data.get("status") != "000":
                raise SystemExit(f"{target['brand_name']} 공시 목록 {page}쪽 응답을 확인하세요.")
            entries.extend(page_data.get("list", []) or [])
            time.sleep(0.25)

        name = safe_name(target["brand_name"])
        filing_dir = ROOT / "data" / "raw" / "filings" / name
        filing_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "target_brand": target["brand_name"],
            "collector": target.get("collector", "suyeon"),
            "corp_code": corp_code,
            "corp_name": target.get("legal_name", ""),
            "from_date": from_date,
            "to_date": to_date,
            "response_status": status,
            "response_message": first.get("message", ""),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "count": len(entries),
            "filings": entries,
        }
        (filing_dir / f"filings_{from_date}_{to_date}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"{target['brand_name']}: 공시 목록 {len(entries)}건")
        print(f"기업개황 저장: data/raw/companies/{safe_name(target['brand_name'])}/company_info.json")
        if download_documents:
            for entry in entries:
                receipt = str(entry.get("rcept_no", "")).strip()
                if not receipt:
                    continue
                archive_file = filing_dir / f"{receipt}.zip"
                if archive_file.exists():
                    continue
                document = get_response("document.xml", {"crtfc_key": key, "rcept_no": receipt})
                if document.content.startswith(b"PK"):
                    archive_file.write_bytes(document.content)
                    meta = {
                        **entry,
                        "target_brand": target["brand_name"],
                        "collector": target.get("collector", "suyeon"),
                        "corp_code": corp_code,
                        "corp_name": company_response.get("corp_name", target.get("legal_name", "")),
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                    }
                    archive_file.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                else:
                    # The API can return a structured error body instead of a ZIP.
                    try:
                        api_error = document.json()
                    except ValueError:
                        try:
                            error_root = ET.fromstring(document.content)
                            api_error = {
                                child.tag: (child.text or "").strip()
                                for child in error_root
                                if child.tag in {"status", "message"}
                            }
                        except ET.ParseError:
                            api_error = {"message": "원문 ZIP이 아닌 응답"}
                    # Keep the response for audit; it contains no request URL or API key.
                    archive_file.with_suffix(".response.json").write_text(
                        json.dumps(
                            {
                                "rcept_no": receipt,
                                "target_brand": target["brand_name"],
                                "corp_code": corp_code,
                                "collected_at": datetime.now(timezone.utc).isoformat(),
                                "response": api_error,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    print(f"원문 ZIP 미수집 ({receipt}): {api_error.get('status', '')} {api_error.get('message', '')}")
                time.sleep(0.25)


def main() -> None:
    parser = argparse.ArgumentParser(description="이니스프리·에스쁘아 Open DART 자료 수집")
    parser.add_argument("--discover", action="store_true", help="법인 고유번호 후보 목록 확인")
    parser.add_argument("--from-date", help="공시 시작일 YYYYMMDD")
    parser.add_argument("--to-date", help="공시 종료일 YYYYMMDD")
    parser.add_argument("--download-documents", action="store_true", help="공시 원문 ZIP도 내려받기")
    args = parser.parse_args()
    if args.discover:
        discover_targets()
    elif args.from_date and args.to_date:
        collect_filings(args.from_date, args.to_date, args.download_documents)
    else:
        parser.error("--discover 또는 --from-date와 --to-date를 지정하세요.")


if __name__ == "__main__":
    main()
