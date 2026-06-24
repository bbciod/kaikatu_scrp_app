"""快活CLUB 店舗データ収集スクリプト。

公式サイト(https://www.kaikatsu.jp/)が配信している店舗マスタ用JSデータ
(/shop/data/shop.js)と各店舗詳細ページから、店舗情報・設備・料金画像・
料金画像のOCR結果を収集し、docs/data/stores.json に出力する。

実行頻度は手動(workflow_dispatch)のみを想定。サーバー負荷を抑えるため、
リクエスト間に SLEEP_SECONDS の間隔を空ける。
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from PIL import Image

try:
    import pytesseract
except ImportError:  # OCRライブラリが無い環境でもマスタ情報だけは収集できるようにする
    pytesseract = None

BASE = "https://www.kaikatsu.jp"
SHOP_JS_URL = f"{BASE}/shop/data/shop.js"
DETAIL_URL_TMPL = f"{BASE}/shop/detail/{{code}}.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; kaikatsu-scraper/1.0; personal research use)"}
SLEEP_SECONDS = 0.8
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "stores.json"

PRICE_LINE_RE = re.compile(r"(?P<label>[^\d\n]{1,20}?)\s*[:：]?\s*(?P<price>[0-9]{2,5})\s*円?")


def fetch_text(url: str) -> str:
    res = requests.get(url, headers=HEADERS, timeout=20)
    res.raise_for_status()
    return res.text


def parse_stores_js(js_text: str) -> dict[str, list[dict[str, Any]]]:
    match = re.search(r"var stores =\s*(\{.*\});", js_text, re.S)
    if not match:
        raise RuntimeError("shop.js から store データを抽出できませんでした")
    return json.loads(match.group(1))


def extract_price_image_url(detail_html: str) -> str | None:
    match = re.search(r'class="price-img"><img src="([^"]+)"', detail_html)
    if not match:
        return None
    src = match.group(1)
    # 詳細ページの相対パスは /shop/ 配下からの相対参照
    if src.startswith("../"):
        src = src[3:]
        return f"{BASE}/shop/{src}"
    if src.startswith("/"):
        return f"{BASE}{src}"
    return f"{BASE}/shop/detail/{src}"


def ocr_price_image(image_bytes: bytes) -> str:
    if pytesseract is None:
        return ""
    image = Image.open(BytesIO(image_bytes))
    try:
        return pytesseract.image_to_string(image, lang="jpn")
    except pytesseract.TesseractError:
        # 日本語学習データが無い環境向けのフォールバック
        return pytesseract.image_to_string(image)


def parse_price_rows(ocr_text: str) -> list[dict[str, str]]:
    rows = []
    for raw_line in ocr_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = PRICE_LINE_RE.search(line)
        if not match:
            continue
        label = match.group("label").strip(" 　-:：")
        price = match.group("price")
        if not label:
            continue
        rows.append({"label": label, "price_yen": price})
    return rows


@dataclass
class StoreRecord:
    pref: str
    raw: dict[str, Any]
    price_image_url: str | None = None
    price_ocr_text: str = ""
    price_rows: list[dict[str, str]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        r = self.raw
        return {
            "store_code": r.get("store_code"),
            "store_name": r.get("store_name"),
            "name_kana": r.get("name_kana"),
            "pref": self.pref,
            "city": r.get("cf_store_city"),
            "tel": r.get("tel"),
            "address": r.get("address"),
            "service": r.get("service", []),
            "roomtype": r.get("roomtype", []),
            "karaoke": r.get("karaoke", []),
            "darts": r.get("darts", []),
            "billiards": r.get("billiards", []),
            "detail_url": DETAIL_URL_TMPL.format(code=r.get("store_code")),
            "price_image_url": self.price_image_url,
            "price_ocr_text": self.price_ocr_text,
            "price_rows": self.price_rows,
        }


def collect(limit: int | None = None) -> list[dict[str, Any]]:
    print("店舗マスタ取得中...", file=sys.stderr)
    stores_by_pref = parse_stores_js(fetch_text(SHOP_JS_URL))

    records: list[StoreRecord] = []
    for pref, stores in stores_by_pref.items():
        for raw in stores:
            records.append(StoreRecord(pref=pref, raw=raw))

    if limit is not None:
        records = records[:limit]

    total = len(records)
    print(f"対象店舗数: {total}", file=sys.stderr)

    results = []
    for i, record in enumerate(records, start=1):
        code = record.raw.get("store_code")
        print(f"[{i}/{total}] {record.raw.get('store_name')} ({code}) 取得中...", file=sys.stderr)
        try:
            detail_html = fetch_text(DETAIL_URL_TMPL.format(code=code))
            record.price_image_url = extract_price_image_url(detail_html)
            if record.price_image_url:
                time.sleep(SLEEP_SECONDS)
                img_res = requests.get(record.price_image_url, headers=HEADERS, timeout=20)
                img_res.raise_for_status()
                ocr_text = ocr_price_image(img_res.content)
                record.price_ocr_text = ocr_text
                record.price_rows = parse_price_rows(ocr_text)
        except requests.RequestException as exc:
            print(f"  警告: {code} の取得に失敗しました ({exc})", file=sys.stderr)

        results.append(record.to_json())
        time.sleep(SLEEP_SECONDS)

    return results


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="快活CLUB 店舗データ収集")
    parser.add_argument("--limit", type=int, default=None, help="動作確認用に件数を絞る")
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH, help="出力先JSONパス")
    args = parser.parse_args()

    data = collect(limit=args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"出力完了: {args.out} ({len(data)} 件)", file=sys.stderr)


if __name__ == "__main__":
    main()
