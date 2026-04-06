import logging
import httpx
import config

logger = logging.getLogger(__name__)

LINE_API_URL = "https://api.line.me/v2/bot/message/push"


def build_message(slots: list[dict]) -> str:
    """空きスロットから通知メッセージを組み立てる"""
    if not slots:
        return "本日のチェック結果: 空きコートはありませんでした。"

    # 施設→日付→時間帯でグループ化
    by_park = {}
    for s in slots:
        park = s["park"]
        by_park.setdefault(park, {})
        date_key = f"{s['date']}({s['day_of_week']})"
        type_marker = ""
        if s.get("slot_type") == "same_day":
            type_marker = "[当日開放]"
        elif s.get("slot_type") == "next_day":
            type_marker = "[翌日開放]"
        by_park[park].setdefault(date_key, []).append(f"{type_marker}{s['time']} {s['court']}")

    lines = [f"テニスコート空き {len(slots)}件"]

    for park, dates in by_park.items():
        short = config.PARKS.get(park, {}).get("short", park)
        lines.append(f"\n【{short}】")
        for date_str, times in sorted(dates.items()):
            lines.append(f"  {date_str}")
            for t in sorted(times):
                lines.append(f"    {t}")

    lines.append(f"\n予約: {config.BASE_URL}")
    return "\n".join(lines)


async def send_line_notification(slots: list[dict]):
    """LINE Messaging APIでプッシュ通知を送信"""
    token = config.LINE_CHANNEL_ACCESS_TOKEN
    user_id = config.LINE_USER_ID

    if not token or not user_id:
        logger.warning("LINE設定が未完了 (LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID)")
        return

    message_text = build_message(slots)

    # 5000文字制限
    if len(message_text) > 5000:
        message_text = message_text[:4990] + "\n..."

    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": message_text,
            }
        ],
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                LINE_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("LINE通知送信成功")
            else:
                logger.error("LINE通知送信失敗: %d %s", resp.status_code, resp.text)
    except Exception as e:
        logger.error("LINE通知送信エラー: %s", e)
