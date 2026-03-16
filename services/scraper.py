import logging
import re
from datetime import datetime
from dataclasses import dataclass, asdict

from playwright.sync_api import sync_playwright

import config

logger = logging.getLogger(__name__)

TIME_BLOCKS = [
    (9, "9:00-11:00"), (11, "11:00-13:00"), (13, "13:00-15:00"),
    (15, "15:00-17:00"), (17, "17:00-19:00"), (19, "19:00-21:00"),
]


@dataclass
class AvailableSlot:
    park: str
    date: str        # YYYY-MM-DD
    day_of_week: str
    court: str
    time: str


class TennisChecker:

    def __init__(self, timeout=20000):
        self.timeout = timeout
        self.results: list[AvailableSlot] = []

    def run(self, parks: list[str], days_ahead: int = 14) -> list[AvailableSlot]:
        logger.info("スクレイプ開始: 施設=%s, 日数=%d", parks, days_ahead)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for park_name in parks:
                if park_name not in config.PARKS:
                    logger.warning("未対応の施設: %s", park_name)
                    continue

                logger.info("%s をチェック中...", park_name)
                page = browser.new_context(
                    viewport={"width": 1280, "height": 900}, locale="ja-JP"
                ).new_page()
                page.set_default_timeout(self.timeout)

                try:
                    self._check_park(page, park_name, days_ahead)
                except Exception as e:
                    logger.error("%s でエラー: %s", park_name, e, exc_info=True)
                finally:
                    page.close()

            browser.close()

        logger.info("スクレイプ完了: %d件の空き", len(self.results))
        return self.results

    def _check_park(self, page, park_name, days_ahead):
        park_info = config.PARKS[park_name]
        search_term = park_info["search"]
        self._navigate_to_availability(page, search_term, park_name)
        self._process_all_weeks(page, park_name, days_ahead)

    def _navigate_to_availability(self, page, search_term, park_name):
        logger.info("  トップページにアクセス中...")
        page.goto(config.BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(3000)

        logger.info("  「%s」で施設検索中...", search_term)
        page.click("text=施設名から探す")
        page.wait_for_timeout(2000)

        all_inputs = page.locator("input[type='text']")
        search_input = None
        for i in range(all_inputs.count()):
            inp = all_inputs.nth(i)
            if inp.is_visible():
                search_input = inp
        search_input.click()
        search_input.fill(search_term)
        page.wait_for_timeout(500)

        input_box = search_input.bounding_box()
        buttons = page.locator("button")
        for i in range(buttons.count()):
            btn = buttons.nth(i)
            if not btn.is_visible():
                continue
            if "検索" in (btn.inner_text() or ""):
                box = btn.bounding_box()
                if box and input_box and abs(box["y"] - input_box["y"]) < 50:
                    btn.click()
                    break
        page.wait_for_timeout(5000)

        checkboxes = page.locator("input[type='checkbox']")
        checked = False
        for i in range(checkboxes.count()):
            cb = checkboxes.nth(i)
            if cb.is_visible():
                cb.click(force=True)
                page.wait_for_timeout(300)
                checked = True
                break

        if not checked:
            logger.warning("  チェックボックスが見つかりません")
            return

        logger.info("  施設別空き状況ページへ...")
        btns = page.locator("button")
        for i in range(btns.count()):
            btn = btns.nth(i)
            if btn.is_visible() and "次へ進む" in (btn.inner_text() or ""):
                btn.click()
                break
        page.wait_for_timeout(5000)
        logger.info("  %s 施設別空き状況ページに到着", park_name)

    def _click_error_close(self, page):
        try:
            close_btn = page.locator("button:has-text('閉じる')")
            if close_btn.count() > 0 and close_btn.first.is_visible():
                close_btn.first.click()
                page.wait_for_timeout(500)
        except Exception:
            pass

    def _deselect_all(self, page, indices):
        if not indices:
            return
        available_tds = page.locator("td:has-text('一部空き'), td:has-text('空きあり')")
        current_count = available_tds.count()
        for idx in indices:
            try:
                if idx < current_count:
                    td = available_tds.nth(idx)
                    if td.is_visible():
                        td.click()
                        page.wait_for_timeout(150)
            except Exception:
                pass
        self._click_error_close(page)
        page.wait_for_timeout(300)

    def _process_all_weeks(self, page, park_name, days_ahead):
        weeks_to_check = (days_ahead // 7) + 2

        for week_num in range(weeks_to_check):
            logger.info("  [%s 週%d]", park_name, week_num + 1)

            available_tds = page.locator("td:has-text('一部空き'), td:has-text('空きあり')")
            total = available_tds.count()
            logger.info("    空きセル: %d件", total)

            if total == 0:
                logger.info("    空きなし")
            else:
                processed = 0
                batch_num = 0
                prev_indices = []

                while processed < total:
                    batch_num += 1
                    batch_end = min(processed + config.BATCH_SIZE, total)
                    logger.info("    [バッチ%d] %d~%d件目 (全%d件)", batch_num, processed + 1, batch_end, total)

                    if prev_indices:
                        self._deselect_all(page, prev_indices)

                    available_tds = page.locator("td:has-text('一部空き'), td:has-text('空きあり')")
                    current_count = available_tds.count()

                    clicked = 0
                    current_indices = []
                    for i in range(processed, min(processed + config.BATCH_SIZE, current_count)):
                        try:
                            td = available_tds.nth(i)
                            if td.is_visible():
                                td.click()
                                page.wait_for_timeout(150)
                                clicked += 1
                                current_indices.append(i)
                        except Exception:
                            pass

                    if clicked == 0:
                        break

                    self._click_error_close(page)

                    btns = page.locator("button")
                    for i in range(btns.count()):
                        btn = btns.nth(i)
                        if btn.is_visible() and "次へ進む" in (btn.inner_text() or ""):
                            btn.click()
                            break

                    page.wait_for_timeout(8000)

                    try:
                        full_text = page.inner_text("body")
                    except Exception:
                        full_text = ""

                    if len(full_text) > 100:
                        self._parse_detail_from_text(full_text, park_name)

                    btns2 = page.locator("button")
                    for i in range(btns2.count()):
                        btn = btns2.nth(i)
                        if btn.is_visible() and "前に戻る" in (btn.inner_text() or ""):
                            btn.click()
                            break
                    page.wait_for_timeout(3000)

                    prev_indices = current_indices
                    processed += clicked

                if prev_indices:
                    self._deselect_all(page, prev_indices)

            # 次の期間
            moved = False
            all_els = page.locator("button, a, span")
            for i in range(all_els.count()):
                try:
                    el = all_els.nth(i)
                    if el.is_visible() and "次の期間" in (el.inner_text() or ""):
                        el.click()
                        page.wait_for_timeout(3000)
                        moved = True
                        break
                except Exception:
                    continue
            if not moved:
                logger.info("    「次の期間」なし → 終了")
                break

    def _parse_detail_from_text(self, text, park_name):
        lines = [l.strip() for l in text.split('\n')]

        current_date = None
        current_dow = None
        current_court = None
        slot_values = []

        for line in lines:
            date_match = re.search(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日\s*\((.)\)', line)
            if date_match:
                self._process_court_data(park_name, current_date, current_dow, current_court, slot_values)
                slot_values = []
                current_court = None
                y, m, d, dow = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)), date_match.group(4)
                try:
                    current_date = datetime(y, m, d)
                    current_dow = dow
                except Exception:
                    current_date = None
                continue

            court_match = re.search(r'テニスコート\s*[０-９\d]+', line)
            if court_match and current_date:
                self._process_court_data(park_name, current_date, current_dow, current_court, slot_values)
                slot_values = []
                court_raw = court_match.group(0)
                num_match = re.search(r'[０-９\d]+', court_raw)
                if num_match:
                    num = num_match.group(0).translate(str.maketrans('０１２３４５６７８９', '0123456789'))
                    current_court = f"テニスコート{num}"
                continue

            if current_court and current_date:
                if line == '空きなし' or line == '休館日':
                    slot_values.append(('unavailable', line))
                elif re.match(r'\d+時から\d+時まで', line):
                    slot_values.append(('available', line))
                if len(slot_values) == 6:
                    self._process_court_data(park_name, current_date, current_dow, current_court, slot_values)
                    slot_values = []
                    current_court = None

        self._process_court_data(park_name, current_date, current_dow, current_court, slot_values)

    def _process_court_data(self, park_name, date, dow, court, slot_values):
        if not date or not court or not slot_values:
            return

        dow_idx = date.weekday()
        is_weekend = dow_idx >= 5
        min_hour = config.WEEKEND_MIN_HOUR if is_weekend else config.WEEKDAY_MIN_HOUR
        date_str = date.strftime("%Y-%m-%d")

        for idx, (status, text) in enumerate(slot_values):
            if idx >= len(TIME_BLOCKS):
                break
            start_hour, time_label = TIME_BLOCKS[idx]
            if start_hour < min_hour:
                continue
            if status == 'available':
                slot = AvailableSlot(
                    park=park_name, date=date_str, day_of_week=dow,
                    court=court, time=time_label,
                )
                if not any(
                    s.park == slot.park and s.date == slot.date
                    and s.court == slot.court and s.time == slot.time
                    for s in self.results
                ):
                    self.results.append(slot)
                    logger.info("      空き: %s(%s) %s %s", date_str, dow, court, time_label)


def run_scrape(parks: list[str] | None = None, days_ahead: int | None = None) -> list[dict]:
    """エントリポイント: スクレイプ実行して結果をdict listで返す"""
    if parks is None:
        parks = config.ALL_PARKS
    if days_ahead is None:
        days_ahead = config.SCRAPE_DAYS_AHEAD

    checker = TennisChecker()
    results = checker.run(parks, days_ahead)
    return [asdict(s) for s in results]
