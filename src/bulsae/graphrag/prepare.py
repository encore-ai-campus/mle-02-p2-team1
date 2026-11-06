"""Prepare traceable news chunks locally; no model or database calls are made."""

import argparse
import hashlib
import json
from pathlib import Path


def chunks(content: str, size: int, overlap: int):
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("size must be positive and 0 <= overlap < size")
    start = 0
    while start < len(content):
        end = min(start + size, len(content))
        if end < len(content):
            boundary = content.rfind("\n", start + size // 2, end)
            if boundary > start + overlap:
                end = boundary + 1
        yield start, end, content[start:end]
        if end == len(content):
            break
        start = end - overlap


def prepare(input_path: Path, output_path: Path, size: int, overlap: int):
    if input_path.resolve() == output_path.resolve():
        raise ValueError("input and output must be different files")
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("size must be positive and 0 <= overlap < size")
    seen = set()
    documents = count = 0
    # Exclusive creation protects existing files and makes accidental reruns visible.
    with input_path.open(encoding="utf-8") as source, output_path.open("x", encoding="utf-8") as out:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            doc_id, content = row["document_id"], row["content"]
            if not isinstance(doc_id, str) or not doc_id or doc_id in seen:
                raise ValueError(f"invalid or duplicate document_id at line {line_number}")
            if not isinstance(content, str):
                raise ValueError(f"invalid content at line {line_number}")
            seen.add(doc_id)
            documents += 1
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            for start, end, text in chunks(content, size, overlap):
                chunk_id = hashlib.sha256(f"{doc_id}\0{digest}\0{start}\0{end}".encode()).hexdigest()
                chunk = {"chunk_id": chunk_id, "document_id": doc_id,
                         "title": row.get("title"), "original_url": row.get("original_url"),
                         "published_at": row.get("published_at"), "content_sha256": digest,
                         "start_char": start, "end_char": end, "text": text}
                out.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                count += 1
    return documents, count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, help="New local output file; do not commit article text")
    parser.add_argument("--size", type=int, default=1200)
    parser.add_argument("--overlap", type=int, default=150)
    args = parser.parse_args()
    documents, count = prepare(args.input, args.output, args.size, args.overlap)
    print(f"documents={documents} chunks={count} output={args.output}")


if __name__ == "__main__":
    main()
