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


@rule("transfer", "deposit_create", "merchant_payment", "wealth_subscribe")
def large_amount(c: RiskContext) -> list[dict]:
    if c.amount_cents >= config.LARGE_AMOUNT_CENTS:
        return [reason("LARGE_AMOUNT", threshold=fmt(config.LARGE_AMOUNT_CENTS))]
    return []


@rule("transfer")
def high_balance_ratio(c: RiskContext) -> list[dict]:
    ratio = Decimal(config.HIGH_BALANCE_RATIO)
    if Decimal(c.amount_cents) > Decimal(c.account.balance_cents - c.held_cents) * ratio:
        return [reason("HIGH_BALANCE_RATIO", ratio=f"{int(ratio * 100)}%")]
    return []


@rule("transfer")
def rapid_repeat(c: RiskContext) -> list[dict]:
    if c.recent_out_count + 1 >= config.RAPID_COUNT:  # +1 为本笔
        return [reason("RAPID_REPEAT", window=str(config.RAPID_WINDOW_SECONDS // 60))]
    return []


@rule("transfer", "merchant_payment")
def night(c: RiskContext) -> list[dict]:
    if config.NIGHT_START_HOUR <= c.local_now.hour < config.NIGHT_END_HOUR:
        return [reason("NIGHT_TRANSACTION")]
    return []


@rule("transfer", "deposit_create", "merchant_payment", "wealth_subscribe")
def autopay_at_risk(c: RiskContext) -> list[dict]:
    due = sum(a for _, a, _ in c.autopays)
    if due and c.account.balance_cents - c.held_cents - c.amount_cents - c.fee_cents < due:
        items = "、".join(f"{m} {fmt(a)} 元 {d}" for m, a, d in c.autopays)
        return [reason("AUTOPAY_AT_RISK", days=str(config.AUTOPAY_LOOKAHEAD_DAYS), items=items)]
    return []


@rule("transfer")
def cross_bank_fee(c: RiskContext) -> list[dict]:
    return [reason("CROSS_BANK_FEE", fee=fmt(c.fee_cents))] if c.cross_bank else []


@rule("card_apply")
def card_apply(c: RiskContext) -> list[dict]:
    return [reason("CARD_APPLY")]


@rule("card_unfreeze")
def card_unfreeze(c: RiskContext) -> list[dict]:
    return [reason("CARD_UNFREEZE")]


@rule("card_reissue")
def card_reissue(c: RiskContext) -> list[dict]:
    return [reason("CARD_REISSUE")]


@rule("card_controls")
def card_controls(c: RiskContext) -> list[dict]:
    names = {"online": "线上支付", "overseas": "境外交易", "atm": "ATM 取现"}
    loosen = c.change.get("loosen", [])
    out = [reason("CONTROL_OVERSEAS_ON")] if "overseas" in loosen else []
    rest = [names[k] for k in loosen if k != "overseas"]
    return out + ([reason("CONTROL_LOOSEN", items="、".join(rest))] if rest else [])


@rule("card_limits", "account_limits")
def limit_raise(c: RiskContext) -> list[dict]:
    if c.change.get("raise"):
        return [reason("LIMIT_RAISE", old=c.change["old"], new=c.change["new"])]
    return []


@rule("mandate_cancel")
def mandate_cancel(c: RiskContext) -> list[dict]:
    return [reason("MANDATE_CANCEL", merchant=c.change["merchant"], date=c.change["date"])]


@rule("hold_release")
def hold_release(c: RiskContext) -> list[dict]:
    return [reason("HOLD_RELEASE", amount=c.change["amount"], purpose=c.change["purpose"])]


@rule("merchant_payment")
def merchant_payment(c: RiskContext) -> list[dict]:
    card, m = c.change["card"], c.change["merchant"]
    out: list[dict] = []
    if card["status"] != "active":
        out.append(reason("CARD_NOT_USABLE", status=card["status_text"]))
    if c.change["channel"] == "online" and not card["online"]:
        out.append(reason("CONTROL_DISABLED", name="线上支付"))
    if m["overseas"] and not card["overseas"]:
        out.append(reason("CONTROL_DISABLED", name="境外交易"))
    used = c.change["card_today_cents"]
    if c.amount_cents > card["single"] or used + c.amount_cents > card["daily"]:
        out.append(reason("CARD_LIMIT_EXCEEDED", single=fmt(card["single"]), daily=fmt(card["daily"]), used=fmt(used)))
    if m["status"] == "risky":
        out.append(reason("MERCHANT_RISKY"))
    if m["overseas"]:
        out.append(reason("OVERSEAS_PAYMENT"))
    if c.change["first_time"]:
        out.append(reason("NEW_MERCHANT"))
    return out


@rule("wealth_subscribe")
def wealth_subscribe(c: RiskContext) -> list[dict]:
    ch, prod = c.change, c.change["product"]
    out: list[dict] = []
    if ch["user_level"] is None:
        out.append(reason("RISK_PROFILE_MISSING", status="尚未完成风险测评" if ch["level_status"] == "none" else "风险测评已过期（有效期 12 个月）"))
    else:
        gap = prod["risk_level"] - ch["user_level"]
        names = dict(product=f"R{prod['risk_level']}", user=f"R{ch['user_level']}（{ch['user_label']}）")
        if gap >= 2:
            out.append(reason("RISK_LEVEL_FORBIDDEN", **names))
        elif gap == 1:
            out.append(reason("RISK_LEVEL_MISMATCH", **names))
    if prod["risk_level"] >= 2:
        out.append(reason("NAV_RISK_NOTICE"))
    return out


@rule("wealth_redeem")
def wealth_redeem(c: RiskContext) -> list[dict]:
    return [reason("REDEEM_LOSS", loss=c.change["pnl"])] if c.change.get("pnl") else []


@rule("deposit_early_withdraw")
def early_withdraw_loss(c: RiskContext) -> list[dict]:
    e = c.early
    return [reason("EARLY_WITHDRAW_LOSS", loss=fmt(e["loss"]), full=fmt(e["full"]), early=fmt(e["early"]))]
