"""快活CLUB 店舗データ収集スクリプト。

公式サイト(https://www.kaikatsu.jp/)が配信している以下のデータソースから、
店舗情報・設備・料金を収集し、docs/data/stores.json に出力する。

- /shop/data/shop.js          … 店舗マスタ（店舗名・住所・設備など）
- /public/{store_code}.json   … 店舗ごとの料金マスタ（座席タイプ別・曜日別・
                                 時間帯別の税込料金が数値で入っている）
- /shop/detail/{store_code}.html … 上記の料金JSONを持たない店舗向けの
                                 フォールバック。料金画像のURLを取得し、
                                 GEMINI_API_KEY が設定されていれば Gemini Vision API
                                 で構造化数値データへの変換を試みる
                                 (price_source="vision_ai")。キー未設定時や
                                 抽出失敗時は Tesseract OCR でのテキスト化のみを
                                 行う(price_source="image"、数値検索の対象外)。

実行頻度は手動(workflow_dispatch)のみを想定。サーバー負荷を抑えるため、
リクエスト間に SLEEP_SECONDS の間隔を空ける。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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
# 時間数 → 公式APIのナイトパックキー。公式は12時間パックを "12" ではなく "A" で持つ。
# AI画像読取(vision_ai)の結果もこの命名に揃え、データ内でキーの揺れを作らない。
# 対応が不明な時間数は str(hours) をキーにする（フロントは key ではなく hours で照合している）。
NIGHT_PACK_KEY_BY_HOURS = {8: "8", 12: "A"}


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
        # 全角数字など int() で直接変換できない表記のフォールバック
        digits = re.sub(r"[^\d]", "", str(value).translate(str.maketrans("０１２３４５６７８９", "0123456789")))
        return int(digits) if digits else None


def finalize_price_schema(
    categories: list[dict[str, Any]],
    night_pack_start_time: str | None = None,
    night_pack_end_time: str | None = None,
) -> dict[str, Any]:
    """座席カテゴリ別の料金リストから、検索・並び替え用の集計値を付与する。

    /public/{code}.json 由来・Gemini Vision由来のどちらの座席カテゴリリストでも
    共通して使う集計ロジック。
    """
    all_basic = [c["weekday_basic_taxfee"] for c in categories if c.get("weekday_basic_taxfee")]
    all_night_pack = [
        np["weekday_taxfee"] for c in categories for np in c["night_packs"] if np.get("weekday_taxfee")
    ]
    all_24h = [c["weekday_hourly_taxfee"].get("24") for c in categories if c["weekday_hourly_taxfee"].get("24")]
    available_night_pack_hours = sorted({
        np["hours"] for c in categories for np in c["night_packs"] if np.get("hours")
    })

    return {
        "categories": categories,
        "available_night_pack_hours": available_night_pack_hours,
        "night_pack_start_time": night_pack_start_time,
        "night_pack_end_time": night_pack_end_time,
        "min_basic_taxfee": min(all_basic) if all_basic else None,
        "min_night_pack_taxfee": min(all_night_pack) if all_night_pack else None,
        "min_24h_taxfee": min(all_24h) if all_24h else None,
    }


def parse_structured_price(entry: dict[str, Any]) -> dict[str, Any]:
    """/public/{code}.json の1エントリを座席カテゴリ別の料金表に変換する。

    ナイトパックは8時間("8"キー)と12時間("A"キー)の2種類が存在し、店舗によって
    片方のみ・両方・どちらも無し、と提供状況が異なる。"B"/"C"キーは実データ上
    使われていないが、将来の追加プランに備えてスキーマ上は残す。
    各バリエーションは時間数(hours)付きの個別エントリとして区別できるようにする。
    """
    night_pack_hours_by_key = {
        k: _num(entry.get(f"night_pack_{k}_time")) for k in NIGHT_PACK_KEYS
    }

    categories = []
    for cat_key, cat_label in SEAT_CATEGORIES.items():
        basic_weekday = _num(entry.get(f"{cat_key}_weekday_basic_taxfee"))
        basic_weekend = _num(entry.get(f"{cat_key}_weekend_basic_taxfee"))

        hourly_weekday = {h: _num(entry.get(f"{cat_key}_weekday_{h}h_taxfee")) for h in HOUR_KEYS}
        hourly_weekend = {h: _num(entry.get(f"{cat_key}_weekend_{h}h_taxfee")) for h in HOUR_KEYS}
        hourly_weekday = {h: v for h, v in hourly_weekday.items() if v is not None}
        hourly_weekend = {h: v for h, v in hourly_weekend.items() if v is not None}

        night_packs = []
        for k in NIGHT_PACK_KEYS:
            hours = night_pack_hours_by_key.get(k)
            weekday_fee = _num(entry.get(f"{cat_key}_weekday_night{k}_taxfee"))
            weekend_fee = _num(entry.get(f"{cat_key}_weekend_night{k}_taxfee"))
            if hours is None or (weekday_fee is None and weekend_fee is None):
                continue
            night_packs.append({
                "key": k,
                "hours": hours,
                "weekday_taxfee": weekday_fee,
                "weekend_taxfee": weekend_fee,
            })

        has_data = any([basic_weekday, basic_weekend, hourly_weekday, hourly_weekend, night_packs])
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
            "night_packs": night_packs,
        })

    return finalize_price_schema(
        categories,
        night_pack_start_time=entry.get("night_pack_start_time") or None,
        night_pack_end_time=entry.get("night_pack_end_time") or None,
    )


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


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"
# APIキーはURLのクエリ(?key=)ではなく x-goog-api-key ヘッダーで送る。クエリに入れると、
# requests の HTTPError メッセージ（"... for url: ...?key=..."）経由で警告ログにキーが出てしまう
# （公開リポジトリのActionsログは誰でも読める。Secretのマスクに頼らない）。
GEMINI_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
GEMINI_HOUR_KEYS = ["3", "6", "9", "12", "15", "18", "21", "24"]
GEMINI_RETRY_COUNT = 3
GEMINI_RETRY_SLEEP_SECONDS = 8

GEMINI_PRICE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "categories": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "category": {"type": "STRING", "enum": list(SEAT_CATEGORIES.keys())},
                    "weekday_basic_taxfee": {"type": "INTEGER"},
                    "weekend_basic_taxfee": {"type": "INTEGER"},
                    "weekday_basic_time": {"type": "INTEGER"},
                    "weekday_hourly_taxfee": {
                        "type": "OBJECT",
                        "properties": {h: {"type": "INTEGER"} for h in GEMINI_HOUR_KEYS},
                        "required": GEMINI_HOUR_KEYS,
                    },
                    "weekend_hourly_taxfee": {
                        "type": "OBJECT",
                        "properties": {h: {"type": "INTEGER"} for h in GEMINI_HOUR_KEYS},
                        "required": GEMINI_HOUR_KEYS,
                    },
                    "night_packs": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "hours": {"type": "INTEGER"},
                                "weekday_taxfee": {"type": "INTEGER"},
                                "weekend_taxfee": {"type": "INTEGER"},
                            },
                        },
                    },
                },
                "required": ["category", "weekday_hourly_taxfee", "weekend_hourly_taxfee"],
            },
        },
    },
    "required": ["categories"],
}

class GeminiExtractionError(Exception):
    pass


class GeminiQuotaExhausted(Exception):
    """無料枠の日次リクエスト数上限に達した。リトライしても無駄なため、
    呼び出し側（backfill_vision_prices）はこれを受けて即座に実行全体を停止する。"""
    pass


def _gemini_request(body: dict[str, Any]) -> dict[str, Any] | None:
    """Gemini APIにリクエストを送り、JSONテキストをパースして返す共通処理。

    429（クォータ超過）はリトライしない。1日のリクエスト数上限に達している場合、
    リトライは成功する見込みがなく、かえって貴重な残りクォータを消費するだけだから。
    """
    url = GEMINI_URL_TMPL.format(model=GEMINI_MODEL)
    headers = {"x-goog-api-key": GEMINI_API_KEY or ""}
    last_exc: Exception | None = None
    for attempt in range(GEMINI_RETRY_COUNT):
        try:
            res = requests.post(url, json=body, headers=headers, timeout=120)
            if res.status_code == 429:
                raise GeminiQuotaExhausted(res.text[:300])
            res.raise_for_status()
            data = res.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except GeminiQuotaExhausted:
            raise
        except (requests.RequestException, GeminiExtractionError, KeyError, ValueError, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt < GEMINI_RETRY_COUNT - 1:
                time.sleep(GEMINI_RETRY_SLEEP_SECONDS)
    print(f"  警告: Gemini抽出に失敗しました ({last_exc})", file=sys.stderr)
    return None


GEMINI_BATCH_PRICE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "results": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "image_index": {"type": "INTEGER"},
                    "categories": GEMINI_PRICE_SCHEMA["properties"]["categories"],
                },
                "required": ["image_index", "categories"],
            },
        },
    },
    "required": ["results"],
}

GEMINI_BATCH_PRICE_PROMPT = """これから複数枚の日本のネットカフェ「快活CLUB」の料金表画像を渡します。
各画像の直前に "=== image_index: N ===" というテキストが入っているので、その画像はN番として
結果の results 配列に1要素として出力してください（画像の枚数と同じ件数を出力すること。
1枚も結合・混同しないこと。各imageは完全に別の店舗の独立した料金表です）。

各画像ごとの抽出ルール（1枚の画像を解析する場合と同じ）:
1. 表には通常「3時間パック」から「24時間パック」まで3時間刻みで8段階（3,6,9,12,15,18,21,24）の料金が記載されています。見える場合は必ず8キー全部を埋めてください。
2. 数値が不鮮明・潰れていて確信が持てない場合は、絶対に0や推測値を入れてはいけません。そのキー自体を省略してください（0円という料金は実在しません）。
3. 平日(weekday)と休日/土日祝(weekend)の両方の料金を必ず出力してください。
   - 表に「平日」「休日」の2列が別々に記載されている場合は、それぞれの列の値をそのまま使ってください。
   - 表が平日料金のみで、「土日・祝日はパック料金にXXX円が加算されます」のような注記がある場合は、
     weekend = weekday + XXX円 を自分で計算して両方埋めてください。
   - 加算の注記がどこにも見当たらない場合は weekend は weekday と同額にしてください。
4. category は座席タイプの実態に合わせて以下にマッピング。表の列見出しの文言に
   正確に対応させ、異なる列見出しを同じcategoryに重複させないこと
   （例えば「ブース」列と「ダーツ・ビリヤード・カラオケ」列が別々に存在する場合、
   両方をbooth扱いにしてはいけない）:
   「オープンシート」「飲み放題カフェ」→ open
   「ブース」（単独の見出し。ダーツ等の言及が無いもの）→ booth
   「ダーツ・ビリヤード・カラオケ」「アミューズシート」など、ダーツ/ビリヤード/
   カラオケ等のアミューズメント利用が前面に出た見出し → amuse
   「個室」「鍵付完全個室」「完全個室」→ private
   1枚の画像内で同じcategory値を複数回出力してはいけない（列ごとに一意のcategoryを割り当てる）。
5. night_packs はナイトパック（「ナイトX時間パック」等）の時間数(hours)と平日/休日料金。複数ある場合は全て列挙してください。
6. 金額は全て税込の数値のみ（円マークやカンマは含めない）。読み取れない項目は省略して構いません。
7. 表の列見出しの数が2つ以上ある場合（例:「飲み放題カフェ」「ブース・ダーツ・カラオケ」「鍵付完全個室」の3列）、
   見える列は1つも省略せず、必ず全ての列をcategoriesに出力してください。
   セルが複数の時間帯行（例:3時間パックと6時間パックの行）にわたって縦に結合され、
   1つの料金しか表示されていない場合は、結合されている全ての時間帯キーに同じ料金値を設定してください
   （例: 3時間パックと6時間パックのセルが結合されて「990円」と1つだけ表示されている場合、
   weekday_hourly_taxfee の "3" と "6" の両方に 990 を設定する）。結合されているからといって
   その列・その時間帯を省略してはいけません。
8. 各行の左端に書かれている時間帯ラベル（3時間パック/6時間パック/9時間パック/12時間パック/
   15時間パック/18時間パック/21時間パック/24時間パック）を1行ずつ正確に確認し、そのラベルと
   完全に一致する時間キー（"3"/"6"/"9"/"12"/"15"/"18"/"21"/"24"）に値を設定してください。
   ある行が不鮮明で読み取れない場合でも、後続の行の値を前に詰めて別の時間キーに割り当てては
   いけません（ラベルと値がズレる原因になります）。読み取れない行はそのキーを省略するだけに
   してください。
"""


def extract_prices_with_genai_batch(images: list[bytes]) -> list[dict[str, Any] | None]:
    """複数枚の料金画像を1回のAPIリクエストにまとめて送信する（1日のリクエスト数枠を節約する）。

    日本のGemini無料枠はプロジェクトによって「1日のリクエスト数」が極端に少ない
    （実測で1日20回程度）場合があり、画像1枚=1リクエストでは61店舗を捌けない。
    1リクエストに複数画像を載せることでリクエスト数を 1/batch_size に圧縮する。

    戻り値は images と同じ長さのリストで、各要素はその画像に対応するGemini結果
    （抽出失敗時は None）。image_index を使って入力順とのズレを補正する。
    """
    if not GEMINI_API_KEY or not images:
        return [None] * len(images)

    import base64

    parts: list[dict[str, Any]] = [{"text": GEMINI_BATCH_PRICE_PROMPT}]
    for i, image_bytes in enumerate(images):
        parts.append({"text": f"=== image_index: {i} ==="})
        parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(image_bytes).decode()}})

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": GEMINI_BATCH_PRICE_SCHEMA,
            "temperature": 0,
        },
    }
    parsed = _gemini_request(body)
    output: list[dict[str, Any] | None] = [None] * len(images)
    if parsed is None:
        return output

    for item in parsed.get("results", []):
        idx = item.get("image_index")
        if isinstance(idx, int) and 0 <= idx < len(images):
            output[idx] = {"categories": item.get("categories", [])}
    return output


def _genai_num(value: Any) -> int | None:
    """Geminiの出力値を数値化する。0円という料金は実在しないため、モデルが読み取り
    不能時に紛れ込ませた0は不正値として弾き、欠損(None)として扱う。"""
    n = _num(value)
    return n if n and n > 0 else None


def genai_result_to_categories(genai_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Geminiが返したJSONを内部の座席カテゴリスキーマに変換する。"""
    categories = []
    for c in genai_result.get("categories", []):
        cat_key = c.get("category")
        if cat_key not in SEAT_CATEGORIES:
            continue
        weekday_hourly = {h: _genai_num(c.get("weekday_hourly_taxfee", {}).get(h)) for h in GEMINI_HOUR_KEYS}
        weekend_hourly = {h: _genai_num(c.get("weekend_hourly_taxfee", {}).get(h)) for h in GEMINI_HOUR_KEYS}
        weekday_hourly = {h: v for h, v in weekday_hourly.items() if v is not None}
        weekend_hourly = {h: v for h, v in weekend_hourly.items() if v is not None}

        night_packs = []
        for np in c.get("night_packs", []):
            hours = _genai_num(np.get("hours"))
            if hours is None:
                continue
            night_packs.append({
                "key": NIGHT_PACK_KEY_BY_HOURS.get(hours, str(hours)),
                "hours": hours,
                "weekday_taxfee": _genai_num(np.get("weekday_taxfee")),
                "weekend_taxfee": _genai_num(np.get("weekend_taxfee")),
            })

        categories.append({
            "category": cat_key,
            "label": SEAT_CATEGORIES[cat_key],
            "weekday_basic_taxfee": _genai_num(c.get("weekday_basic_taxfee")),
            "weekend_basic_taxfee": _genai_num(c.get("weekend_basic_taxfee")),
            "weekday_basic_time": _genai_num(c.get("weekday_basic_time")),
            "weekend_basic_time": _genai_num(c.get("weekday_basic_time")),
            "weekday_hourly_taxfee": weekday_hourly,
            "weekend_hourly_taxfee": weekend_hourly,
            "night_packs": night_packs,
        })
    return _dedupe_categories(categories)


def _category_richness(c: dict[str, Any]) -> int:
    """カテゴリが持つ実データの量を雑に数値化する（重複時にどちらを残すか判定するため）。"""
    return (
        len(c["weekday_hourly_taxfee"]) + len(c["weekend_hourly_taxfee"]) + len(c["night_packs"])
        + bool(c["weekday_basic_taxfee"]) + bool(c["weekend_basic_taxfee"])
    )


def _dedupe_categories(categories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同じcategory値が複数列として重複抽出された場合、データ量が多い方を残す。

    モデルが列見出しを誤って同じcategoryに分類してしまうことがあるための安全策。
    """
    best_by_category: dict[str, dict[str, Any]] = {}
    for c in categories:
        existing = best_by_category.get(c["category"])
        if existing is None or _category_richness(c) > _category_richness(existing):
            best_by_category[c["category"]] = c
    return list(best_by_category.values())


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
    price_source: str = "none"  # "json" | "vision_ai" | "image" | "none"
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
            "access": extract_access(r.get("address")),  # 最寄駅からの徒歩案内（カード表示用）
            "lat": None,  # 地図表示用。--geocode-backfill で住所からジオコーディングして埋める
            "lng": None,
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
                    # Gemini Vision APIによる数値化は別途 `--vision-backfill` で行う
                    # （無料枠の日次リクエスト数上限が低いプロジェクトでは、通常の
                    # スクレイピング中に毎回呼ぶと枠を使い切ってしまうため）。
                    ocr_text = ocr_price_image(img_res.content)
                    record.price_ocr_text = ocr_text
                    record.price_rows = parse_price_rows(ocr_text)
        except requests.RequestException as exc:
            print(f"  警告: {code} の取得に失敗しました ({exc})", file=sys.stderr)

        results.append(record.to_json())
        time.sleep(SLEEP_SECONDS)

    return results


def backfill_vision_prices(
    stores_path: Path,
    batch_size: int = 4,
    max_requests: int = 15,
    batch_sleep_seconds: float = 10.0,
    force_codes: set[str] | None = None,
) -> None:
    """既存の docs/data/stores.json のうち price_source=="image" の店舗だけを対象に、
    複数画像まとめてのGemini Vision抽出を行い、その都度ファイルへ保存する。

    無料枠の「1日あたりのリクエスト数」上限が低いプロジェクトでも、複数日に分けて
    本関数を再実行すれば取り残しなく徐々に置き換えられるよう、以下の設計にしている。
    - 既に price_source=="vision_ai"/"json" の店舗は対象にしない（再実行のたびに
      重複してAPIを消費しない）。force_codes に store_code を指定すると、
      vision_ai/json 済みでも強制的に再処理する（誤抽出の修正用）。
    - 1バッチ処理するたびにファイルへ保存する（quota切れで中断しても進捗が残る）
    - max_requests 件のバッチを送ったら自動的に終了する（1日の上限を超えないよう
      呼び出し側で日の上限より少し小さい値を指定する想定）
    """
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY が設定されていないため backfill を実行できません。", file=sys.stderr)
        return

    data: list[dict[str, Any]] = json.loads(stores_path.read_text(encoding="utf-8"))
    force_codes = force_codes or set()
    targets = [
        s for s in data
        if s.get("price_image_url") and (s.get("price_source") == "image" or s.get("store_code") in force_codes)
    ]
    print(f"対象店舗数: {len(targets)} 件 / バッチサイズ: {batch_size} / 最大リクエスト数: {max_requests}", file=sys.stderr)

    by_code = {s["store_code"]: s for s in data}
    request_count = 0

    for batch_start in range(0, len(targets), batch_size):
        if request_count >= max_requests:
            print(f"最大リクエスト数({max_requests})に達したため終了します。残り {len(targets) - batch_start} 件は次回実行で処理してください。", file=sys.stderr)
            break

        batch = targets[batch_start:batch_start + batch_size]
        print(f"バッチ {batch_start // batch_size + 1}: {[s['store_name'] for s in batch]}", file=sys.stderr)

        images = []
        for s in batch:
            try:
                res = requests.get(s["price_image_url"], headers=HEADERS, timeout=20)
                res.raise_for_status()
                images.append(res.content)
            except requests.RequestException as exc:
                print(f"  警告: {s['store_name']} の画像取得に失敗 ({exc})", file=sys.stderr)
                images.append(b"")
            time.sleep(SLEEP_SECONDS)

        valid_indices = [i for i, img in enumerate(images) if img]
        if not valid_indices:
            continue

        try:
            results = extract_prices_with_genai_batch([images[i] for i in valid_indices])
        except GeminiQuotaExhausted as exc:
            print(
                f"1日のリクエスト数上限に達したため終了します ({exc})。"
                f" 残り {len(targets) - batch_start} 件は翌日以降の再実行で処理してください。",
                file=sys.stderr,
            )
            break
        request_count += 1

        for local_i, genai_result in zip(valid_indices, results):
            store = by_code[batch[local_i]["store_code"]]
            if genai_result is None:
                continue
            categories = genai_result_to_categories(genai_result)
            if categories:
                store["price_source"] = "vision_ai"
                store["price"] = finalize_price_schema(categories)

        stores_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  保存しました（バッチ内成功: {sum(1 for r in results if r)}/{len(results)}）", file=sys.stderr)

        if batch_start + batch_size < len(targets) and request_count < max_requests:
            time.sleep(batch_sleep_seconds)

    remaining = sum(1 for s in data if s.get("price_source") == "image")
    vision_total = sum(1 for s in data if s.get("price_source") == "vision_ai")
    print(f"backfill完了: AI画像読取 合計{vision_total}件 / 画像のみ残り{remaining}件", file=sys.stderr)


# 国土地理院(GSI)ジオコーディングAPI。APIキー不要・無料で、日本の住所を番地レベルまで
# 高精度に解決できる（OSM Nominatimは日本の番地/丁目データが疎で市区中心に丸められがち）。
# 応答は GeoJSON 風の配列で coordinates は [経度, 緯度] の順。
GSI_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# 連絡先を明示するUser-Agent（両API共通で使用。Nominatimは特に規約で要求）。
GEOCODE_HEADERS = {
    "User-Agent": "kaikatu-scraper/1.0 (personal research use; https://github.com/)"
}
# GSIは明示的なレート上限を課していないが、相手サーバ負荷を避けるため間隔を空ける。
GEOCODE_SLEEP_SECONDS = 0.6


def clean_address_for_geocoding(address: str | None) -> str:
    """住所文字列からジオコーディング可能な番地部分だけを取り出し、正規化する。

    公式データの address は「番地<br>ビル名 階<br>※駅より徒歩N分」のように、番地の後ろに
    <br>区切りでビル名や最寄駅の案内が連結されていることがある。ビル名・駅案内をそのまま
    Nominatimに渡すとヒットしない（結果0件）ため、最初の<br>より前（番地部分）だけを使う。

    さらにNominatimは日本語の「丁目/番地/番/号」や全角数字を含む表記でヒット率が落ちるため、
    全角数字→半角、丁目/番地/番→ハイフン、号→除去、と正規化し、途中の空白以降（ビル名等の
    残り）を切り落とす。
    """
    if not address:
        return ""
    first = re.split(r"<br\s*/?>", address)[0].strip()
    first = first.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    first = (first.replace("丁目", "-").replace("−", "-").replace("－", "-")
                  .replace("番地", "-").replace("番", "-").replace("号", ""))
    # 全角/半角スペース以降（ビル名などが残っている場合）を切り落とす
    first = re.split(r"[ 　]", first)[0]
    first = re.sub(r"-+", "-", first).rstrip("-")
    return first.strip()


def chome_level_address(address: str) -> str:
    """番地レベルでヒットしなかった時のフォールバック用に、丁目レベルまで丸めた住所を返す。

    正規化済み住所（例「大阪府大阪市城東区蒲生4-22-4」）の最初の数値ブロックまで（「…蒲生4」）
    を残す。番地まで登録が無い地域でも丁目レベルなら座標が取れることがあるため。
    """
    if not address:
        return ""
    m = re.match(r"(.+?[区市町村].*?\d+)(?:-\d+)+$", address)
    return m.group(1) if m else ""


def extract_access(address: str | None) -> list[str]:
    """住所に含まれる「最寄駅から徒歩N分」の案内文を抽出する（カード表示用）。

    address の <br> 区切りセグメントのうち「徒歩」を含むものを対象にし、先頭の「※」や
    区切り記号を除いて返す。複数駅が併記されている店舗もあるためリストで返す。該当なしは空。
    """
    if not address:
        return []
    result = []
    for seg in re.split(r"<br\s*/?>", address):
        seg = seg.strip().lstrip("※＊*").strip()
        if "徒歩" in seg and seg:
            result.append(seg)
    return result


def _geocode_gsi(query: str) -> tuple[float, float] | None:
    """国土地理院APIで1クエリをジオコーディングする。coordinatesは[経度,緯度]。"""
    try:
        res = requests.get(GSI_URL, params={"q": query}, headers=GEOCODE_HEADERS, timeout=20)
        res.raise_for_status()
        data = res.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"  警告: GSIジオコーディング失敗 ({query}): {exc}", file=sys.stderr)
        return None
    if data:
        try:
            lon, lat = data[0]["geometry"]["coordinates"]
            return float(lat), float(lon)
        except (KeyError, ValueError, IndexError, TypeError):
            pass
    return None


def _geocode_nominatim(query: str) -> tuple[float, float] | None:
    """OSM Nominatimで1クエリをジオコーディングする（GSIが空振りした時のフォールバック）。"""
    try:
        res = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "countrycodes": "jp", "limit": 1},
            headers=GEOCODE_HEADERS,
            timeout=20,
        )
        res.raise_for_status()
        data = res.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"  警告: Nominatimジオコーディング失敗 ({query}): {exc}", file=sys.stderr)
        return None
    if data:
        try:
            return float(data[0]["lat"]), float(data[0]["lon"])
        except (KeyError, ValueError, IndexError):
            pass
    return None


def geocode_address(*queries: str | None) -> tuple[float, float] | None:
    """住所文字列を緯度・経度に変換する（無料・APIキー不要）。

    日本の住所は番地レベルまで高精度なGSI(国土地理院)を第一候補にし、GSIが空振りした場合のみ
    OSM Nominatimにフォールバックする。引数の候補クエリ（番地→丁目→市区町村の順を想定）を
    順に試し、最初にヒットしたものを返す。見つからなければ None。
    """
    for query in queries:
        if not query:
            continue
        coords = _geocode_gsi(query)
        time.sleep(GEOCODE_SLEEP_SECONDS)
        if coords is None:
            coords = _geocode_nominatim(query)
            time.sleep(GEOCODE_SLEEP_SECONDS)
        if coords is not None:
            return coords
    return None


def backfill_geocode(stores_path: Path, max_requests: int | None = None) -> None:
    """既存の docs/data/stores.json のうち緯度経度(lat/lng)が未設定の店舗だけを対象に、
    住所からジオコーディングして lat/lng を書き込む（地図表示用）。

    - 既に lat/lng を持つ店舗はスキップ（再実行時に無駄なリクエストを出さない）。
    - 1リクエストごとにレート制限(約1req/sec)を守り、バッチごとにファイルへ保存する
      （中断しても進捗が残る）。max_requests で1回の実行件数を制限できる。
    """
    data: list[dict[str, Any]] = json.loads(stores_path.read_text(encoding="utf-8"))

    # 駅徒歩案内(access)は住所から抽出できる純粋な処理なので、ネットワーク不要。
    # 全店舗ぶんこの場でまとめて埋める（ジオコーディング対象外の店舗も含めて）。
    for store in data:
        store["access"] = extract_access(store.get("address"))

    targets = [s for s in data if s.get("lat") is None or s.get("lng") is None]
    print(f"ジオコーディング対象: {len(targets)} 件", file=sys.stderr)

    done = 0
    for i, store in enumerate(targets, start=1):
        if max_requests is not None and done >= max_requests:
            print(f"最大リクエスト数({max_requests})に達したため終了します。残り {len(targets) - i + 1} 件は次回実行で処理してください。", file=sys.stderr)
            break

        address = clean_address_for_geocoding(store.get("address"))
        chome = chome_level_address(address)
        fallback = f"{store.get('pref', '')}{store.get('city', '')}".strip()
        print(f"[{i}/{len(targets)}] {store.get('store_name')} ({address or fallback}) ...", file=sys.stderr)

        coords = geocode_address(address, chome, fallback)
        if coords:
            store["lat"], store["lng"] = coords
        else:
            # 失敗を明示的にNoneで記録（次回再試行対象のまま）
            store["lat"] = store.get("lat")
            store["lng"] = store.get("lng")
            print(f"  見つかりませんでした: {store.get('store_name')}", file=sys.stderr)
        done += 1

        # 10件ごと、および最後にファイル保存
        if done % 10 == 0 or i == len(targets):
            stores_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  保存しました（{done}件処理）", file=sys.stderr)

    stores_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    geocoded = sum(1 for s in data if s.get("lat") is not None and s.get("lng") is not None)
    print(f"ジオコーディング完了: 座標あり {geocoded} 件 / 全 {len(data)} 件", file=sys.stderr)


def carry_over_backfills(data: list[dict[str, Any]], prev: list[dict[str, Any]]) -> None:
    """全件スクレイプの新データ(data)へ、前回データ(prev)のbackfill結果を引き継ぐ。

    - 緯度経度: 再スクレイプのたびにジオコーディングをやり直さずに済むように。
    - AI補完料金(vision_ai): 全件スクレイプは料金画像のみの店舗を price_source="image" で
      作り直すため、引き継がないとGeminiで数値化した結果が消えて料金検索の対象から外れる
      （2026-08-02のスクレイプで実際に61店舗が消えた）。ただし料金画像URL（ファイル名に
      日付を含む）が変わっていれば料金改定の可能性があるので引き継がず、再補完の対象に残す。
      新データ側で公式JSONが取れるようになった店舗は、より正確なのでそちらを優先する。
    """
    prev_by_code = {s.get("store_code"): s for s in prev}
    carried_vision = 0
    for s in data:
        old = prev_by_code.get(s.get("store_code"))
        if old is None:
            continue
        if old.get("lat") is not None and old.get("lng") is not None:
            s["lat"], s["lng"] = old["lat"], old["lng"]
        if (
            s.get("price_source") == "image"
            and old.get("price_source") == "vision_ai"
            and old.get("price")
            and s.get("price_image_url")
            and s.get("price_image_url") == old.get("price_image_url")
        ):
            s["price_source"] = "vision_ai"
            s["price"] = old["price"]
            carried_vision += 1
    print(f"AI補完料金を引き継ぎ: {carried_vision} 店舗", file=sys.stderr)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="快活CLUB 店舗データ収集")
    parser.add_argument("--limit", type=int, default=None, help="動作確認用に件数を絞る")
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH, help="出力先JSONパス")
    parser.add_argument(
        "--vision-backfill",
        action="store_true",
        help="新規スクレイピングは行わず、既存の --out のデータのうち画像のみの店舗を"
             "Gemini Vision APIで数値化するbackfillのみ実行する（無料枠の日次上限に"
             "合わせて複数回に分けて実行することを想定）",
    )
    parser.add_argument("--batch-size", type=int, default=4, help="vision-backfill時に1リクエストへまとめる画像枚数")
    parser.add_argument("--max-requests", type=int, default=None, help="1回の実行で送る最大リクエスト数（vision-backfillは未指定で15、geocode-backfillは未指定で無制限）")
    parser.add_argument(
        "--force-codes", type=str, default="",
        help="vision-backfill時にカンマ区切りで指定した店舗コードは、既にvision_ai/json"
             "済みでも強制的に再抽出する（誤抽出の修正用）",
    )
    parser.add_argument(
        "--geocode-backfill",
        action="store_true",
        help="新規スクレイピングは行わず、既存の --out のデータのうち緯度経度が未設定の"
             "店舗を住所からジオコーディング(OSM Nominatim)してlat/lngを埋める（地図表示用）",
    )
    args = parser.parse_args()

    if args.geocode_backfill:
        backfill_geocode(args.out, max_requests=args.max_requests)
        return

    if args.vision_backfill:
        force_codes = {c.strip() for c in args.force_codes.split(",") if c.strip()}
        vision_max_requests = args.max_requests if args.max_requests is not None else 15
        backfill_vision_prices(args.out, batch_size=args.batch_size, max_requests=vision_max_requests, force_codes=force_codes)
        return

    data = collect(limit=args.limit)

    # 既存出力があれば、過去のbackfill結果（座標・AI補完料金）を引き継ぐ。
    if args.out.exists():
        try:
            prev = json.loads(args.out.read_text(encoding="utf-8"))
            carry_over_backfills(data, prev)
        except (ValueError, OSError) as exc:
            print(f"警告: 既存データからの引き継ぎに失敗しました ({exc})", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 料金データの取得日時を別ファイルに記録する（フッターの「料金データ取得日」に表示）。
    # stores.json は配列のまま保ちたいので、メタ情報は meta.json に分ける。
    # backfill（AI補完・ジオコーディング）は料金の取得日を変えないため、ここ（全件スクレイプ）でのみ更新する。
    if args.limit is None:
        meta_path = args.out.parent / "meta.json"
        meta = {"scraped_at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")}
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    json_count = sum(1 for s in data if s["price_source"] == "json")
    vision_count = sum(1 for s in data if s["price_source"] == "vision_ai")
    image_count = sum(1 for s in data if s["price_source"] == "image")
    none_count = sum(1 for s in data if s["price_source"] == "none")
    print(
        f"出力完了: {args.out} ({len(data)} 件 / 公式API数値料金: {json_count} 件,"
        f" AI画像読取: {vision_count} 件, 画像のみ(OCR参考): {image_count} 件, 取得不可: {none_count} 件)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
