# テニスコート予約アプリ（tennis-court-app）

## 概要
- 横浜市の公園テニスコートの空き枠を自動スクレイピングし、月カレンダーに表示するアプリ。Google カレンダーの予定（読み取りのみ）を重ねて表示し、LINE で空きを通知する。
- **Mac サーバーで稼働中**（ポート 8005）：http://mylifeapp.duckdns.org:8005 。以前は Render で動かしていたが削除済み。
- リポジトリ：sukeis56/tennis-court-app

## 技術スタック
- **FastAPI + Playwright（スクレイピング）+ Google Calendar API**
- DB：SQLite（data/tennis.db）
- デプロイ：Mac サーバー（~/tennis-court-app、venv は Homebrew の python3.11、cron で deploy.sh）
- 通知：LINE Messaging API

## 起動方法（ローカル）
```bash
uvicorn main:app --reload --port 8005
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
- `token.json`：Google OAuth トークン（gitignore）
- `deploy.sh`：Mac の自動デプロイ（git pull → 変更時に uvicorn 再起動、requirements 変更時は pip install）
- `render.yaml`・`Dockerfile`：旧 Render 用（未使用）

## 対象コート（config.py の PARKS）
- 三ツ沢公園、新横浜公園、入船公園、清水ケ丘公園

## 環境変数
Mac の `~/tennis-court-app/.env` に置く（config.py が python-dotenv で読む）。

| 変数 | 用途 |
|---|---|
| LINE_CHANNEL_ACCESS_TOKEN | LINE 通知 |
| LINE_USER_ID | LINE 通知 |

Google は Mac の `credentials.json`（OAuth クライアント）と `token.json`（ログイン後に自動作成）をファイルで使う。環境変数 GOOGLE_CREDENTIALS_JSON / GOOGLE_TOKEN_JSON は Render 時代の名残（コードは対応したまま）。

## Mac デプロイ
- 場所：`~/tennis-court-app`、ポート 8005、ログ `uvicorn.log`・`deploy.log`。
- cron（Mac 本体のターミナルで `crontab -e`）：`*/2 * * * * /bin/bash /Users/kn/tennis-court-app/deploy.sh`
- Chromium は `venv/bin/python3 -m playwright install chromium` で導入済み。

## 機能（コードから確認済み・2026-10-25）
- 開発期間：2026-03-16〜2026-04-22（最後の機能追加は「検索タイプ選択」）。
- 予約サイト：横浜市施設予約システム（`config.BASE_URL`）。
- **通常の空き検索**：「利用目的から探す」→テニス→4公園を選択→週ごとに「一部空き/空きあり/当日開放/翌日開放」のセルを開いて詳細テキストを解析。28日先まで。
- **開放待ち検索**：「日時から探す」→「開放待ち」で1週間ずつ検索。翌月末まで。開放日時が今日なら「当日開放」、それ以外は「翌日開放」。
- **時間フィルタ**：平日は 19:00 以降、土日は終日（祝日は平日扱い）。
- **画面**：月カレンダー（日曜始まり）に空き件数と Google 予定を表示。日付タップで公園別・コート別の空き枠。施設・日付・検索タイプ（両方/通常/開放待ち）を選んで手動スクレイプ。
- **Google カレンダー**：スコープは `calendar.readonly`。全カレンダーの予定を表示し、テニス・ジム予定のある日を「予定あり」として表示。祝日カレンダーは休日表示に使う。**予約をカレンダーに書き込む機能はない**。
- **LINE 通知**：毎朝 7:00 JST の定期スクレイプ後と手動スクレイプ後に、空き一覧をプッシュ送信。
- **定期実行**：アプリ内の asyncio ループ（cron ではない）。

## 構造上の注意
- ログイン機能なし。URL を知っていれば誰でもスクレイプ実行・`/test-notify` にアクセスできる（`/debug/check` は削除済み）。
- 施設一覧で対象公園が見つからない・画面遷移に失敗したときは、scrape_log に error として残る（サイト変更の検知に使う）。

## 現在の状態・次にやること
- 2026-10-25: コードを確認し、機能一覧を上に整理。
- 確認結果：Render は削除済みで稼働なし。そのため LINE 通知も止まっている。運用を再開する方針。
- PC で動作確認（三ツ沢・2026-10-31・通常検索）：
  - 画面は起動する。ポートは **8005**（8004 は Mac の部屋掃除アプリが使用中）。
  - スクレイピング：施設一覧で 4 公園を選べず全施設を選んでいた不具合と、凡例の「当日開放待ち」で全枠が当日開放扱いになる不具合を修正済み（2026-10-25）。時間フィルタなしで 3 週分 439 枠を取得できることを確認。フィルタあり（平日19時以降・土日）だと 0 件だが、実際に該当する空きがないため（19〜21時と土日は全て埋まっていた）。
  - **Google 予定は取れない**。token.json の client secret が無効（`invalid_client`）。OAuth クライアントの作り直しと再ログインが必要。
  - 開放待ち検索も動作確認済み。
- Mac にデプロイ済み（8005、外部から表示 OK）。Mac 上で三ツ沢・10/31 の検索が成功（開放待ち 2 枠）。
- cron 登録済み（2026-10-25、自動デプロイ動作確認済み）。
- 残り：①Mac に `.env`（LINE トークン）を置く ②Google OAuth クライアントを作り直す（リダイレクト URI は `http://localhost:8005/auth/callback`。https でない外部 URL は Google が許可しないため、PC でログイン → token.json を Mac にコピー。公開ステータスは「本番環境」に）。

## 詳しい資料
- docs/progress.md：作業の経緯（新しい順）
