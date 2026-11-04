"""Open DART 기업 고유번호 목록에서 처음 10개를 조회합니다."""

import io
import os
from pathlib import Path
import sys
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[2]
URL = "https://opendart.fss.or.kr/api/corpCode.xml"
COLUMNS = (
    ("corp_code", "고유번호"),
    ("corp_name", "회사명"),
    ("corp_eng_name", "영문명"),
    ("stock_code", "종목코드"),
    ("modify_date", "최종변경일"),
)


def api_key():
    """환경 변수 또는 프로젝트 루트의 .env에서 인증키를 읽습니다."""
    key = os.environ.get("DART_API_KEY", "").strip()
    if key:
        return key
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and name.strip() == "DART_API_KEY":
                return value.strip().strip('"\'')
    raise ValueError("프로젝트 루트의 .env에 DART_API_KEY를 설정해 주세요.")


def fetch_companies(key):
    # 인증키가 포함된 요청 URL과 예외 내용은 출력하지 않습니다.
    request_url = URL + "?" + urlencode({"crtfc_key": key})
    try:
        with urlopen(request_url, timeout=60) as response:
            data = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Open DART 연결에 실패했습니다. 인터넷 연결을 확인해 주세요.") from None

    if not zipfile.is_zipfile(io.BytesIO(data)):
        try:
            error = ET.fromstring(data)
            status = error.findtext("status", default="알 수 없음")
            message = error.findtext("message", default="응답을 확인할 수 없습니다.")
        except ET.ParseError:
            raise RuntimeError("Open DART에서 예상과 다른 응답을 받았습니다.") from None
        raise RuntimeError(f"Open DART 오류 {status}: {message}")

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml_files = [name for name in archive.namelist() if name.lower().endswith('.xml')]
        if not xml_files:
            raise RuntimeError("Open DART 응답에 기업 목록 XML이 없습니다.")
        with archive.open(xml_files[0]) as xml_file:
            root = ET.parse(xml_file).getroot()
    return [{key: (item.findtext(key) or '').strip() for key, _ in COLUMNS}
            for item in root.findall('list')]


def display_width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in 'WF' else 1 for ch in text)


def show_table(companies):
    rows = [[company[key] or '-' for key, _ in COLUMNS] for company in companies[:10]]
    headers = [label for _, label in COLUMNS]
    widths = [max(display_width(row[i]) for row in [headers, *rows]) for i in range(len(headers))]

    def render(row):
        return ' | '.join(value + ' ' * (width - display_width(value))
                          for value, width in zip(row, widths))

    print(f"전체 {len(companies):,}개 기업 중 {len(rows)}개 표시 (API 제공 순서)")
    print(render(headers))
    print('-+-'.join('-' * width for width in widths))
    for row in rows:
        print(render(row))


def main():
    try:
        show_table(fetch_companies(api_key()))
    except (ValueError, RuntimeError, ET.ParseError, zipfile.BadZipFile) as exc:
        print(f"조회 실패: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
