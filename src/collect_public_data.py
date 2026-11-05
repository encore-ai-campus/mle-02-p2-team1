from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
API = "https://apis.data.go.kr/1160100/service/GetCorpBasicInfoService_V2"
TARGETS_FILE = ROOT / "config" / "targets.json"

load_dotenv(ROOT / ".env")


def api_key() -> str:
    value = os.getenv("DATA_GO_KR_API_KEY", "").strip().strip('"')
    if not value:
        raise SystemExit("DATA_GO_KR_API_KEY가 비어 있습니다. .env에 공공데이터포털 일반 인증키를 설정하세요.")
    return value


def get_profile(name: str, key: str) -> dict[str, Any]:
    try:
        response = requests.get(
            f"{API}/getCorpOutline_V2",
            params={
                "ServiceKey": key,
                "resultType": "json",
                "pageNo": "1",
                "numOfRows": "100",
                "corpNm": name,
            },
            timeout=45,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        # Avoid printing the request URL because the API key is a query parameter.
        raise RuntimeError(exc.__class__.__name__) from None
    except ValueError:
        raise SystemExit("금융위 기업개요 API가 JSON이 아닌 응답을 반환했습니다.") from None


def items_from(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = payload.get("response", {}).get("body", {})
    items = body.get("items", {}).get("item", [])
    return [items] if isinstance(items, dict) else list(items or [])


def load_targets() -> list[dict[str, str]]:
    config = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    return [
        {
            "slug": str(target["company_id"]).removeprefix("COMPANY-").lower(),
            "name": str(target["brand_name"]),
            "fss_corp_code": str(target["corp_code"]),
        }
        for target in config["targets"]
    ]


def normalized_corp_code(value: Any) -> str:
    return str(value or "").strip().zfill(8)


def collect() -> None:
    key = api_key()
    raw_dir = ROOT / "data" / "raw" / "public_data"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for target in load_targets():
        slug = target["slug"]
        config_target = next(t for t in json.loads(TARGETS_FILE.read_text(encoding="utf-8"))["targets"] if t["brand_name"] == target["name"])
        queries = list(dict.fromkeys([target["name"], config_target.get("legal_name", ""), *config_target.get("aliases", [])]))
        candidates: list[dict[str, Any]] = []
        matched_payload: dict[str, Any] | None = None
        matched_count = 0
        for query in (q for q in queries if q):
            try:
                payload = get_profile(query, key)
            except RuntimeError as exc:
                candidates.append({"query": query, "error": str(exc)})
                continue
            items = items_from(payload)
            candidates.extend({"query": query, "item": item} for item in items)
            matches = [item for item in items if normalized_corp_code(item.get("fssCorpUnqNo")) == normalized_corp_code(target["fss_corp_code"])]
            if matches:
                matched_payload = payload
                matched_count = len(matches)
                break

        if matched_payload is not None:
            raw_path = raw_dir / f"fsc_corp_outline_{slug}.json"
            matched_payload["_matched_query"] = query
            raw_path.write_text(json.dumps(matched_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{target['name']}: 검색 후보 {len(items_from(matched_payload))}건, 지정 법인 일치 {matched_count}건 → {raw_path.relative_to(ROOT)}")
        else:
            raw_path = raw_dir / f"fsc_corp_candidates_{slug}.json"
            raw_path.write_text(json.dumps({"target": target, "queries": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{target['name']}: 지정 DART 고유번호와 일치하는 금융위 결과 없음; 후보 원응답 저장 → {raw_path.relative_to(ROOT)}")


if __name__ == "__main__":
    collect()
