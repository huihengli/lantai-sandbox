"""金额工具：库内整数分，接口层字符串。"""
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal

from app.errors import LantaiError

_AMOUNT_RE = re.compile(r"^\d{1,12}(\.\d{1,2})?$")


def parse_amount(value: object) -> int:
    if not isinstance(value, str) or not _AMOUNT_RE.match(value):
        raise LantaiError("AMOUNT_INVALID", "金额格式不合法：需为字符串，最多两位小数")
    cents = int((Decimal(value) * 100).to_integral_value())
    if cents <= 0:
        raise LantaiError("AMOUNT_INVALID", "金额必须大于 0")
    return cents


def fmt(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mask(account_no: str) -> str:
    return "****" + account_no[-4:]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"
