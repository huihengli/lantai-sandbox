"""规则列表。规则是纯函数：只读上下文，不写库。新增规则只需加一个 @rule 函数。"""
from collections.abc import Callable
from decimal import Decimal

from app import config
from app.money import fmt
from app.risk.codes import reason
from app.risk.context import RiskContext

RULES: list[tuple[set[str], Callable[[RiskContext], list[dict]]]] = []


def rule(*op_types: str):
    def register(fn: Callable[[RiskContext], list[dict]]):
        RULES.append((set(op_types), fn))
        return fn
    return register


@rule("transfer")
def blacklist(c: RiskContext) -> list[dict]:
    return [reason("BLACKLIST_HIT")] if c.blacklist_hit else []


@rule("transfer")
def single_limit(c: RiskContext) -> list[dict]:
    if c.amount_cents > c.account.single_limit_cents:
        return [reason("SINGLE_LIMIT_EXCEEDED", limit=fmt(c.account.single_limit_cents))]
    return []


@rule("transfer")
def daily_limit(c: RiskContext) -> list[dict]:
    if c.today_out_cents + c.amount_cents > c.account.daily_limit_cents:
        return [reason("DAILY_LIMIT_EXCEEDED", limit=fmt(c.account.daily_limit_cents),
                       used=fmt(c.today_out_cents))]
    return []


@rule("transfer")
def new_payee(c: RiskContext) -> list[dict]:
    return [reason("NEW_PAYEE")] if c.is_new_payee else []


@rule("transfer")
def payee_name_mismatch(c: RiskContext) -> list[dict]:
    return [reason("PAYEE_NAME_MISMATCH")] if c.name_mismatch else []


@rule("transfer", "deposit_create")
def large_amount(c: RiskContext) -> list[dict]:
    if c.amount_cents >= config.LARGE_AMOUNT_CENTS:
        return [reason("LARGE_AMOUNT", threshold=fmt(config.LARGE_AMOUNT_CENTS))]
    return []


@rule("transfer")
def high_balance_ratio(c: RiskContext) -> list[dict]:
    ratio = Decimal(config.HIGH_BALANCE_RATIO)
    if Decimal(c.amount_cents) > Decimal(c.account.balance_cents) * ratio:
        return [reason("HIGH_BALANCE_RATIO", ratio=f"{int(ratio * 100)}%")]
    return []


@rule("transfer")
def rapid_repeat(c: RiskContext) -> list[dict]:
    if c.recent_out_count + 1 >= config.RAPID_COUNT:  # +1 为本笔
        return [reason("RAPID_REPEAT", window=str(config.RAPID_WINDOW_SECONDS // 60))]
    return []


@rule("transfer")
def night(c: RiskContext) -> list[dict]:
    if config.NIGHT_START_HOUR <= c.local_now.hour < config.NIGHT_END_HOUR:
        return [reason("NIGHT_TRANSACTION")]
    return []


@rule("transfer", "deposit_create")
def autopay_at_risk(c: RiskContext) -> list[dict]:
    due = sum(a for _, a, _ in c.autopays)
    if due and c.account.balance_cents - c.amount_cents - c.fee_cents < due:
        items = "、".join(f"{m} {fmt(a)} 元 {d}" for m, a, d in c.autopays)
        return [reason("AUTOPAY_AT_RISK", days=str(config.AUTOPAY_LOOKAHEAD_DAYS), items=items)]
    return []


@rule("transfer")
def cross_bank_fee(c: RiskContext) -> list[dict]:
    return [reason("CROSS_BANK_FEE", fee=fmt(c.fee_cents))] if c.cross_bank else []


@rule("deposit_early_withdraw")
def early_withdraw_loss(c: RiskContext) -> list[dict]:
    e = c.early
    return [reason("EARLY_WITHDRAW_LOSS", loss=fmt(e["loss"]), full=fmt(e["full"]), early=fmt(e["early"]))]
