# テニスコート予約アプリ 作業記録

## 2026-10-25（2回目）
- やったこと：
  - コードと git log から機能一覧・弱点を CLAUDE.md に整理。Render は削除済みで稼働なし（LINE 通知も停止中）と確認。
  - PC で動作確認。スクレイピングが 0 件 → 原因 2 つを修正：①施設一覧のチェックボックスが透明で is_visible に弾かれ全施設選択にフォールバック → 親 div の文字で判定して check、見つからなければエラー ②凡例の「当日開放待ち」でページ全体を当日開放扱い → 判定削除。
  - フィルタなしで 439 枠取得を確認。19〜21時・土日は実際に空きゼロで、フィルタありの 0 件は正しい。
  - 開放待ち：開放日時列で当日/翌日を判定、コート名を半角に統一。動作確認済み。
  - Google 予定は `invalid_client`（client secret 無効）で取得不可と判明。
  - Mac デプロイ：deploy.sh（8005）・.gitattributes・.env 読み込みを追加、/debug/check を削除。Mac に clone・venv（Homebrew python3.11）・Chromium を導入。起動・検索・外部 URL・cron 自動デプロイを確認。
- 決めたこと（理由も一言）：
  - 運用再開。稼働先は Mac（Render 無料はスリープで 7 時実行が動かず DB も消えるため）。
  - ポート 8005（8004 は部屋掃除アプリが使用中）。
  - Google ログインは PC の localhost で行い token.json を Mac にコピー（Google は https でない外部リダイレクト URI を許可しないため）。
- 未解決・次回：LINE トークンを Mac の .env に置く／Google OAuth クライアント作り直し（公開ステータスは本番環境に）／ログインなしで誰でもスクレイプ実行できる点。

## 2026-10-25
- やったこと：CLAUDE.md を新規作成。remote URL を確認（変更不要）。token.json の git 追跡状況を確認（gitignore 済み・追跡なし、問題なし）。
- 決めたこと：特になし。
- 未解決・次回：Render でのデプロイ状況・動作確認（スクレイピング精度、Google Calendar 連携）。
