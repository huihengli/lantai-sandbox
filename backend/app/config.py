"""澜台全部可配置项（环境变量可覆盖）。"""
import os
from datetime import timedelta


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _parse_offset(value: str) -> timedelta:
    sign = -1 if value.startswith("-") else 1
    hours, minutes = value.lstrip("+-").split(":")
    return sign * timedelta(hours=int(hours), minutes=int(minutes))


DATABASE_URL = _env("DATABASE_URL", "sqlite:///./data/lantai.db")
PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "http://localhost:8001")
# 前端地址：confirm_url 指向它。开发时 Vite 在 5173，设为 http://localhost:5173；默认由后端托管构建产物。
FRONTEND_BASE_URL = _env("FRONTEND_BASE_URL", PUBLIC_BASE_URL)
# 前端构建产物目录（pnpm build 后的 dist）；不存在则不托管。
FRONTEND_DIST = _env("FRONTEND_DIST", os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
ADMIN_KEY = _env("ADMIN_KEY", "dev-admin-key")  # 仅本地演示

TIMEZONE_OFFSET = _env("TIMEZONE_OFFSET", "+01:00")
TZ = _parse_offset(TIMEZONE_OFFSET)

OPERATION_TTL_SECONDS = 300
OTP_FIXED_CODE: str | None = _env("OTP_FIXED_CODE", "123456") or None  # 空串=随机
OTP_MAX_ATTEMPTS = 3
AGENT_TOKEN_TTL_SECONDS = 1800
AGENT_TOKEN_MAX_TTL_SECONDS = 3600
USER_SESSION_TTL_SECONDS = 1800
IDEMPOTENCY_TTL_SECONDS = 86400

# 风控阈值（单位：分）
LARGE_AMOUNT_CENTS = 5_000_000
HIGH_BALANCE_RATIO = "0.80"
RAPID_WINDOW_SECONDS = 600
RAPID_COUNT = 3
NIGHT_START_HOUR, NIGHT_END_HOUR = 0, 6
AUTOPAY_LOOKAHEAD_DAYS = 7

# 手续费（跨行）
CROSS_BANK_FEE_RATE = "0.001"
CROSS_BANK_FEE_MIN_CENTS = 200
CROSS_BANK_FEE_MAX_CENTS = 2000

# 默认账户限额
DEFAULT_SINGLE_LIMIT_CENTS = 5_000_000
DEFAULT_DAILY_LIMIT_CENTS = 10_000_000

HOME_BANK = "LANTAI"
