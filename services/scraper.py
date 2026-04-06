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
    slot_type: str = "normal"  # "normal", "same_day", "next_day"


class TennisChecker:

    def __init__(self, timeout=60000):
        self.timeout = timeout
        self.results: list[AvailableSlot] = []

    def run(self, parks: list[str], days_ahead: int = 14, target_dates: set[str] | None = None) -> list[AvailableSlot]:
        logger.info("スクレイプ開始: 施設=%s, 日数=%d, 対象日=%s", parks, days_ahead, target_dates)
        self.target_dates = target_dates

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(
                viewport={"width": 1280, "height": 900}, locale="ja-JP"
            ).new_page()
            page.set_default_timeout(self.timeout)

            try:
                self._navigate_by_purpose(page, parks)
                self._process_all_weeks(page, days_ahead)
            except Exception as e:
                logger.error("スクレイプでエラー: %s", e, exc_info=True)
            finally:
                page.close()
                browser.close()

        logger.info("スクレイプ完了: %d件の空き", len(self.results))
        return self.results

    def _navigate_by_purpose(self, page, parks: list[str]):
        """「利用目的から探す」→「テニス」チェック→ 検索 → 施設選択"""
        logger.info("  トップページにアクセス中...")
        page.goto(config.BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # 「利用目的から探す」タブをクリック
        logger.info("  「利用目的から探す」を選択中...")
        page.click("text=利用目的から探す")
        page.wait_for_timeout(2000)

        # 「スポーツ」分類が選ばれていることを確認（デフォルトで選択済みの可能性）
        try:
            sports_radio = page.locator("text=スポーツ").first
            if sports_radio.is_visible():
                sports_radio.click()
                page.wait_for_timeout(500)
        except Exception:
            pass

        # 「テニス」のチェックボックスをクリック
        logger.info("  「テニス」のチェックボックスを選択中...")
        # チェックボックスのラベルとして「テニス」を探す
        tennis_checked = False
        checkboxes = page.locator("input[type='checkbox']")
        for i in range(checkboxes.count()):
            cb = checkboxes.nth(i)
            if not cb.is_visible():
                continue
            try:
                # ラベルや親要素のテキストを確認
                label = cb.locator("xpath=parent::label | xpath=following-sibling::*[1] | xpath=ancestor::label[1]")
                if label.count() > 0:
                    text = label.first.inner_text().strip()
                    if text == "テニス":
                        cb.click(force=True)
                        tennis_checked = True
                        logger.info("    ✓ テニスを選択（チェックボックス経由）")
                        break
            except Exception:
                pass

        # チェックボックスで見つからなければラベルテキストをクリック
        if not tennis_checked:
            try:
                # ラベル要素をテキストで検索
                labels = page.locator("label")
                for i in range(labels.count()):
                    label = labels.nth(i)
                    if label.is_visible() and label.inner_text().strip() == "テニス":
                        label.click()
                        tennis_checked = True
                        logger.info("    ✓ テニスを選択（ラベル経由）")
                        break
            except Exception:
                pass

        if not tennis_checked:
            logger.warning("  テニスのチェックボックスが見つかりませんでした")

        page.wait_for_timeout(1000)

        # 青い「検索」ボタンをクリック（右下の大きなボタン）
        logger.info("  検索ボタンをクリック...")
        clicked_search = False
        # 方法1: テキストに「検索」を含むボタン/リンクを探す
        candidates = page.locator("button, a, [role='button']")
        for i in range(candidates.count()):
            el = candidates.nth(i)
            try:
                if not el.is_visible():
                    continue
                text = el.inner_text().strip()
                if text in ("検索", "Q 検索") or text.endswith("検索"):
                    el.click()
                    clicked_search = True
                    logger.info("    ✓ 検索ボタンをクリック: '%s'", text)
                    break
            except Exception:
                continue

        if not clicked_search:
            # 方法2: onclick属性にsearchByPurposeを含む要素を探す
            try:
                el = page.locator("[onclick*='searchByPurpose']").first
                if el.is_visible():
                    el.click()
                    clicked_search = True
                    logger.info("    ✓ 検索ボタンをクリック (onclick経由)")
            except Exception:
                pass

        if not clicked_search:
            # 方法3: Vue.jsのメソッド呼び出し
            try:
                page.evaluate("document.querySelector('[onclick*=\"search\"]')?.click()")
                logger.info("    ✓ 検索ボタンをクリック (JS経由)")
            except Exception:
                logger.warning("  検索ボタンが見つかりませんでした")

        page.wait_for_timeout(5000)

        # 「さらに読み込む」があればクリック（新横浜公園など追加施設を表示）
        self._click_load_more(page)

        # 施設のチェックボックスを選択
        self._select_facilities(page, parks)

        # 「次へ進む」をクリック
        logger.info("  施設別空き状況ページへ...")
        btns = page.locator("button")
        for i in range(btns.count()):
            btn = btns.nth(i)
            if btn.is_visible() and "次へ進む" in (btn.inner_text() or ""):
                btn.click()
                break
        page.wait_for_timeout(5000)
        logger.info("  施設別空き状況ページに到着")

    def _click_load_more(self, page):
        """「さらに読み込む」ボタンがあれば全てクリック"""
        max_clicks = 5
        for _ in range(max_clicks):
            try:
                load_more = page.locator("button:has-text('さらに読み込む'), a:has-text('さらに読み込む')")
                if load_more.count() > 0 and load_more.first.is_visible():
                    logger.info("  「さらに読み込む」をクリック...")
                    load_more.first.click()
                    page.wait_for_timeout(3000)
                else:
                    break
            except Exception:
                break

    def _select_facilities(self, page, parks: list[str]):
        """施設一覧から対象施設のチェックボックスをONにする"""
        # まず全チェックボックスを取得
        # 施設名テキストの近くにあるチェックボックスを探す
        body_text = page.inner_text("body")
        logger.info("  施設一覧から対象を選択中... (対象: %s)", [config.PARKS[p]["short"] for p in parks])

        checkboxes = page.locator("input[type='checkbox']")
        checkbox_count = checkboxes.count()
        logger.info("  チェックボックス数: %d", checkbox_count)

        checked_count = 0
        for i in range(checkbox_count):
            cb = checkboxes.nth(i)
            if not cb.is_visible():
                continue

            # チェックボックスの親要素や近くのテキストを取得
            try:
                # 親の行やラベルのテキストを取得
                parent = cb.locator("xpath=ancestor::*[self::label or self::div or self::tr or self::li][1]")
                if parent.count() > 0:
                    parent_text = parent.first.inner_text()
                else:
                    parent_text = ""
            except Exception:
                parent_text = ""

            # 対象施設に一致するかチェック
            for park_name in parks:
                search_key = config.PARKS[park_name]["search"]
                if search_key in parent_text:
                    cb.click(force=True)
                    page.wait_for_timeout(300)
                    checked_count += 1
                    logger.info("    ✓ %s を選択", park_name)
                    break

        if checked_count == 0:
            logger.warning("  対象施設が見つかりませんでした。全施設を選択します。")
            # フォールバック: 見つからなければ全チェックボックスをON
            for i in range(checkbox_count):
                cb = checkboxes.nth(i)
                if cb.is_visible():
                    cb.click(force=True)
                    page.wait_for_timeout(200)
        else:
            logger.info("  %d施設を選択", checked_count)

    def _click_error_close(self, page):
        try:
            close_btn = page.locator("button:has-text('閉じる')")
            if close_btn.count() > 0 and close_btn.first.is_visible():
                close_btn.first.click()
                page.wait_for_timeout(500)
        except Exception:
            pass

    # 空きセル検出用ロケーター（当日開放・翌日開放も含む）
    AVAILABLE_SELECTOR = (
        "td:has-text('一部空き'), td:has-text('空きあり'), "
        "td:has-text('当日開放'), td:has-text('翌日開放')"
    )

    def _deselect_all(self, page, indices):
        if not indices:
            return
        available_tds = page.locator(self.AVAILABLE_SELECTOR)
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

    def _process_all_weeks(self, page, days_ahead):
        weeks_to_check = (days_ahead // 7) + 2
        consecutive_errors = 0

        for week_num in range(weeks_to_check):
            logger.info("  [週%d/%d]", week_num + 1, weeks_to_check)

            try:
                self._process_one_week(page)
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                logger.warning("  週%d でエラー（%d回連続）: %s", week_num + 1, consecutive_errors, e)
                self._click_error_close(page)
                page.wait_for_timeout(2000)
                if consecutive_errors >= 3:
                    logger.error("  3回連続エラー → 中断（取得済み %d件は保持）", len(self.results))
                    break

            # 次の期間
            moved = False
            try:
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
            except Exception:
                pass
            if not moved:
                logger.info("    「次の期間」なし → 終了")
                break

    def _classify_cell(self, td) -> str:
        """セルのテキストからスロットタイプを判定"""
        try:
            text = td.inner_text()
            if "当日開放" in text:
                return "same_day"
            if "翌日開放" in text:
                return "next_day"
        except Exception:
            pass
        return "normal"

    def _process_one_week(self, page):
        """1週間分の空きセルをタイプ別に処理"""
        available_tds = page.locator(self.AVAILABLE_SELECTOR)
        total = available_tds.count()
        logger.info("    空きセル: %d件", total)

        if total == 0:
            logger.info("    空きなし")
            return

        # まず全セルのテキストとタイプをログに記録
        available_tds = page.locator(self.AVAILABLE_SELECTOR)
        initial_total = available_tds.count()
        for i in range(min(initial_total, 10)):  # 最初の10件だけログ
            try:
                td = available_tds.nth(i)
                if td.is_visible():
                    cell_text = td.inner_text().strip().replace('\n', ' ')
                    cell_type = self._classify_cell(td)
                    logger.info("    セル[%d]: '%s' → %s", i, cell_text[:40], cell_type)
            except Exception:
                pass

        # タイプごとに処理（毎回セルを再スキャンしてインデックスを取得）
        for slot_type in ["normal", "same_day", "next_day"]:
            available_tds = page.locator(self.AVAILABLE_SELECTOR)
            current_total = available_tds.count()
            indices = []
            for i in range(current_total):
                try:
                    td = available_tds.nth(i)
                    if not td.is_visible():
                        continue
                    cell_type = self._classify_cell(td)
                    if cell_type == slot_type:
                        indices.append(i)
                except Exception:
                    pass

            if not indices:
                continue
            logger.info("    [%s] %d件を処理", slot_type, len(indices))
            self._process_cells_by_indices(page, indices, slot_type)

    def _process_cells_by_indices(self, page, indices: list[int], slot_type: str):
        """指定インデックスのセルをバッチ処理"""
        processed = 0
        batch_num = 0
        prev_indices = []

        while processed < len(indices):
            batch_num += 1
            batch_targets = indices[processed:processed + config.BATCH_SIZE]
            logger.info("      [バッチ%d] %d件", batch_num, len(batch_targets))

            if prev_indices:
                self._deselect_all(page, prev_indices)

            available_tds = page.locator(self.AVAILABLE_SELECTOR)

            clicked = 0
            current_indices = []
            for idx in batch_targets:
                try:
                    td = available_tds.nth(idx)
                    if td.is_visible():
                        td.click()
                        page.wait_for_timeout(150)
                        clicked += 1
                        current_indices.append(idx)
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
                self._parse_detail_from_text(full_text, slot_type=slot_type)

            btns2 = page.locator("button")
            for i in range(btns2.count()):
                btn = btns2.nth(i)
                if btn.is_visible() and "前に戻る" in (btn.inner_text() or ""):
                    btn.click()
                    break
            page.wait_for_timeout(3000)

            prev_indices = current_indices
            processed += len(batch_targets)

        if prev_indices:
            self._deselect_all(page, prev_indices)

    def _detect_park_name(self, text):
        """テキストから施設名を推定する"""
        for park_name, park_info in config.PARKS.items():
            if park_info["search"] in text or park_name in text:
                return park_name
        return "不明な施設"

    def _parse_detail_from_text(self, text, slot_type: str = "normal"):
        """詳細ページのテキストをパースしてスロットを抽出（複数施設対応）"""
        lines = [l.strip() for l in text.split('\n')]

        current_park = None
        current_date = None
        current_dow = None
        current_court = None
        slot_values = []

        for line in lines:
            # 施設名を検出
            for park_name, park_info in config.PARKS.items():
                if park_name in line or park_info["search"] in line:
                    if not re.search(r'\d{4}年', line) and 'テニスコート' not in line:
                        current_park = park_name
                        break

            date_match = re.search(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日\s*\((.)\)', line)
            if date_match:
                self._process_court_data(current_park, current_date, current_dow, current_court, slot_values, slot_type)
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
                self._process_court_data(current_park, current_date, current_dow, current_court, slot_values, slot_type)
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
                    self._process_court_data(current_park, current_date, current_dow, current_court, slot_values, slot_type)
                    slot_values = []
                    current_court = None

        self._process_court_data(current_park, current_date, current_dow, current_court, slot_values, slot_type)

    def _process_court_data(self, park_name, date, dow, court, slot_values, slot_type: str = "normal"):
        if not date or not court or not slot_values:
            return

        if not park_name:
            park_name = "不明な施設"

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
                    court=court, time=time_label, slot_type=slot_type,
                )
                if not any(
                    s.park == slot.park and s.date == slot.date
                    and s.court == slot.court and s.time == slot.time
                    for s in self.results
                ):
                    self.results.append(slot)
                    logger.info("      空き: %s %s(%s) %s %s", park_name, date_str, dow, court, time_label)


def run_scrape(
    parks: list[str] | None = None,
    days_ahead: int | None = None,
    target_dates: list[str] | None = None,
) -> list[dict]:
    """エントリポイント: スクレイプ実行して結果をdict listで返す

    target_dates が指定された場合、該当日のスロットのみ返す (YYYY-MM-DD のリスト)。
    """
    if parks is None:
        parks = config.ALL_PARKS
    if days_ahead is None:
        days_ahead = config.SCRAPE_DAYS_AHEAD

    # target_dates が指定されている場合、必要な日数を自動計算
    if target_dates:
        from datetime import datetime as dt
        today = dt.now().date()
        max_date = max(dt.strptime(d, "%Y-%m-%d").date() for d in target_dates)
        days_ahead = max((max_date - today).days + 1, 1)

    target_set = set(target_dates) if target_dates else None

    checker = TennisChecker()
    results = checker.run(parks, days_ahead, target_dates=target_set)

    # 念のため最終フィルタ
    if target_set:
        results = [s for s in results if s.date in target_set]

    return [asdict(s) for s in results]
