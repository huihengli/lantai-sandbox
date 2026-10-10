from dataclasses import dataclass, field
from datetime import datetime

from app.models import Account


@dataclass
class RiskContext:
    op_type: str  # transfer / deposit_create / deposit_early_withdraw
    account: Account
    amount_cents: int
    now: datetime  # naive UTC
    local_now: datetime
    fee_cents: int = 0
    held_cents: int = 0  # 已预留金额，可用余额 = 余额 - 预留
    today_out_cents: int = 0
    recent_out_count: int = 0
    autopays: list[tuple[str, int, str]] = field(default_factory=list)  # (商户, 金额, 日期)
    is_new_payee: bool = False
    blacklist_hit: bool = False
    name_mismatch: bool = False
    cross_bank: bool = False
    early: dict = field(default_factory=dict)  # 提前支取：loss / full / early（单位分）
    change: dict = field(default_factory=dict)  # 卡片/额度类操作的变更描述
