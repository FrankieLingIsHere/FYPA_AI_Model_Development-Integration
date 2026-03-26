import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def get_timezone_info():
    """Returns the configured ZoneInfo object from .env or defaults to MYT."""
    tz_str = os.getenv("TIMEZONE", "Asia/Kuala_Lumpur")
    try:
        return ZoneInfo(tz_str)
    except Exception:
        return ZoneInfo("Asia/Kuala_Lumpur")

def get_local_time():
    """Returns the current local time as a timezone-aware datetime."""
    return datetime.now(get_timezone_info())

def to_local_time(dt):
    """Converts a naive or aware datetime to the local timezone."""
    if dt.tzinfo is None:
        # Assume naive datetimes are UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_timezone_info())
