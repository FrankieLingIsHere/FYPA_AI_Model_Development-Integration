# Readability: Module overview: keep the main setup, workflow, and fallback paths easy to scan.
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Section: run the get timezone info workflow with clear inputs and outputs.
def get_timezone_info():
    """Returns the configured ZoneInfo object from .env or defaults to MYT."""
    # Prepare tz str for the next step.
    tz_str = os.getenv("TIMEZONE", "Asia/Kuala_Lumpur")
    try:
        # Return the prepared result to the caller.
        return ZoneInfo(tz_str)
    except Exception:
        return ZoneInfo("Asia/Kuala_Lumpur")

# Section: run the get local time workflow with clear inputs and outputs.
def get_local_time():
    """Returns the current local time as a timezone-aware datetime."""
    return datetime.now(get_timezone_info())

# Section: run the to local time workflow with clear inputs and outputs.
def to_local_time(dt):
    """Converts a naive or aware datetime to the local timezone."""
    # Choose the correct branch before the workflow continues.
    if dt.tzinfo is None:
        # Assume naive datetimes are UTC
        # Prepare dt for the next step.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_timezone_info())
