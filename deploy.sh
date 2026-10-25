#!/bin/bash
# 自動デプロイスクリプト - cron から実行される
# crontab -e で: */2 * * * * /bin/bash /Users/kn/tennis-court-app/deploy.sh
export PATH="/opt/homebrew/bin:/usr/sbin:$PATH"
APP_DIR="$HOME/tennis-court-app"
PORT=8005
LOG="$APP_DIR/deploy.log"
PYTHON="$APP_DIR/venv/bin/python3"

cd "$APP_DIR" || exit 1

OLD_HASH=$(git rev-parse HEAD 2>/dev/null)
git pull --quiet 2>>"$LOG"
NEW_HASH=$(git rev-parse HEAD 2>/dev/null)

# 変更があった時、または起動していない時に再起動する
if [ "$OLD_HASH" != "$NEW_HASH" ] || ! pgrep -f "uvicorn main:app.*--port $PORT" >/dev/null; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') デプロイ開始: $OLD_HASH -> $NEW_HASH" >> "$LOG"
    # requirements.txt が変わった時だけ依存を入れ直す
    if [ "$OLD_HASH" != "$NEW_HASH" ] && git diff --name-only "$OLD_HASH" "$NEW_HASH" | grep -q requirements.txt; then
        "$PYTHON" -m pip install -q -r requirements.txt >> "$LOG" 2>&1
    fi
    pkill -f "uvicorn main:app.*--port $PORT" 2>/dev/null
    sleep 2
    nohup "$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port $PORT >> "$APP_DIR/uvicorn.log" 2>&1 &
    echo "$(date '+%Y-%m-%d %H:%M:%S') 起動完了 (PID: $!)" >> "$LOG"
fi
