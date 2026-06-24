"""快活CLUB 店舗データ収集スクリプト。

公式サイト(https://www.kaikatsu.jp/)が配信している以下のデータソースから、
店舗情報・設備・料金を収集し、docs/data/stores.json に出力する。

- /shop/data/shop.js          … 店舗マスタ（店舗名・住所・設備など）
- /public/{store_code}.json   … 店舗ごとの料金マスタ（座席タイプ別・曜日別・
                                 時間帯別の税込料金が数値で入っている）
- /shop/detail/{store_code}.html … 上記の料金JSONを持たない店舗向けの
                                 フォールバック。料金画像のURLを取得し、
                                 Tesseract OCR でテキスト化を試みる。

実行頻度は手動(workflow_dispatch)のみを想定。サーバー負荷を抑えるため、
リクエスト間に SLEEP_SECONDS の間隔を空ける。
"""
from __future__ import annotations

import json
import os
import re
import shutil
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

    # Windows ではデフォルトインストール先がPATHに入らないことが多いため明示的に探す
    if not shutil.which("tesseract"):
        for candidate in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if Path(candidate).exists():
                pytesseract.pytesseract.tesseract_cmd = candidate
                break
except ImportError:  # OCRライブラリが無い環境でもマスタ情報だけは収集できるようにする
    pytesseract = None

BASE = "https://www.kaikatsu.jp"
SHOP_JS_URL = f"{BASE}/shop/data/shop.js"
DETAIL_URL_TMPL = f"{BASE}/shop/detail/{{code}}.html"
PRICE_JSON_URL_TMPL = f"{BASE}/public/{{code}}.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; kaikatsu-scraper/1.0; personal research use)"}
SLEEP_SECONDS = 0.8
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "stores.json"

PRICE_LINE_RE = re.compile(r"(?P<label>[^\d\n]{1,20}?)\s*[:：]?\s*(?P<price>[0-9]{2,5})\s*円?")

# 料金JSONに登場する座席カテゴリと、画面表示用の日本語ラベル
SEAT_CATEGORIES = {
    "open": "オープンシート",
    "booth": "ブース",
    "amuse": "アミューズシート",
    "private": "個室",
}
HOUR_KEYS = [str(h) for h in range(1, 25)]
NIGHT_PACK_KEYS = ["8", "A", "B", "C"]


def fetch_text(url: str) -> str:
    res = requests.get(url, headers=HEADERS, timeout=20)
    res.raise_for_status()
    return res.text


def parse_stores_js(js_text: str) -> dict[str, list[dict[str, Any]]]:
    match = re.search(r"var stores =\s*(\{.*\});", js_text, re.S)
    if not match:
        raise RuntimeError("shop.js から store データを抽出できませんでした")
    return json.loads(match.group(1))


def fetch_price_json(code: str) -> dict[str, Any] | None:
    """/public/{code}.json から料金マスタを取得する。

    料金画像のみの店舗ではレスポンスが空配列になるため None を返す。
    """
    url = PRICE_JSON_URL_TMPL.format(code=code)
    res = requests.get(url, headers=HEADERS, timeout=20)
    if res.status_code != 200:
        return None
    try:
        data = res.json()
    except ValueError:
        return None
    if not data:
        return None
    # 複数期間が入っている場合は先頭（基本料金）を採用する
    return data[0]


def _num(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_structured_price(entry: dict[str, Any]) -> dict[str, Any]:
    """/public/{code}.json の1エントリを座席カテゴリ別の料金表に変換する。"""
    categories = []
    for cat_key, cat_label in SEAT_CATEGORIES.items():
        basic_weekday = _num(entry.get(f"{cat_key}_weekday_basic_taxfee"))
        basic_weekend = _num(entry.get(f"{cat_key}_weekend_basic_taxfee"))

        hourly_weekday = {h: _num(entry.get(f"{cat_key}_weekday_{h}h_taxfee")) for h in HOUR_KEYS}
        hourly_weekend = {h: _num(entry.get(f"{cat_key}_weekend_{h}h_taxfee")) for h in HOUR_KEYS}
        hourly_weekday = {h: v for h, v in hourly_weekday.items() if v is not None}
        hourly_weekend = {h: v for h, v in hourly_weekend.items() if v is not None}

        night_pack_weekday = {
            k: _num(entry.get(f"{cat_key}_weekday_night{k}_taxfee")) for k in NIGHT_PACK_KEYS
        }
        night_pack_weekend = {
            k: _num(entry.get(f"{cat_key}_weekend_night{k}_taxfee")) for k in NIGHT_PACK_KEYS
        }
        night_pack_weekday = {k: v for k, v in night_pack_weekday.items() if v is not None}
        night_pack_weekend = {k: v for k, v in night_pack_weekend.items() if v is not None}

        has_data = any([
            basic_weekday, basic_weekend, hourly_weekday, hourly_weekend,
            night_pack_weekday, night_pack_weekend,
        ])
        if not has_data:
            continue

        categories.append({
            "category": cat_key,
            "label": cat_label,
            "weekday_basic_taxfee": basic_weekday,
            "weekend_basic_taxfee": basic_weekend,
            "weekday_basic_time": _num(entry.get("weekday_basic_time")),
            "weekend_basic_time": _num(entry.get("weekend_basic_time")),
            "weekday_hourly_taxfee": hourly_weekday,
            "weekend_hourly_taxfee": hourly_weekend,
            "weekday_night_pack_taxfee": night_pack_weekday,
            "weekend_night_pack_taxfee": night_pack_weekend,
        })

    all_basic = [c["weekday_basic_taxfee"] for c in categories if c["weekday_basic_taxfee"]]
    all_night_pack = [v for c in categories for v in c["weekday_night_pack_taxfee"].values()]
    all_24h = [c["weekday_hourly_taxfee"].get("24") for c in categories if c["weekday_hourly_taxfee"].get("24")]

    return {
        "categories": categories,
        "night_pack_hours": _num(entry.get("night_pack_8_time")),
        "night_pack_start_time": entry.get("night_pack_start_time") or None,
        "night_pack_end_time": entry.get("night_pack_end_time") or None,
        "min_basic_taxfee": min(all_basic) if all_basic else None,
        "min_night_pack_taxfee": min(all_night_pack) if all_night_pack else None,
        "min_24h_taxfee": min(all_24h) if all_24h else None,
    }


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
    """料金画像をOCRでテキスト化する（参考情報。数値検索には使用しない）。

    装飾フォント・2カラムレイアウトのためOCR精度は高くなく、数字が誤認識される
    ことが多い。3倍に拡大してからOCRすることで多少改善するが、過信しないこと。
    """
    if pytesseract is None:
        return ""
    image = Image.open(BytesIO(image_bytes)).convert("L")
    image = image.resize((image.width * 3, image.height * 3))
    try:
        return pytesseract.image_to_string(image, lang="jpn+eng", config="--psm 6")
    except pytesseract.TesseractError:
        # 日本語学習データが無い環境向けのフォールバック
        return pytesseract.image_to_string(image, config="--psm 6")


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
    price_source: str = "none"  # "json" | "image" | "none"
    price: dict[str, Any] | None = None
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
            "price_source": self.price_source,
            "price": self.price,
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
            price_entry = fetch_price_json(code)
            time.sleep(SLEEP_SECONDS)
            if price_entry is not None:
                record.price_source = "json"
                record.price = parse_structured_price(price_entry)
            else:
                detail_html = fetch_text(DETAIL_URL_TMPL.format(code=code))
                record.price_image_url = extract_price_image_url(detail_html)
                if record.price_image_url:
                    record.price_source = "image"
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

    json_count = sum(1 for s in data if s["price_source"] == "json")
    image_count = sum(1 for s in data if s["price_source"] == "image")
    none_count = sum(1 for s in data if s["price_source"] == "none")
    print(
        f"出力完了: {args.out} ({len(data)} 件 / 数値料金: {json_count} 件,"
        f" 画像のみ: {image_count} 件, 取得不可: {none_count} 件)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
