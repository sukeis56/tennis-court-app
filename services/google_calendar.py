from datetime import datetime
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import logging

logger = logging.getLogger(__name__)


def list_events_for_month(creds: Credentials, year: int, month: int) -> list[dict]:
    """指定月の全カレンダーイベントを取得"""
    try:
        service = build("calendar", "v3", credentials=creds)
        time_min = datetime(year, month, 1).isoformat() + "Z"
        if month == 12:
            time_max = datetime(year + 1, 1, 1).isoformat() + "Z"
        else:
            time_max = datetime(year, month + 1, 1).isoformat() + "Z"

        cal_list = service.calendarList().list().execute()
        calendars = [
            {"id": c["id"], "summary": c.get("summary", "")}
            for c in cal_list.get("items", [])
        ]

        events = []
        for cal in calendars:
            try:
                result = service.events().list(
                    calendarId=cal["id"],
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=250,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()

                for item in result.get("items", []):
                    start = item["start"].get("dateTime", item["start"].get("date", ""))
                    date_str = start[:10]
                    time_str = start[11:16] if "T" in start else ""

                    events.append({
                        "summary": item.get("summary", "(無題)"),
                        "date": date_str,
                        "start_time": time_str,
                        "calendar_name": cal["summary"],
                    })
            except Exception as e:
                logger.warning("Failed to fetch from %s: %s", cal["summary"], e)

        events.sort(key=lambda e: (e["date"], e["start_time"]))
        return events
    except Exception as e:
        logger.error("Failed to fetch calendar events: %s", e)
        return []
