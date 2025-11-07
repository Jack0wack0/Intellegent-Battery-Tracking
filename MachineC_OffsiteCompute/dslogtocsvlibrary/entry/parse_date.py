from pytz import timezone
from datetime import datetime, timedelta

UINT64_MAX = (1 << 64) - 1


def parse_date(unix_time: float, offset: int) -> datetime:
    epoch = datetime(1904, 1, 1, 0, 0, 0, 0, timezone("UTC"))
    date = epoch + timedelta(seconds=unix_time)
    date += timedelta(seconds=offset / UINT64_MAX)
    return date
