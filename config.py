SCRAPE_INTERVAL_HOURS = 6
SCRAPE_DAYS_AHEAD = 14
DB_PATH = "data/tennis.db"

BASE_URL = "https://www.shisetsu.city.yokohama.lg.jp/user/Home"

DAY_NAMES = ["月", "火", "水", "木", "金", "土", "日"]
WEEKDAY_MIN_HOUR = 19
WEEKEND_MIN_HOUR = 0
BATCH_SIZE = 20

PARKS = {
    "三ツ沢公園":   {"search": "三ツ沢",   "short": "三ツ沢"},
    "新横浜公園":   {"search": "新横浜公園", "short": "新横浜"},
    "入船公園":     {"search": "入船",     "short": "入船"},
    "清水ヶ丘公園": {"search": "清水ヶ丘",  "short": "清水ヶ丘"},
}
ALL_PARKS = list(PARKS.keys())
