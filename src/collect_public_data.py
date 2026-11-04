from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
API = "https://apis.data.go.kr/1160100/service/GetCorpBasicInfoService_V2"
TARGETS = {
    "innisfree": {"name": "이니스프리", "fss_corp_code": "00812353"},
    "espoir": {"name": "에스쁘아", "fss_corp_code": "01061150"},
}

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
        raise SystemExit(f"금융위 기업개요 API 요청 실패: {exc.__class__.__name__}") from None
    except ValueError:
        raise SystemExit("금융위 기업개요 API가 JSON이 아닌 응답을 반환했습니다.") from None


def items_from(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = payload.get("response", {}).get("body", {})
    items = body.get("items", {}).get("item", [])
    return [items] if isinstance(items, dict) else list(items or [])


def collect() -> None:
    key = api_key()
    raw_dir = ROOT / "data" / "raw" / "public_data"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for slug, target in TARGETS.items():
        payload = get_profile(target["name"], key)
        matches = [
            item for item in items_from(payload)
            if str(item.get("fssCorpUnqNo", "")).strip() == target["fss_corp_code"]
        ]
        if not matches:
            raise SystemExit(f"{target['name']} 검색 결과에서 지정 DART 고유번호를 확인하지 못했습니다.")

        raw_path = raw_dir / f"fsc_corp_outline_{slug}.json"
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"{target['name']}: 후보 {len(items_from(payload))}건, "
            f"지정 법인 일치 {len(matches)}건 → {raw_path.relative_to(ROOT)}"
        )


if __name__ == "__main__":
    collect()
