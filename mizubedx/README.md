# 水辺リスク観測 Web入力システム

Googleフォーム「水辺リスク観測（条件分岐版）」の項目・選択肢・スコア仕様を
そのまま反映した、Flask + SQLite の代替入力システムです。
気象庁・Open-Meteoの公式API連携、および任意でGemini APIによる要約強化に対応しています。

## 構成

```
water_risk_app/
├── app.py               バックエンド（Flask）
├── external_data.py     気象庁・Open-Meteo・Gemini連携モジュール
├── schema.sql            SQLiteテーブル定義
├── requirements.txt
├── templates/
│   └── index.html         入力フォーム（観測エリアで条件分岐＋気象警報バー）
└── static/
    └── uploads/           アップロード写真の保存先
```

## 起動方法

### 本番運用（推奨・複数人の同時アクセスに対応）

Flaskの開発用サーバー（`app.run()`）はシングルスレッドかつデバッグ用途のため、
複数のスタッフが同時にフォームを送信する現場運用には適していません。
そのため、`python app.py` で起動すると自動的に **waitress（本番向けWSGIサーバー）** で
立ち上がるようにしています。

```bash
cd water_risk_app
pip install -r requirements.txt
python app.py
```

```
Waitress WSGIサーバーを起動します: http://0.0.0.0:5000 (threads=8)
```
と表示されれば起動完了です。ブラウザで `http://localhost:5000` を開くとフォームが表示されます。
初回起動時に `water_risk.db` が自動生成されます。

同時アクセス数に応じてスレッド数を調整できます（既定8）。

```bash
WAITRESS_THREADS=16 PORT=8080 python app.py
```

`waitress-serve` コマンドから直接起動することもできます（`app.py`をimportするだけで
DBが初期化されるため、こちらでも問題なく動作します）。

```bash
waitress-serve --host=0.0.0.0 --port=5000 --threads=8 app:app
```

### 開発・デバッグ用（Flask開発サーバー）

コードの動作確認やデバッグ時、自動リロードが欲しい場合は、環境変数で
Flask開発サーバーに切り替えられます（本番では使用しないでください）。

```bash
FLASK_APP=app.py FLASK_DEBUG=1 flask run --host=0.0.0.0 --port=5000
```

## 外部データ連携について【重要】

本システムが使用する外部データソースは、すべて **スクレイピングを一切行わない**
公式・公開API/JSONのみです。

### ① 気象庁（自動取得・公式・無認証）
- URL: `https://www.jma.go.jp/bosai/warning/data/warning/130000.json`
- 気象庁が自身のサイト構築のために公開している構造化JSONデータを直接取得します
  （HTMLページの解析ではありません）。
- 世田谷区の地域コード `1311200` でフィルタし、現在発令中の警報・注意報を抽出します。
- 環境変数 `JMA_AREA_CODE_PREF` / `JMA_AREA_CODE_CITY` で対象地域を変更可能です。

### ② 河川データ（自動取得・公式・無料・無認証）
国交省「川の防災情報」サイトの利用規約には
「ツール等による定期的なデータ収集はサーバ負担のためお控えください」と明記されており、
このサイトへの自動アクセス（スクレイピング含む）は一切行いません。

代わりに **Open-Meteo Flood API**（GloFAS: Global Flood Awareness Systemによる
河川流量シミュレーションの公式REST/JSON API。認証不要・商用利用も無料）を使用します。

- URL: `https://flood-api.open-meteo.com/v1/flood?latitude=..&longitude=..&daily=river_discharge`
- 戻り値は **河川流量シミュレーション値（m³/s）** であり、国交省・二子橋観測所が実測する
  **「水位（m）」とは異なる指標**です。DB上も別カラム（`river_discharge_m3s`）で保持し、
  実測水位（`river_level_m`）と混同しないようにしています。

**実測水位（m）がどうしても必要な場合**は、以下のいずれかを推奨します。

| 方法 | 内容 |
|---|---|
| a) 正規契約 | 国交省の有料サービス「水防災オープンデータ提供サービス」に契約し、発行されたAPIエンドポイントを環境変数 `RIVER_LEVEL_API_URL`（+`RIVER_LEVEL_API_KEY`）に設定 |
| b) 手動入力（デフォルト） | スタッフが公式サイト「川の防災情報」を目視確認し、`/admin/river_level` にPOSTして入力（`river_level_manual_entry`テーブルに保存） |

`app.py` は a) が設定されていればそれを優先し、無ければ自動的に b) にフォールバックします。

### ③ Gemini API（任意・要約強化）
環境変数 `GEMINI_API_KEY` を設定すると、上記①②の公式データを踏まえた
一言サマリーの強化文（`ai_summary`列）を自動生成します。未設定時は何もしません
（既存の動作に影響しません）。

## 主要な環境変数

| 変数名 | 既定値 | 説明 |
|---|---|---|
| `JMA_AREA_CODE_PREF` | `130000` | 気象庁：都道府県コード（東京都） |
| `JMA_AREA_CODE_CITY` | `1311200` | 気象庁：市区町村コード（世田谷区） |
| `FUTAKO_LAT` / `FUTAKO_LON` | `35.6089` / `139.6236` | Open-Meteo Flood APIに渡す座標（二子玉川付近） |
| `RIVER_LEVEL_API_URL` / `RIVER_LEVEL_API_KEY` | 未設定 | 契約済み実測水位APIのエンドポイント（任意） |
| `RIVER_DANGER_LEVEL_M` | `3.8` | 実測水位の危険判定閾値[m]（要現地確認・調整） |
| `RIVER_CAUTION_LEVEL_M` | `2.5` | 実測水位の注意判定閾値[m]（要現地確認・調整） |
| `EXTERNAL_STATUS_CACHE_MINUTES` | `10` | 外部データの再取得キャッシュ時間（分） |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | 未設定 / `gemini-2.0-flash` | Gemini API（任意） |

## エンドポイント

| メソッド/パス | 説明 |
|---|---|
| `GET /` | 入力フォーム画面 |
| `GET /api/status` | 気象庁警報・河川データ・危険度をJSONで返す（フォーム表示時に自動取得、5分間隔で再取得） |
| `POST /admin/river_level` | スタッフによる実測水位の手動入力（`level_m`, `observed_at`, `entered_by`） |
| `POST /submit` | 観測データの送信・保存 |

## Googleフォーム → DB マッピング

| Googleフォーム上の表記 | テーブル / カラム |
|---|---|
| 日付・時間・観測員ID・観測エリア | `observations` (共通) |
| 【二子玉川BBQ場】観測項目一式 | `obs_bbq`（`observations.id` に1:1） |
| 【兵庫島公園1】観測項目一式 | `obs_hyogojima1` |
| 【兵庫島公園2】観測項目一式 | `obs_hyogojima2` |
| 危険フラグ（複数選択） | 各テーブルの `danger_flags` にカンマ区切りで格納 |
| 現場の写真 | 各テーブルの `photo_path`（`static/uploads/` 配下の相対パス） |
| （新規）AI強化サマリー | 各テーブルの `ai_summary`（Gemini API・任意） |
| （新規）気象庁・河川データ | `external_status_cache`（キャッシュ1行）、履歴は `alert_log` |
| （新規）実測水位の手動入力 | `river_level_manual_entry`（常に最新1行） |

## フロントエンドの警報バー・全画面アラート

- 画面上部の警報バーは `/api/status` を表示直後・5分ごとに取得し、
  「発令中の警報・注意報」「多摩川の実測水位（あれば）」を表示します。
- `alert_level` が `danger`（大雨警報・洪水警報・特別警報の発令、または実測水位が
  `RIVER_DANGER_LEVEL_M` 以上）の場合、画面全体に「【警告】即時避難推奨」のオーバーレイが
  自動的に表示されます。「確認しました」を押すとその状態では再表示されません
  （状態が変化すれば再度表示されます）。

## 注意点・確認事項

- 兵庫島公園2セクションの「水位」「水際接近」「滞留密度」は、フォーム画像上で
  必須マーク（*）が確認できなかったため、DB上は `NULL` 許容にしています。
- Open-Meteo Flood API は5km解像度のシミュレーションのため、
  「一番近い川」が意図した川と異なる場合があります（公式ドキュメントに明記）。
  座標を0.1度単位で微調整することが推奨されています。
- `RIVER_DANGER_LEVEL_M` / `RIVER_CAUTION_LEVEL_M` は暫定値です。
  必ず国交省が公表する二子橋観測所の「氾濫注意水位」「氾濫危険水位」の実際の値に
  置き換えてください。
- 危険フラグ・状況メモ・イベント発生・一言サマリーは元フォーム通り任意項目です。
- 運用移行時は、Googleフォームの回答スプレッドシートから本DBへの
  データ移行スクリプトが別途必要になる場合があります（現状は新規入力のみ対応）。

## 日次PDFレポート自動生成機能（Gemini 2.5 Flash + pdfkit）

観測データから、世田谷区役所への提出を想定した「安全パトロール報告書（PDF）」を
その場で生成できます。

### 使い方
1. `/dashboard` にアクセスすると、観測ログ一覧（AI一言サマリーのプレビュー付き）が表示されます。
2. 各行の「📄 PDFダウンロード」ボタンを押すと、その場でPDFが生成されダウンロードされます。
3. 一言サマリーが未生成の場合、ボタンを押した瞬間にGemini API（既定 `gemini-2.5-flash`）で
   自動生成され、以後はDBにキャッシュされます（`report_summary`列）。

### 新しいエンドポイント

| メソッド/パス | 説明 |
|---|---|
| `GET /dashboard` | 観測ログ一覧・PDFダウンロードの管理画面 |
| `GET /api/observations` | 観測ログ一覧をJSONで返す（ダッシュボード用） |
| `GET /api/report/<id>/pdf` | 指定した観測IDの安全パトロール報告書PDFを生成・返却。`?refresh=1`でAIサマリーを強制再生成 |

### PDF生成ライブラリについて
要件では weasyprint または pdfkit を想定していましたが、本実行環境のパッケージインデックスに
**weasyprintが存在しなかった**ため、**pdfkit（+ wkhtmltopdfバイナリ）** を採用しています。
どちらもHTML/CSSでレイアウトを組む方式のため、`templates/report.html` の見た目はそのまま維持できます。

- 動作には `wkhtmltopdf` バイナリが必要です：`apt-get install -y wkhtmltopdf`（Ubuntu/Debian）
- weasyprintが導入可能な環境に移行する場合は、`report_generator.py` の `render_report_pdf()` 内、
  `pdfkit.from_string(...)` の部分を `weasyprint.HTML(string=html).write_pdf()` に差し替えるだけで移行できます
  （テンプレート・CSSはほぼそのまま使えます）。
- 日本語が正しく表示されるよう、`templates/report.html` に `<meta charset="utf-8">` を必ず含め、
  pdfkitのオプションに `{"encoding": "UTF-8"}` を指定しています（未指定だと文字化けします）。

### 一言サマリーの生成ロジック
`report_generator.generate_report_summary()` が、リスクスコア・危険フラグ・状況メモを
Gemini 2.5 Flashに渡し、「客観的・簡潔・行政向けの文体（2〜3文・100文字程度）」で
一言サマリーを生成します。`GEMINI_API_KEY` 未設定時は、危険フラグ等から組み立てた
簡易な代替文を返すため、機能自体は止まりません。

### 写真の扱い
現場写真は `report_generator.resize_photo_to_data_uri()` でPillowによりリサイズ
（既定：最大幅900px、JPEG品質78）され、base64データURIとしてPDFに直接埋め込まれます。
外部ファイル参照ではないため、PDF単体で写真を含めて配布・保存できます。

### 新しいDBカラム
`obs_bbq` / `obs_hyogojima1` / `obs_hyogojima2` の各テーブルに以下を追加しました。

| カラム | 内容 |
|---|---|
| `report_summary` | 日次PDF報告書用のAI一言サマリー（キャッシュ） |
| `report_generated_at` | 上記の生成日時 |

新しい環境変数：`REPORT_GEMINI_MODEL`（既定 `gemini-2.5-flash`）、
`REPORT_PHOTO_MAX_WIDTH`（既定900）、`REPORT_PHOTO_JPEG_QUALITY`（既定78）
