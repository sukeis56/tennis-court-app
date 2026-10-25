# テニスコート予約アプリ（tennis-court-app）

## 概要
- 横浜市の公園テニスコートの空き枠を自動スクレイピングし、月カレンダーに表示するアプリ。Google カレンダーの予定（読み取りのみ）を重ねて表示し、LINE で空きを通知する。
- **現在どこでも稼働していない**。以前は Render（Docker）で動かしていたが、Render のサービスは削除済み。運用再開予定。
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

## Render デプロイ設定（旧・サービス削除済み。render.yaml は残してある）
- プラン：free
- ランタイム：Docker
- ヘルスチェック：/status
- ディスク：tennis-data（/app/data、1GB）

## 機能（コードから確認済み・2026-10-25）
- 開発期間：2026-03-16〜2026-04-22（最後の機能追加は「検索タイプ選択」）。
- 予約サイト：横浜市施設予約システム（`config.BASE_URL`）。
- **通常の空き検索**：「利用目的から探す」→テニス→4公園を選択→週ごとに「一部空き/空きあり/当日開放/翌日開放」のセルを開いて詳細テキストを解析。28日先まで。
- **開放待ち検索**：「日時から探す」→「開放待ち」で1週間ずつ検索。翌月末まで。種別は一律「翌日開放」扱い。
- **時間フィルタ**：平日は 19:00 以降、土日は終日（祝日は平日扱い）。
- **画面**：月カレンダー（日曜始まり）に空き件数と Google 予定を表示。日付タップで公園別・コート別の空き枠。施設・日付・検索タイプ（両方/通常/開放待ち）を選んで手動スクレイプ。
- **Google カレンダー**：スコープは `calendar.readonly`。全カレンダーの予定を表示し、テニス・ジム予定のある日を「予定あり」として表示。祝日カレンダーは休日表示に使う。**予約をカレンダーに書き込む機能はない**。
- **LINE 通知**：毎朝 7:00 JST の定期スクレイプ後と手動スクレイプ後に、空き一覧をプッシュ送信。
- **定期実行**：アプリ内の asyncio ループ（cron ではない）。

## 構造上の注意（コードから分かる弱点）
- Render 無料プランは 15 分アクセスがないとスリープする → 7:00 の定期スクレイプはスリープ中は動かない。
- Render の永続ディスクは有料プランのみ → 無料プランでは再起動・再デプロイで DB（空き枠・履歴）が消える。
- Google トークンの更新結果はメモリにしか保存されない（Render ではファイルが消えるため）。refresh_token が有効な間は問題なし。
- ログイン機能なし。URL を知っていれば誰でもスクレイプ実行・`/test-notify`・`/debug/check`（トークン先頭を表示）にアクセスできる。

## 現在の状態・次にやること
- 2026-10-25: コードを確認し、機能一覧を上に整理。
- 確認結果：Render は削除済みで稼働なし。そのため LINE 通知も止まっている。運用を再開する方針。
- PC で動作確認（三ツ沢・2026-10-31・通常検索）：
  - 画面は起動する（`uvicorn main:app --port 8004`）。
  - **スクレイピングは 0 件で壊れている**。サイトの「テニス選択→検索→施設選択→週ごとの空きセル（一部空き 24〜27件）→詳細ページ」までは進むが、詳細ページから枠を 1 件も取り出せない。詳細ページの注意書きに「当日開放」の文字があるため、全ページが当日開放扱いになる誤判定もある。
  - **Google 予定は取れない**。token.json の client secret が無効（`invalid_client`）。OAuth クライアントの作り直しと再ログインが必要。
  - LINE は PC に環境変数がないため未送信（想定どおり）。
- 次：①詳細ページのパースを今のサイトに合わせて直す → ②Google OAuth を作り直す → ③稼働先を決めてデプロイ（Mac サーバー案。Render 無料プランはスリープと DB 消失のため不向き）。

## 詳しい資料
- docs/progress.md：作業の経緯（新しい順）
