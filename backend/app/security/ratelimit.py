"""进程内滑动窗口限频（演示用；多实例部署需换成共享存储）。"""
from app import clock
from app.errors import LantaiError

_hits: dict[str, list[float]] = {}


def _ts() -> float:
    return clock.now().timestamp()


def check(key: str, limit: int, window_seconds: int) -> None:
    now = _ts()
    recent = [t for t in _hits.get(key, []) if now - t < window_seconds]
    if len(recent) >= limit:
        _hits[key] = recent
        raise LantaiError("RATE_LIMITED", "操作过于频繁，请稍后再试", {"retry_after_seconds": window_seconds})
    recent.append(now)
    _hits[key] = recent


def reset() -> None:
    _hits.clear()
