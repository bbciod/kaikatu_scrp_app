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
- `.github/workflows/scrape.yml` — `workflow_dispatch`（手動実行）で通常のスクレイピングを行う
  ワークフロー（Gemini呼び出しは行わない）。定期実行は行わない。
- `.github/workflows/vision_backfill.yml` — `workflow_dispatch`（手動実行）で上記の
  `--vision-backfill` を実行するワークフロー。無料枠の日次上限に応じて`batch_size`/`max_requests`
  を調整しながら、必要なら複数日に分けて手動実行する想定。
- `docs/` — GitHub Pagesで配信する静的フロントエンド（都道府県・キーワード・設備での絞り込み、
  複数店舗の設備比較表、料金画像の並列表示）。

## 使い方（サイトの機能）

1. **絞り込み** — 上部の「都道府県」セレクトと「キーワード」入力で店舗を絞り込めます。
   「ナイトパック予算（円以下）」に金額を入れると、ナイトパック料金がその金額以下の
   店舗のみに絞り込めます（数値料金が取得できている437店舗が対象）。
   さらに下の設備チップ（鍵付完全個室、ダーツ、ビリヤード等）をクリックすると、
   その設備を持つ店舗だけが一覧に残ります（複数選択でAND条件）。
2. **並び替え** — 「並び替え」セレクトで、ナイトパック料金が安い順／高い順に並べ替えられます。
3. **店舗比較** — 一覧表の「比較」列のチェックボックスで複数店舗を選択すると、
   ページ下部に設備の有無を○/−で並べた比較表と、各店舗の座席タイプ別の数値料金表
   （または料金画像＋OCR参考テキスト）がカードで並んで表示されます。
   「クリア」ボタンで比較選択をリセットできます。
4. **公式リンク** — 各行の「公式」リンクから、その店舗の公式詳細ページに飛べます。
   最新情報や正式な料金は必ずそちらでご確認ください。

注意: 数値料金（437店舗）は公式サイトの料金APIから取得した値です。残り61店舗のうち
Gemini Vision APIで抽出できた店舗（`price_source: "vision_ai"`）は数値検索の対象に
含めていますが、画像からのAI読み取りのため誤りを含む可能性があります。抽出に失敗した
店舗は画像＋OCR参考テキストのみの表示とし、料金検索・並び替えの対象には含めていません。
最終確認は必ず公式サイト・各店舗で行ってください。

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
6. 数分後、`docs/data/stores.json` が自動コミットされ、Pagesに反映される

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
- 個人の学習・比較検討目的の利用を想定。商用利用や大規模再配布は想定していない
