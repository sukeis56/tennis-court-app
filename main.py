import asyncio
import calendar
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import database
from services.scraper import run_scrape
from services.line_notify import send_line_notification

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

app = FastAPI(title="Tennis Court Checker")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# --- スクレイパー状態管理 ---
scraper_state = {
    "running": False,
    "last_run": None,
    "task": None,
}


async def run_scrape_task(notify: bool = False):
    """asyncio.to_thread でスクレイパーを実行し、結果をDB保存"""
    if scraper_state["running"]:
        logger.info("スクレイプ既に実行中、スキップ")
        return

    scraper_state["running"] = True
    log_id = database.log_scrape_start()

    try:
        logger.info("スクレイプタスク開始")
        slots = await asyncio.to_thread(run_scrape)
        database.save_slots(slots)
        database.log_scrape_finish(log_id, "success", len(slots))
        scraper_state["last_run"] = datetime.now(JST)
        logger.info("スクレイプ完了: %d件", len(slots))

        # LINE通知
        if notify:
            await send_line_notification(slots)
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
    """毎朝7時(JST)にスクレイプ + LINE通知"""
    # 初回: 起動30秒後に実行（通知なし）
    await asyncio.sleep(30)
    try:
        await run_scrape_task(notify=False)
    except Exception as e:
        logger.error("初回スクレイプでエラー: %s", e)

    # 以降は毎朝7時に実行（通知あり）
    while True:
        wait = _seconds_until_next_run()
        await asyncio.sleep(wait)
        try:
            await run_scrape_task(notify=True)
        except Exception as e:
            logger.error("定期スクレイプでエラー: %s", e)


@app.on_event("startup")
async def startup():
    database.init_db()
    asyncio.create_task(scheduled_scrape_loop())
    logger.info("アプリ起動完了")


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

    context = {
        "request": request,
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
    }
    return templates.TemplateResponse("calendar.html", context)


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
        by_park[park]["courts"].setdefault(court, []).append(s["time"])

    context = {
        "request": request,
        "date_str": date_str,
        "slots_by_park": by_park,
        "total": len(slots),
        "base_url": config.BASE_URL,
    }
    return templates.TemplateResponse("partials/day_detail.html", context)


# --- 手動スクレイプ ---
@app.post("/scrape", response_class=HTMLResponse)
async def manual_scrape(request: Request):
    if not scraper_state["running"]:
        asyncio.create_task(run_scrape_task())
    return templates.TemplateResponse("partials/status_bar.html", {
        "request": request,
        "last_scrape": database.get_last_scrape(),
        "scraper_running": True,
        "total_slots": database.get_total_slot_count(),
    })


# --- ステータス ---
@app.get("/status", response_class=HTMLResponse)
async def status(request: Request):
    return templates.TemplateResponse("partials/status_bar.html", {
        "request": request,
        "last_scrape": database.get_last_scrape(),
        "scraper_running": scraper_state["running"],
        "total_slots": database.get_total_slot_count(),
    })


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
