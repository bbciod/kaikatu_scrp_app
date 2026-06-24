# 快活CLUB 店舗比較（非公式・個人利用ツール）

快活CLUB公式サイトが公開している店舗情報を収集し、設備・サービス・料金画像を
店舗間で比較できる静的Webサイトです。完全無料の構成（GitHub Pages + GitHub Actions）
で構築・運用しています。

**非公式のツールです。** 快活CLUB／株式会社média kaikatsu groupとは無関係です。
正確な最新情報は必ず[公式サイト](https://www.kaikatsu.jp/)・各店舗にご確認ください。

## 構成

- `scraper/scrape.py` — 公式サイトの店舗マスタJS (`/shop/data/shop.js`) と各店舗詳細ページから
  店舗名・住所・設備・料金画像URLを収集。料金画像はOCR（Tesseract, 日本語）でテキスト化を試みる
  （画像のレイアウトにより精度は保証されません）。
- `.github/workflows/scrape.yml` — `workflow_dispatch`（手動実行）でスクレイパーを実行し、
  結果を `docs/data/stores.json` としてコミットするワークフロー。定期実行は行わない。
- `docs/` — GitHub Pagesで配信する静的フロントエンド（都道府県・キーワード・設備での絞り込み、
  複数店舗の設備比較表、料金画像の並列表示）。

## セットアップ

1. このリポジトリをGitHubに作成・push
2. **Settings → Pages** で Source を `Deploy from a branch`、Branch を `main` / `docs` に設定
3. データを更新したい時は **Actions → Scrape kaikatsu store data → Run workflow** を手動実行
   （`limit` を指定すると動作確認用に件数を絞れる）
4. 数分後、`docs/data/stores.json` が自動コミットされ、Pagesに反映される

ローカルで試す場合:

```bash
pip install -r scraper/requirements.txt
# OCRを使う場合はTesseract本体＋日本語データも別途インストールが必要
#   Windows: https://github.com/UB-Mannheim/tesseract/wiki
#   macOS:   brew install tesseract tesseract-lang
#   Linux:   apt install tesseract-ocr tesseract-ocr-jpn
python scraper/scrape.py --limit 5   # まず少数件で動作確認
python -m http.server -d docs 8080   # http://localhost:8080 で確認
```

## 注意事項・スクレイピング方針

- `robots.txt` を確認し、明示的に禁止されているパス（在庫確認ページ）は対象外にしている
- 各リクエスト間に約0.8秒の間隔を空け、サーバー負荷を抑えている
- 定期自動実行（cron）はせず、必要なときに手動実行する運用としている
- 料金画像自体は再配布せず、公式サイト上のURLへの参照（埋め込み表示）のみを行っている
- 料金のOCR結果は参考情報であり、誤読の可能性がある旨をサイト上に明記している
- 個人の学習・比較検討目的の利用を想定。商用利用や大規模再配布は想定していない
