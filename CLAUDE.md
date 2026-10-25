# テニスコート予約アプリ（tennis-court-app）

## 概要
- 横浜市の公園テニスコートの空き枠を自動スクレイピングして Google Calendar に連携するアプリ。
- **Render でデプロイ済み**（Docker コンテナ）。Mac サーバーではなく外部クラウド。
- リポジトリ：sukeis56/tennis-court-app

## 技術スタック
- **FastAPI + Playwright（スクレイピング）+ Google Calendar API**
- DB：SQLite（data/tennis.db）
- デプロイ：Docker / Render（render.yaml）
- 通知：LINE Messaging API

## 起動方法（ローカル）
```bash
uvicorn main:app --reload --port 8004
```

## 構成
- `main.py`：FastAPI 本体（カレンダー表示・スクレイプ実行・設定など）
- `config.py`：定数（対象公園、スクレイプ設定、LINE など）
- `database.py`：SQLite 接続
- `services/scraper.py`：Playwright でコート空き枠をスクレイピング
- `services/google_auth.py`：Google OAuth2（token.json に保存）
- `services/google_calendar.py`：Google Calendar の予定取得
- `services/line_notify.py`：LINE 通知
- `templates/`：base.html、calendar.html、partials/
- `static/`：style.css、sw.js、manifest.json
- `data/tennis.db`：SQLite DB（gitignore）
- `token.json`：Google OAuth トークン（gitignore・Render 環境変数で管理）
- `render.yaml`：Render デプロイ設定（Web サービス、Docker、ディスク1GB）

## 対象コート（config.py の PARKS）
- 三ツ沢公園、新横浜公園、入船公園、清水ケ丘公園

## 環境変数
| 変数 | 用途 | 設定場所 |
|---|---|---|
| LINE_CHANNEL_ACCESS_TOKEN | LINE 通知 | Render ダッシュボード |
| LINE_USER_ID | LINE 通知 | Render ダッシュボード |
| GOOGLE_CREDENTIALS_JSON | Google OAuth 認証情報（JSON 文字列） | Render ダッシュボード |
| GOOGLE_TOKEN_JSON | Google OAuth トークン（JSON 文字列） | Render ダッシュボード |

token.json は gitignore 済み。Render では環境変数 GOOGLE_TOKEN_JSON として管理。

## Render デプロイ設定
- プラン：free
- ランタイム：Docker
- ヘルスチェック：/status
- ディスク：tennis-data（/app/data、1GB）

## 現在の状態・次にやること
- 2026-10-25: Render でデプロイ済み。スクレイピング・カレンダー連携の基本機能は実装済み。
- 次：実際の動作確認。要確認（スクレイピングの精度、Google Calendar 連携の動作）。

## 詳しい資料
- docs/progress.md：作業の経緯（新しい順）
