from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SUYEON = ROOT / "data" / "collected" / "suyeon"
PROCESSED = ROOT / "data" / "processed" / "suyeon"
COMPANIES = ROOT / "data" / "shared" / "companies.jsonl"
FACT_FILES = {
    "company_info.jsonl": "company_info",
    "social_issues.jsonl": "social_issue",
    "politics.jsonl": "politics",
    "market.jsonl": "market",
    "strategies.jsonl": "strategy",
    "owners.jsonl": "owner",
}
REQUIRED_FACT_FIELDS = {
    "record_id",
    "company_id",
    "document_id",
    "domain",
    "content",
    "evidence_text",
    "evidence_location",
    "as_of_date",
    "verification_status",
}
VALID_VERIFICATION = {"확인 필요", "확인됨", "상충"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"필수 파일이 없습니다: {path.relative_to(ROOT)}")
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path.relative_to(ROOT)}:{line_number} JSON 오류: {exc.msg}"
            ) from None
        if not isinstance(row, dict):
            raise ValueError(f"{path.relative_to(ROOT)}:{line_number} 객체가 아닙니다.")
        result.append(row)
    return result


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


def split_spans(text: str, max_chars: int, overlap_chars: int):
    """Yield overlapping half-open character ranges into the unchanged source text."""
    start = 0
    size = len(text)
    while start < size:
        target = min(start + max_chars, size)
        end = target
        if target < size:
            floor = start + max(1, max_chars // 2)
            paragraph_break = text.rfind("\n", floor, target)
            whitespace_break = text.rfind(" ", floor, target)
            candidate = max(paragraph_break, whitespace_break)
            if candidate > start:
                end = candidate
        if end <= start:
            end = target
        yield start, end
        if end >= size:
            break
        start = max(start + 1, end - overlap_chars)


def check_and_prepare(max_chars: int, overlap_chars: int) -> dict[str, Any]:
    companies = read_jsonl(COMPANIES)
    allowed_company_ids = {row.get("company_id") for row in companies}
    documents = read_jsonl(SUYEON / "documents.jsonl")
    docs_by_id = {row.get("document_id"): row for row in documents}
    issues: list[str] = []
    duplicate_docs = len(docs_by_id) != len(documents)
    if duplicate_docs:
        issues.append("documents.jsonl에 중복 document_id가 있습니다.")
    if not documents:
        issues.append("수연 documents.jsonl이 비어 있습니다.")

    chunks: list[dict[str, Any]] = []
    per_document: Counter[str] = Counter()
    invalid_chunk_spans = 0
    for document in documents:
        document_id = document.get("document_id")
        text = document.get("clean_text")
        if not isinstance(document_id, str) or not document_id:
            issues.append("document_id가 비어 있거나 문자열이 아닙니다.")
            continue
        if not isinstance(text, str) or not text.strip():
            issues.append(f"{document_id}: clean_text가 비어 있습니다.")
            continue
        doc_company_ids = document.get("company_ids") or []
        unknown = set(doc_company_ids) - allowed_company_ids
        if unknown:
            issues.append(f"{document_id}: 공통 목록에 없는 company_id가 있습니다.")
        digest = sha256(document_id.encode("utf-8")).hexdigest()[:10]
        spans = list(split_spans(text, max_chars, overlap_chars))
        if (
            not spans
            or spans[0][0] != 0
            or spans[-1][1] != len(text)
            or any(left[1] < right[0] for left, right in zip(spans, spans[1:]))
        ):
            invalid_chunk_spans += 1
            issues.append(f"{document_id}: 청크 위치가 원문을 연속적으로 덮지 않습니다.")
        for index, (start, end) in enumerate(spans, 1):
            chunk_text = text[start:end]
            chunks.append(
                {
                    "chunk_id": f"CHUNK-SY-{digest}-{index:04d}",
                    "document_id": document_id,
                    "company_ids": doc_company_ids,
                    "chunk_index": index,
                    "start_char": start,
                    "end_char": end,
                    "char_count": end - start,
                    "chunk_text": chunk_text,
                    "source_name": document.get("source_name"),
                    "source_type": document.get("source_type"),
                    "title": document.get("title"),
                    "original_url": document.get("original_url"),
                    "published_at": document.get("published_at"),
                }
            )
            per_document[document_id] += 1

    fact_counts: Counter[str] = Counter()
    domain_errors = 0
    missing_fields = 0
    duplicate_fact_ids = 0
    dangling_document_ids = 0
    dangling_company_ids = 0
    fact_document_company_mismatches = 0
    empty_contents = 0
    invalid_statuses = 0
    missing_evidence = 0
    evidence_matches = 0
    evidence_unmatched = 0
    seen_record_ids: set[str] = set()

    for filename, expected_domain in FACT_FILES.items():
        rows = read_jsonl(SUYEON / filename)
        fact_counts[filename] = len(rows)
        for row in rows:
            record_id = row.get("record_id")
            if record_id in seen_record_ids:
                duplicate_fact_ids += 1
            if record_id:
                seen_record_ids.add(record_id)
            if not REQUIRED_FACT_FIELDS.issubset(row):
                missing_fields += 1
            if row.get("domain") != expected_domain:
                domain_errors += 1
            if row.get("document_id") not in docs_by_id:
                dangling_document_ids += 1
            if row.get("company_id") not in allowed_company_ids:
                dangling_company_ids += 1
            elif row.get("document_id") in docs_by_id and row.get("company_id") not in (
                docs_by_id[row["document_id"]].get("company_ids") or []
            ):
                fact_document_company_mismatches += 1
            if not isinstance(row.get("content"), str) or not row["content"].strip():
                empty_contents += 1
            if row.get("verification_status") not in VALID_VERIFICATION:
                invalid_statuses += 1
            evidence = row.get("evidence_text")
            document = docs_by_id.get(row.get("document_id"))
            source_text = document.get("clean_text") if document else None
            if not isinstance(evidence, str) or not evidence.strip():
                missing_evidence += 1
            if isinstance(evidence, str) and evidence.strip() and isinstance(source_text, str):
                if normalized_text(evidence) in normalized_text(source_text):
                    evidence_matches += 1
                else:
                    evidence_unmatched += 1

    chunks_path = PROCESSED / "document_chunks.jsonl"
    PROCESSED.mkdir(parents=True, exist_ok=True)
    with chunks_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in chunks:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    result = {
        "company_ids_in_scope": sorted({cid for doc in documents for cid in (doc.get("company_ids") or [])}),
        "documents": len(documents),
        "chunks": len(chunks),
        "chunk_max_chars": max((row["char_count"] for row in chunks), default=0),
        "chunk_min_chars": min((row["char_count"] for row in chunks), default=0),
        "chunk_max_chars_setting": max_chars,
        "chunk_overlap_chars_setting": overlap_chars,
        "chunk_span_errors": invalid_chunk_spans,
        "facts": sum(fact_counts.values()),
        "fact_counts": dict(fact_counts),
        "fact_validation": {
            "missing_required_fields": missing_fields,
            "duplicate_record_ids": duplicate_fact_ids,
            "wrong_domain_values": domain_errors,
            "missing_documents": dangling_document_ids,
            "unknown_companies": dangling_company_ids,
            "fact_company_not_listed_on_source_document": fact_document_company_mismatches,
            "empty_content": empty_contents,
            "invalid_verification_status": invalid_statuses,
            "missing_evidence_text": missing_evidence,
            "evidence_found_in_document_text": evidence_matches,
            "evidence_not_found_in_document_text": evidence_unmatched,
        },
        "document_validation_issues": issues,
        "chunk_file": chunks_path.relative_to(ROOT).as_posix(),
    }

    report = [
        "# 수연 문서 청킹·추출 입력 검증",
        "",
        "이 보고서는 기존 정제 문서를 청크로 나누고, 이미 수집된 사실 레코드의 ID·출처 연결을 점검한 결과입니다. 외부 LLM 호출이나 새 사실 생성은 수행하지 않았습니다.",
        "",
        "## 청킹 결과",
        "",
        f"- 대상 문서: {result['documents']:,}건",
        f"- 생성 청크: {result['chunks']:,}건",
        f"- 청크 길이: {result['chunk_min_chars']:,}~{result['chunk_max_chars']:,}자 (설정 상한 {max_chars:,}자)",
        f"- 겹침 길이: {overlap_chars:,}자",
        "- 각 청크에 원본 `document_id`, 문자 위치(시작 포함·끝 제외), 출처 제목·URL을 보존했습니다.",
        f"- 원문 범위 누락·단절: {invalid_chunk_spans}건",
        "",
        "## 기존 조사 레코드 검증",
        "",
        f"- 사실 레코드: {result['facts']:,}건",
        f"- 필수 필드 누락: {missing_fields}",
        f"- 중복 record_id: {duplicate_fact_ids}",
        f"- 파일별 domain 오류: {domain_errors}",
        f"- 문서·회사 참조 누락: {dangling_document_ids + dangling_company_ids}",
        f"- 사실 회사와 출처 문서의 회사 연결 불일치: {fact_document_company_mismatches}",
        f"- 확인 상태 오류: {invalid_statuses}",
        f"- evidence_text 누락: {missing_evidence}",
        f"- evidence_text가 연결 문서 본문에 그대로 포함됨(공백 정규화): {evidence_matches}",
        f"- 그대로 포함되지 않음: {evidence_unmatched} (문구가 요약·표 변환·별도 출처일 수 있어 실제 근거 대조가 필요)",
        "",
        "## 다음 단계",
        "",
        "LLM 추출은 사용할 모델·인증정보가 정해진 뒤에 실행합니다. 이번 단계에서는 이미 수집된 수연 사실을 재생성하지 않았습니다.",
        "",
    ]
    (PROCESSED / "PREPARATION_REPORT.md").write_text("\n".join(report), encoding="utf-8")
    (PROCESSED / "preparation_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="수연 자료의 문서 청크와 근거 연결 점검 결과를 준비합니다."
    )
    parser.add_argument("--max-chars", type=int, default=2000)
    parser.add_argument("--overlap-chars", type=int, default=200)
    args = parser.parse_args()
    if args.max_chars < 200 or args.overlap_chars < 0 or args.overlap_chars >= args.max_chars:
        parser.error("--max-chars는 200 이상, --overlap-chars는 0 이상 max-chars 미만이어야 합니다.")
    try:
        result = check_and_prepare(args.max_chars, args.overlap_chars)
    except (FileNotFoundError, ValueError) as exc:
        parser.exit(2, f"오류: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
