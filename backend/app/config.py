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
# 前端地址：confirm_url 指向它。开发时 Vite 在 5172，设为 http://localhost:5172；默认由后端托管构建产物。
FRONTEND_BASE_URL = _env("FRONTEND_BASE_URL", PUBLIC_BASE_URL)
# 前端构建产物目录（pnpm build 后的 dist）；不存在则不托管。
FRONTEND_DIST = _env("FRONTEND_DIST", os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
# 运行环境：dev（默认，本地演示）/ prod。prod 下 /admin 默认关闭，且必须显式设置强随机 ADMIN_KEY
APP_ENV = _env("APP_ENV", "dev").lower()
ADMIN_KEY = _env("ADMIN_KEY", "dev-admin-key")  # 仅本地演示
ADMIN_ENABLED = _env("ADMIN_ENABLED", "1" if APP_ENV != "prod" else "0") == "1"
ADMIN_KEY_MIN_LENGTH = 24
DOCS_ENABLED = _env("DOCS_ENABLED", "1" if APP_ENV != "prod" else "0") == "1"
# 数据库结构落后于代码时：1=启动时清空并重建（开发用）；默认拒绝启动并提示
RESET_DB_ON_START = _env("RESET_DB_ON_START", "") == "1"

TIMEZONE_OFFSET = _env("TIMEZONE_OFFSET", "+01:00")
TZ = _parse_offset(TIMEZONE_OFFSET)

OPERATION_TTL_SECONDS = 300
# 演示模式：模拟短信可经 /ui/.../otp-hint 取码、默认固定码；prod 下关闭，验证码随机且不落明文
OTP_DEMO_MODE = _env("OTP_DEMO_MODE", "1" if APP_ENV != "prod" else "0") == "1"
OTP_FIXED_CODE: str | None = (_env("OTP_FIXED_CODE", "123456" if OTP_DEMO_MODE else "") or None) if OTP_DEMO_MODE else None
OTP_PEPPER = _env("OTP_PEPPER", "") or os.urandom(16).hex()  # 验证码哈希密钥；多实例需显式设置同一值
OTP_USER_FAIL_LIMIT, OTP_USER_FAIL_WINDOW = 10, 600  # 每用户 10 分钟内 OTP 错误上限（与单操作 3 次互补）
OTP_MAX_ATTEMPTS = 3
AGENT_TOKEN_TTL_SECONDS = 1800
AGENT_TOKEN_MAX_TTL_SECONDS = 3600
AGENT_TOKEN_LONG_TTL_SECONDS = 7 * 24 * 3600  # 长期凭证（用户显式勾选 long_lived）的默认与上限：168 小时
USER_SESSION_TTL_SECONDS = 1800
# 登录防暴破：窗口内同一手机号 / 同一来源 IP 的失败次数上限
# 通用限频 / 资源上限
TOKEN_RATE_LIMIT, TOKEN_RATE_WINDOW = 300, 60  # 每令牌每分钟请求数
PREPARE_PROBE_LIMIT, PREPARE_PROBE_WINDOW = 60, 600  # 每用户 10 分钟内转账预处理/预检次数
PAYEE_ADD_LIMIT, PAYEE_ADD_WINDOW = 20, 600  # 每用户 10 分钟内添加收款人次数
MAX_ACTIVE_OPERATIONS = 20  # 每用户同时待处理的操作上限
MAX_BODY_BYTES = 64 * 1024
EVENT_RETENTION_DAYS = 30
# 种子数据口令（仅演示）
SEED_PASSWORD = _env("SEED_PASSWORD", "Lantai@2026")
LOGIN_FAIL_LIMIT_PHONE = 5
LOGIN_FAIL_LIMIT_IP = 20
LOGIN_FAIL_WINDOW_SECONDS = 300
# 口令哈希 PBKDF2-HMAC-SHA256 迭代次数（测试可用环境变量调低）
PASSWORD_ITERATIONS = int(_env("PASSWORD_ITERATIONS", "600000"))
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

# 卡片与额度
CARD_DEFAULT_SINGLE_CENTS = 2_000_000
CARD_DEFAULT_DAILY_CENTS = 5_000_000
CARD_MAX_SINGLE_CENTS = 20_000_000
CARD_MAX_DAILY_CENTS = 50_000_000
ACCOUNT_MAX_SINGLE_CENTS = 20_000_000  # 账户转账额度调整上限
ACCOUNT_MAX_DAILY_CENTS = 50_000_000
MAX_CARDS_PER_ACCOUNT = 3

# 风险测评
RISK_PROFILE_VALID_DAYS = 365
