import asyncio
import calendar
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request, Query
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import database
from services.scraper import run_scrape, run_release_scrape
from services.line_notify import send_line_notification
from services.google_auth import load_credentials, get_flow, save_credentials, clear_credentials
from services.google_calendar import list_events_for_month

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# テニス・ジムなど除外すべきイベントのキーワード
BUSY_KEYWORDS = ["テニス", "ジム", "RAT", "TOP", "GODAI", "新横浜", "三ツ沢", "三ッ沢", "入船", "清水ケ丘"]

# イベントカテゴリ定義: (キーワード, 絵文字, CSSクラス)
EVENT_CATEGORIES = [
    # 公園テニス（黄緑）
    (["新横浜", "三ツ沢", "三ッ沢", "入船", "清水ケ丘", "公園テニス"], "\U0001F3BE", "ev-park"),
    # テニススクール（青）
    (["TOP", "GODAI", "テニススクール", "スクール"], "\U0001F3BE", "ev-school"),
    # ジム（赤）
    (["RAT", "ジム", "トレーニング", "筋トレ"], "\U0001F4AA", "ev-gym"),
    # その他
    (["ランニング", "ジョギング", "マラソン"], "\U0001F3C3", "ev-default"),
    (["会議", "ミーティング", "MTG", "打ち合わせ"], "\U0001F4BC", "ev-default"),
    (["飲み", "飲み会", "食事", "ランチ", "ディナー"], "\U0001F37B", "ev-default"),
    (["病院", "歯医者", "クリニック", "通院"], "\U0001F3E5", "ev-default"),
    (["旅行", "出張"], "\U00002708", "ev-default"),
    (["誕生日", "バースデー"], "\U0001F382", "ev-default"),
    (["買い物", "ショッピング"], "\U0001F6CD", "ev-default"),
    (["美容院", "散髪", "ヘアサロン"], "\U00002702", "ev-default"),
]
DEFAULT_EMOJI = "\U0001F4C5"  # 📅
DEFAULT_CLASS = "ev-default"


def _get_event_info(summary: str) -> tuple[str, str]:
    """イベント名から (絵文字, CSSクラス) を返す"""
    for keywords, emoji, css_class in EVENT_CATEGORIES:
        if any(kw in summary for kw in keywords):
            return emoji, css_class
    return DEFAULT_EMOJI, DEFAULT_CLASS


def _format_event_short(ev: dict) -> str:
    """カレンダーグリッド用の短い表示: '19:00🎾'"""
    emoji, _ = _get_event_info(ev.get("summary", ""))
    time = ev.get("start_time", "")
    if time:
        return f"{time}{emoji}"
    return emoji


app = FastAPI(title="Tennis Court Checker")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# --- スクレイパー状態管理 ---
scraper_state = {
    "running": False,
    "last_run": None,
    "task": None,
}


async def run_scrape_task(
    notify: bool = False,
    parks: list[str] | None = None,
    target_dates: list[str] | None = None,
    search_type: str = "both",
):
    """asyncio.to_thread でスクレイパーを実行し、結果をDB保存
    search_type: "both" | "normal" | "release"
    """
    if scraper_state["running"]:
        logger.info("スクレイプ既に実行中、スキップ")
        return

    scraper_state["running"] = True
    log_id = database.log_scrape_start()

    try:
        logger.info("スクレイプタスク開始 (施設=%s, 日付=%s, タイプ=%s)", parks, target_dates, search_type)

        all_slots = []

        # 通常の空きスクレイプ
        if search_type in ("both", "normal"):
            slots = await asyncio.to_thread(run_scrape, parks, None, target_dates)
            logger.info("通常スクレイプ完了: %d件", len(slots))
            all_slots.extend(slots)

        # 開放待ちスクレイプ（翌月末まで）
        if search_type in ("both", "release"):
            today = datetime.now(JST).date()
            nm_year = today.year + (1 if today.month == 12 else 0)
            nm_month = 1 if today.month == 12 else today.month + 1
            last_day = calendar.monthrange(nm_year, nm_month)[1]
            release_days_ahead = (today.replace(year=nm_year, month=nm_month, day=last_day) - today).days + 1
            release_slots = await asyncio.to_thread(run_release_scrape, parks, release_days_ahead, target_dates)
            logger.info("開放待ちスクレイプ完了: %d件 (翌月末まで %d日)", len(release_slots), release_days_ahead)
            all_slots.extend(release_slots)

        database.save_slots(all_slots)
        database.log_scrape_finish(log_id, "success", len(all_slots))
        scraper_state["last_run"] = datetime.now(JST)
        logger.info("スクレイプ完了（合計）: %d件", len(all_slots))

        # LINE通知
        if notify:
            await send_line_notification(all_slots)
    except Exception as e:
        logger.error("スクレイプ失敗: %s", e, exc_info=True)
        database.log_scrape_finish(log_id, "error", error_message=str(e))
    finally:
        scraper_state["running"] = False


def _seconds_until_next_run() -> float:
    """次の実行時刻(JST 7:00)までの秒数を計算"""
    now = datetime.now(JST)
    target = now.replace(hour=config.SCRAPE_HOUR_JST, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    wait = (target - now).total_seconds()
    logger.info("次回スクレイプ: %s (あと%.0f秒)", target.strftime("%Y-%m-%d %H:%M JST"), wait)
    return wait


async def scheduled_scrape_loop():
    """毎朝7時(JST)にスクレイプ + LINE通知（起動時の自動実行なし）"""
    while True:
        wait = _seconds_until_next_run()
        await asyncio.sleep(wait)
        try:
            await run_scrape_task(notify=True)
        except Exception as e:
            logger.error("定期スクレイプでエラー: %s", e)


def _get_calendar_events(year: int, month: int) -> tuple[dict, set[str]]:
    """Googleカレンダーからイベントを取得。祝日は除外し、祝日日付セットを別途返す"""
    creds = load_credentials()
    if not creds:
        logger.warning("Google認証情報なし → カレンダー取得スキップ")
        return {}, set()

    logger.info("Googleカレンダー取得開始: %d年%d月", year, month)
    try:
        events = list_events_for_month(creds, year, month)
        logger.info("Googleカレンダー取得成功: %d件のイベント", len(events))
    except Exception as e:
        logger.error("Googleカレンダー取得失敗: %s", e, exc_info=True)
        return {}, set()
    by_date = {}
    holiday_dates = set()
    for ev in events:
        # 祝日カレンダーのイベントは除外し、日付だけ記録
        cal_name = ev.get("calendar_name", "")
        if "祝日" in cal_name or "Holiday" in cal_name.lower():
            holiday_dates.add(ev["date"])
            continue

        summary = ev.get("summary", "")
        emoji, css_class = _get_event_info(summary)
        ev["short"] = _format_event_short(ev)
        ev["emoji"] = emoji
        ev["css_class"] = css_class
        date = ev["date"]
        by_date.setdefault(date, []).append(ev)
    return by_date, holiday_dates


def _get_busy_dates(year: int, month: int) -> set[str]:
    """テニス・ジムの予定がある日付を返す"""
    creds = load_credentials()
    if not creds:
        return set()

    events = list_events_for_month(creds, year, month)
    busy = set()
    for ev in events:
        _, css_class = _get_event_info(ev.get("summary", ""))
        if css_class in ("ev-park", "ev-school", "ev-gym"):
            busy.add(ev["date"])
    return busy


@app.on_event("startup")
async def startup():
    database.init_db()
    asyncio.create_task(scheduled_scrape_loop())
    logger.info("アプリ起動完了")


# --- Google認証 ---
# Flowをリクエストをまたいで保持（PKCEのcode_verifier対策）
_pending_flow = {}


@app.get("/auth/login")
async def auth_login(request: Request):
    redirect_uri = str(request.base_url) + "auth/callback"
    try:
        flow = get_flow(redirect_uri)
    except Exception as e:
        return HTMLResponse(f"<p>Flow作成でエラー: {e}</p>", status_code=500)
    if not flow:
        has_env = bool(os.environ.get("GOOGLE_CREDENTIALS_JSON", ""))
        return HTMLResponse(
            f"<p>Google認証情報が見つかりません。<br>"
            f"環境変数 GOOGLE_CREDENTIALS_JSON: {'設定あり' if has_env else '未設定'}</p>",
            status_code=500,
        )
    flow.code_verifier = None  # PKCEを無効化
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    _pending_flow[state] = flow
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = ""):
    if not code:
        return RedirectResponse("/")
    # 保存したFlowを再利用
    flow = _pending_flow.pop(state, None)
    if not flow:
        redirect_uri = str(request.base_url) + "auth/callback"
        flow = get_flow(redirect_uri)
        flow.code_verifier = None
    flow.fetch_token(code=code)
    save_credentials(flow.credentials)
    return RedirectResponse("/")


@app.get("/auth/logout")
async def auth_logout():
    clear_credentials()
    return RedirectResponse("/")


# --- PWA ---
@app.get("/sw.js")
async def service_worker():
    return FileResponse(
        Path(__file__).parent / "static" / "sw.js",
        media_type="application/javascript",
    )


# --- メインページ ---
@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    year: int = 0,
    month: int = 0,
    park: str = "",
):
    now = datetime.now(JST)
    if year == 0:
        year = now.year
    if month == 0:
        month = now.month

    # カレンダーグリッド
    cal = calendar.Calendar(firstweekday=6)  # 日曜始まり
    month_days = cal.monthdayscalendar(year, month)

    # 前月・次月
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    # 空きデータ
    dates_with_slots = database.get_dates_with_slots(year, month)
    total_slots = database.get_total_slot_count()
    last_scrape = database.get_last_scrape()
    is_current_month = (year == now.year and month == now.month)
    today_str = now.strftime("%Y-%m-%d")

    # 選択中の施設フィルター
    selected_parks = [p.strip() for p in park.split(",") if p.strip()] if park else []

    # Googleカレンダー連携
    calendar_events, holiday_dates = _get_calendar_events(year, month)
    busy_dates = _get_busy_dates(year, month)
    gcal_connected = load_credentials() is not None

    context = {
        "year": year,
        "month": month,
        "month_days": month_days,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "dates_with_slots": dates_with_slots,
        "total_slots": total_slots,
        "last_scrape": last_scrape,
        "is_current_month": is_current_month,
        "today_str": today_str,
        "parks": config.PARKS,
        "selected_parks": selected_parks,
        "scraper_running": scraper_state["running"],
        "calendar_events": calendar_events,
        "busy_dates": sorted(busy_dates),
        "holiday_dates": sorted(holiday_dates),
        "gcal_connected": gcal_connected,
    }
    return templates.TemplateResponse(request=request, name="calendar.html", context=context)


# --- 日別詳細 ---
@app.get("/day/{date_str}", response_class=HTMLResponse)
async def day_detail(request: Request, date_str: str, park: str = ""):
    selected_parks = [p.strip() for p in park.split(",") if p.strip()] if park else None
    slots = database.get_slots_for_date_filtered(date_str, selected_parks)

    # 施設ごと→コートごとにグループ化
    by_park = {}
    for s in slots:
        park = s["park"]
        court = s["court"]
        if park not in by_park:
            by_park[park] = {"courts": {}, "count": 0}
        by_park[park]["count"] += 1
        by_park[park]["courts"].setdefault(court, []).append({
            "time": s["time"],
            "slot_type": s.get("slot_type", "normal"),
        })

    # Googleカレンダーのイベント
    cal_events = []
    creds = load_credentials()
    if creds:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            all_events = list_events_for_month(creds, dt.year, dt.month)
            cal_events = [e for e in all_events if e["date"] == date_str]
            for ev in cal_events:
                emoji, css_class = _get_event_info(ev.get("summary", ""))
                ev["short"] = _format_event_short(ev)
                ev["emoji"] = emoji
                ev["css_class"] = css_class
        except Exception:
            pass

    context = {
        "date_str": date_str,
        "slots_by_park": by_park,
        "total": len(slots),
        "base_url": config.BASE_URL,
        "calendar_events": cal_events,
    }
    return templates.TemplateResponse(request=request, name="partials/day_detail.html", context=context)


# --- 手動スクレイプ ---
@app.post("/scrape", response_class=HTMLResponse)
async def manual_scrape(
    request: Request,
    parks: list[str] = Form(default=[]),
    dates: list[str] = Form(default=[]),
    search_type: str = Form(default="both"),
):
    if not scraper_state["running"]:
        selected_parks = parks if parks else None
        target_dates = [d for d in dates if d] if dates else None
        if search_type not in ("both", "normal", "release"):
            search_type = "both"
        asyncio.create_task(run_scrape_task(
            notify=True,
            parks=selected_parks,
            target_dates=target_dates,
            search_type=search_type,
        ))
    return templates.TemplateResponse(request=request, name="partials/status_bar.html", context={
        "last_scrape": database.get_last_scrape(),
        "scraper_running": True,
        "total_slots": database.get_total_slot_count(),
    })


# --- LINE通知テスト ---
@app.post("/test-notify", response_class=HTMLResponse)
async def test_notify(request: Request):
    slots = [{"park": "テスト公園", "date": "2026-03-17", "day_of_week": "火", "court": "テニスコート1", "time": "9:00-11:00"}]
    await send_line_notification(slots)
    return HTMLResponse("<p>テスト通知を送信しました</p>")


# --- ステータス ---
@app.get("/status", response_class=HTMLResponse)
async def status(request: Request):
    return templates.TemplateResponse(request=request, name="partials/status_bar.html", context={
        "last_scrape": database.get_last_scrape(),
        "scraper_running": scraper_state["running"],
        "total_slots": database.get_total_slot_count(),
    })


@app.get("/debug/check", response_class=HTMLResponse)
async def debug_check():
    creds = load_credentials()
    lines = [f"creds: {'OK' if creds else 'None'}"]
    if creds:
        lines.append(f"token (先頭30): {creds.token[:30] if creds.token else 'None'}...")
        lines.append(f"expired: {creds.expired}")
        lines.append(f"valid: {creds.valid}")
        lines.append(f"scopes: {creds.scopes}")
        try:
            from googleapiclient.discovery import build
            service = build("calendar", "v3", credentials=creds)
            # カレンダー一覧
            cal_list = service.calendarList().list().execute()
            cals = cal_list.get("items", [])
            lines.append(f"calendars: {len(cals)}件")
            for c in cals[:5]:
                lines.append(f"  - {c.get('summary', '?')} (id: {c['id'][:30]}...)")
            # イベント取得
            events = list_events_for_month(creds, 2026, 4)
            lines.append(f"events (2026-04): {len(events)}件")
            for e in events[:10]:
                lines.append(f"  {e['date']} {e.get('start_time','')} {e['summary']}")
        except Exception as e:
            import traceback
            lines.append(f"API error: {e}")
            lines.append(traceback.format_exc().replace('\n', '<br>'))
    try:
        slots = database.get_slots_for_date("2026-04-16")
        lines.append(f"slots for 4/16: {len(slots)}件")
        for s in slots[:5]:
            lines.append(f"  {s['park']} {s['court']} {s['time']} type={s.get('slot_type','?')}")
    except Exception as e:
        lines.append(f"slots error: {e}")
    return HTMLResponse(f"<pre>{'<br>'.join(lines)}</pre>")


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
