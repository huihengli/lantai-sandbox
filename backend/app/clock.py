"""可控时钟：库内一律存 naive UTC，输出时按配置时区格式化。"""
from datetime import datetime, timedelta, timezone

from app.config import TZ

_offset = timedelta(0)


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) + _offset


def reset() -> None:
    global _offset
    _offset = timedelta(0)


def advance(seconds: float) -> None:
    global _offset
    _offset += timedelta(seconds=seconds)


def set_time(target: datetime) -> None:
    """让 now() 此刻等于 target（带时区的按其时区换算，不带时区的视为澜台本地时间）。"""
    global _offset
    if target.tzinfo is None:
        utc = target - TZ
    else:
        utc = target.astimezone(timezone.utc).replace(tzinfo=None)
    _offset = utc - datetime.now(timezone.utc).replace(tzinfo=None)


def local(dt: datetime) -> datetime:
    return dt + TZ


def local_day_start_utc(dt: datetime) -> datetime:
    return local(dt).replace(hour=0, minute=0, second=0, microsecond=0) - TZ


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt + TZ).replace(tzinfo=timezone(TZ), microsecond=0).isoformat()
