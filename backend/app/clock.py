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


def local_day_end_utc(dt: datetime) -> datetime:
    """当日（本地自然日）的结束边界，与 local_day_start_utc 配对使用。

    日累计类求和必须同时带上下界：演示时钟可以往回拨，之前按"未来日期"记账的流水仍然满足
    `>= 当日 00:00`，没有上界就会被算进今天。实测：11-02 转了 7 笔共 625 元，把时钟拨回
    10-31 后余额接口仍报 today_transferred_out=625，而当日流水只有 5 元。
    """
    return local_day_start_utc(dt) + timedelta(days=1)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt + TZ).replace(tzinfo=timezone(TZ), microsecond=0).isoformat()
