from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "filings"
COLLECTED = ROOT / "data" / "collected"
OWNER_PREFIX = {"suyeon": "SY", "anna": "AN", "seonghyeon": "SH"}
COMPANY_IDS = {
    "이니스프리": "COMPANY-INNISFREE",
    "에스쁘아": "COMPANY-ESPOIR",
    "아모레퍼시픽": "COMPANY-AMOREPACIFIC",
    "에뛰드": "COMPANY-ETUDE",
    "퍼시픽테크": "COMPANY-PACIFICTECH",
    "아모스프로페셔널": "COMPANY-AMOSPROFESSIONAL",
    "코스알엑스": "COMPANY-COSRX",
}


def normalize_text(value: str) -> str:
    value = value.replace("\u00a0", " ").replace("\r", "\n")
    value = re.sub(r"[\t ]+", " ", value)
    value = re.sub(r"\n\s*\n\s*\n+", "\n\n", value)
    return value.strip()


def extract_text(data: bytes) -> str:
    source = ""
    for encoding in ("utf-8", "euc-kr", "cp949"):
        try:
            source = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    soup = BeautifulSoup(source, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [normalize_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            table.replace_with(soup.new_string("\n" + "\n".join(rows) + "\n"))
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\[첨부 문서: [^\]]+\]\s*", "", text)
    text = re.sub(r"&cr\s*", "\n", text, flags=re.I)
    text = text.replace("◆click◆", "")
    return normalize_text(text)


def metadata_for(archive_path: Path) -> dict[str, Any]:
    sidecar = archive_path.with_suffix(".json")
    if sidecar.exists():
        return json.loads(sidecar.read_text(encoding="utf-8"))
    return {"rcept_no": archive_path.stem, "target_brand": archive_path.parent.name}


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
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


def main() -> None:
    archives = sorted(RAW.rglob("*.zip")) if RAW.exists() else []
    if not archives:
        raise SystemExit("원문 ZIP이 없습니다. 먼저 collect_dart.py --download-documents로 수집하세요.")
    records_by_owner: dict[str, dict[str, dict[str, Any]]] = {}
    for archive_path in archives:
        meta = metadata_for(archive_path)
        receipt = str(meta.get("rcept_no", archive_path.stem))
        owner = str(meta.get("collector", "suyeon")).strip() or "suyeon"
        prefix = OWNER_PREFIX.get(owner, owner[:2].upper())
        brand = str(meta.get("target_brand", archive_path.parent.name))
        company_id = COMPANY_IDS.get(brand)
        if not company_id:
            raise ValueError(f"shared/companies.jsonl에 없는 대상 기업: {brand}")
        text_parts = []
        with zipfile.ZipFile(archive_path) as archive:
            supported = [name for name in archive.namelist() if name.lower().endswith((".xml", ".html", ".htm"))]
            for source_file in supported:
                text = extract_text(archive.read(source_file))
                if text:
                    text_parts.append(text)
        clean_text = "\n\n".join(text_parts)
        record = {
            "document_id": f"DOC-{prefix}-DART-{receipt}",
            "source_type": "disclosure",
            "source_name": "Open DART 전자공시시스템",
            "title": meta.get("report_nm") or None,
            "original_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
            "published_at": iso_date(meta.get("rcept_dt")),
            "collected_at": meta.get("collected_at") or datetime.now(timezone.utc).isoformat(),
            "company_ids": [company_id],
            "raw_path": archive_path.relative_to(ROOT).as_posix(),
            "clean_text": clean_text or None,
            "processing_status": "정제 완료" if clean_text else "확인 필요",
        }
        records_by_owner.setdefault(owner, {})[record["document_id"]] = record

    for owner, records in records_by_owner.items():
        output = COLLECTED / owner / "documents.jsonl"
        existing = jsonl_rows(output)
        # Preserve manually collected public sources and Open DART company-profile API records.
        for row in existing:
            if row.get("source_type") != "disclosure":
                records[row["document_id"]] = row
        ordered = sorted(records.values(), key=lambda item: (item.get("published_at") or "", item["document_id"]))
        with output.open("w", encoding="utf-8") as handle:
            for record in ordered:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f"문서 {len(ordered)}건 저장: {output.relative_to(ROOT)}")
    print("문서 ID, 출처, 기업 ID, 원문 경로와 처리 상태를 CONNECT 스키마로 기록했습니다.")


if __name__ == "__main__":
    main()
