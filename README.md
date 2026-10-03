# 快活CLUB 店舗比較（非公式・個人利用ツール）

快活CLUB公式サイトが公開している店舗情報を収集し、設備・サービス・料金画像を
店舗間で比較できる静的Webサイトです。完全無料の構成（GitHub Pages + GitHub Actions）
で構築・運用しています。

**非公式のツールです。** 快活CLUB／株式会社média kaikatsu groupとは無関係です。
正確な最新情報は必ず[公式サイト](https://www.kaikatsu.jp/)・各店舗にご確認ください。

## 構成

- `scraper/scrape.py` — 公式サイトの以下のデータソースから店舗名・住所・設備・料金を収集する。
  - `/shop/data/shop.js` … 店舗マスタ（店舗名・住所・設備など）
  - `/public/{店舗コード}.json` … 座席タイプ別・平日/休日別・時間帯別の**数値の**料金マスタ
    （498店舗中437店舗で取得可能。これを使って料金検索・並び替えができる）
  - 上記JSONが存在しない61店舗のみ、`/shop/detail/{店舗コード}.html` から料金画像URLを取得し、
    Tesseract OCR（日本語）でテキスト化する（`price_source: "image"`）。装飾フォントのため
    数字の誤読が多く、**このOCR結果は参考表示のみで、料金検索・並び替えの対象には含めない**。
- `scraper/scrape.py --vision-backfill` — 画像のみの店舗（`price_source: "image"`）を対象に、
  Gemini Vision API（無料枠）で座席タイプ別・平日/休日別・時間帯別の数値料金へ変換する
  （`price_source: "vision_ai"`、料金検索・並び替えの対象に含める）。公式サイト調査の結果、
  これら61店舗には数値料金データそのものが存在しないことを確認済み（画像のみで提供する古い
  テンプレートの店舗ページ）。画像から読み取れない・不鮮明な値は0円などの推測値で埋めず必ず
  欠損として省略する。
  **無料枠は「1日あたりのリクエスト数」がプロジェクトによって極端に少ない場合があり（実測で
  1日20回程度のケースを確認）、61店舗を1回では処理しきれないことがある。** そのため
  `--batch-size`（デフォルト4）枚の画像を1リクエストにまとめて送ることでリクエスト数を圧縮し、
  さらに `--max-requests`（デフォルト15）に達したら安全に中断して `docs/data/stores.json` を
  保存する設計にしている。既に `vision_ai` 化済みの店舗は次回実行時にスキップされるため、
  日をまたいで何度か実行すれば未処理分から順に処理が進む。
- `.github/workflows/scrape.yml` — `workflow_dispatch`（手動実行）で全件スクレイピングを行う
  ワークフロー。定期実行は行わない。前回データの座標・AI補完料金は引き継ぎ（料金画像URLが
  変わった店舗のAI補完は引き継がず再処理対象にする）、続けて**新店のジオコーディング**と
  **画像のみの店舗のAI補完**を自動実行して、新店や料金画像の差し替えで生じた穴を埋める。
  AI補完は `GEMINI_API_KEY` のSecretが登録されている場合のみ動き、未登録ならスキップする。
- `.github/workflows/vision_backfill.yml` — `workflow_dispatch`（手動実行）で上記の
  `--vision-backfill` を実行するワークフロー。無料枠の日次上限に応じて`batch_size`/`max_requests`
  を調整しながら、必要なら複数日に分けて手動実行する想定。
- `scraper/scrape.py --geocode-backfill` — 地図表示用に、各店舗の住所から緯度経度(lat/lng)を
  ジオコーディングして `docs/data/stores.json` に書き込む。**APIキー不要・無料の国土地理院(GSI)
  ジオコーディングAPI**を第一候補に使用する（日本の住所を番地レベルまで高精度に解決できる）。
  GSIが空振りした場合のみOSM Nominatimにフォールバックする。相手サーバ負荷を避けるため
  リクエスト間隔を空けている。既に座標を持つ店舗はスキップするため再実行しても無駄なリクエストを
  出さず、通常スクレイプ後も既存座標を引き継ぐ（毎回やり直さない）。
- `.github/workflows/geocode_backfill.yml` — `workflow_dispatch`（手動実行）で上記の
  `--geocode-backfill` を実行するワークフロー。GSI/NominatimともキーレスなのでSecret登録は不要。
- `docs/` — GitHub Pagesで配信する静的フロントエンド（都道府県・キーワード・設備での絞り込み、
  複数店舗の設備比較表、地図表示）。地図は **Leaflet + OpenStreetMap**（APIキー不要・完全無料）で
  実装し、ライブラリ本体は `docs/vendor/leaflet/` に同梱している（地図タイルはOSMから配信）。

## 使い方（サイトの機能）

データは「店舗×座席タイプ×利用プラン」を1レコードに展開したロング形式で保持し、
比較値（平日価格）を軸に検索・ランキングする設計です。

1. **表示モード切替** — 最上部の「カード表示／一覧表表示／地図表示」で切り替えます。
   カード表示は順位バッジ付きでスマホ向け、一覧表表示はPCで全件確認・店舗比較したい場合向け、
   地図表示は位置関係を見ながら探したい場合向けです。地図では条件に合う店舗をピンで示し、
   ピンには最安値、クリックで開くポップアップには選択中の各プランの料金（例: ナイト8h・12hを
   両方選んでいれば両方）を表示します。座標が未取得の店舗はピンが表示されません。
2. **検索条件パネル** — 「予算（平日価格・円以下）」「キーワード」を最前面に、
   「都道府県」「座席タイプ」「利用時間・プラン」を複数選択チップで絞り込めます。
   各グループ先頭の「すべて」は他の個別選択と排他で、個別を選ぶと自動的に外れ、
   全て外すと「すべて」に戻ります（＝その軸はフィルタしない）。
   「設備・サービス」は補足の絞り込み（AND条件、複数選択可）です。
3. **条件チップ** — 現在有効な絞り込み条件が常時チップ表示され、×で個別に解除できます。
4. **サマリー** — 絞り込み後の最安値・件数・平均が一目で分かります。
5. **一覧表（店舗比較表）** — 一覧表モードでは、選択操作なしで条件に合う店舗がそのまま
   座席タイプ別プラン価格＋設備の有無を1つの表にまとめた比較表として表示されます。
   選択中の条件（プラン・設備）は列の先頭にハイライト表示されます。列見出しは折り返し表示にし、
   スマホでの横方向の間延びを抑えています。

注意: 比較値として表示しているのは平日価格です。休日（土日・祝日）は店舗ごとに
加算額が異なるため、各行に「休日 +¥◯◯◯」として参考表示しています。
数値料金（437店舗）は公式サイトの料金APIから取得した値です。残り61店舗は
Gemini Vision APIで画像から抽出した値（`price_source: "vision_ai"`、AIバッジ表示）で、
誤りを含む可能性があります。最終確認は必ず公式サイト・各店舗で行ってください。

## セットアップ

1. このリポジトリをGitHubに作成・push
2. **Settings → Pages** で Source を `Deploy from a branch`、Branch を `main` / `docs` に設定
3. （任意）料金画像のみの店舗をAIで数値化したい場合: [Google AI Studio](https://aistudio.google.com/apikey)
   で無料のAPIキーを取得し、リポジトリの **Settings → Secrets and variables → Actions** で
   `GEMINI_API_KEY` という名前のSecretとして登録する（未設定でも動作する。その場合は
   OCR参考表示のみになる）
4. データを更新したい時は **Actions → Scrape kaikatsu store data → Run workflow** を手動実行
   （`limit` を指定すると動作確認用に件数を絞れる）
5. （任意）画像のみの店舗をAI数値化したい場合: **Actions → Backfill prices with Gemini Vision
   (image-only stores) → Run workflow** を手動実行。無料枠の日次上限に達した場合は途中で
   安全に止まるので、翌日以降に同じワークフローを再実行すれば残りが処理される
6. （任意）地図表示用に店舗の緯度経度を埋めたい場合: **Actions → Backfill lat/lng with OSM
   Nominatim (map view) → Run workflow** を手動実行（APIキー不要）。または後述のローカル手順でも可
7. 数分後、`docs/data/stores.json` が自動コミットされ、Pagesに反映される

ローカルで試す場合:

```bash
pip install -r scraper/requirements.txt
# OCRを使う場合はTesseract本体＋日本語データも別途インストールが必要
#   Windows: https://github.com/UB-Mannheim/tesseract/wiki
#   macOS:   brew install tesseract tesseract-lang
#   Linux:   apt install tesseract-ocr tesseract-ocr-jpn
python scraper/scrape.py --limit 5   # まず少数件で動作確認

# Gemini Vision APIで画像のみの店舗を数値化する場合（任意）
export GEMINI_API_KEY=取得したキー   # Windows PowerShellなら $env:GEMINI_API_KEY="..."
python scraper/scrape.py --vision-backfill --batch-size 4 --max-requests 15
# 無料枠の日次上限に達したら自動で安全に停止する。翌日以降に同じコマンドを再実行すれば続きから処理される。

# 地図表示用に住所から緯度経度を埋める（APIキー不要・国土地理院APIを使用、全件で約5分）
python scraper/scrape.py --geocode-backfill              # 全件（未取得のみ処理）
# python scraper/scrape.py --geocode-backfill --max-requests 50  # 件数を絞って試す場合

python -m http.server 8080 -d docs   # http://localhost:8080 で確認
```

`docs/index.html` を `file://` で直接ブラウザやプレビューパネルで開くと、
ブラウザのセキュリティ制限で `fetch("data/stores.json")` が失敗し画面が真っ白になります。
必ず上記のように簡易HTTPサーバー経由（`http://localhost:8080`）で開いてください。
（Claude Codeのプレビューパネルを使う場合は `.claude/launch.json` に登録済みのサーバー設定を利用できます）

## 注意事項・スクレイピング方針

- `robots.txt` を確認し、明示的に禁止されているパス（在庫確認ページ）は対象外にしている
- 各リクエスト間に約0.8秒の間隔を空け、サーバー負荷を抑えている
- 定期自動実行（cron）はせず、必要なときに手動実行する運用としている
- 料金画像自体は再配布せず、公式サイト上のURLへの参照（埋め込み表示）のみを行っている
- 料金のOCR結果は参考情報であり、誤読の可能性がある旨をサイト上に明記している
- 地図表示のジオコーディングは国土地理院API（フォールバックでOSM Nominatim）を使い、相手サーバ
  負荷を避けるためリクエスト間隔を空け、取得済み座標はキャッシュして再取得しない。
  地図タイルはOpenStreetMapの帰属表示を地図上に明記している
- 個人の学習・比較検討目的の利用を想定。商用利用や大規模再配布は想定していない
