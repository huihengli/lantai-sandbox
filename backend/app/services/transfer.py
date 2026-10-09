"""转账：规范化 → 计划（校验 + 风控）→ 执行。"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, config
from app.errors import LantaiError
from app.models import HOME_BANK, Account, Blacklist, Payee, User
from app.money import fmt, mask, new_id, parse_amount, round_cents
from app.risk import engine
from app.services import account as acct
from app.services.plan import Plan


def fee_for(bank_code: str, amount_cents: int) -> int:
    if bank_code == HOME_BANK:
        return 0
    fee = round_cents(Decimal(amount_cents) * Decimal(config.CROSS_BANK_FEE_RATE))
    return min(max(fee, config.CROSS_BANK_FEE_MIN_CENTS), config.CROSS_BANK_FEE_MAX_CENTS)


def normalize(db: Session, user: User, body) -> dict:
    if body.currency != "CNY":
        raise LantaiError("CURRENCY_UNSUPPORTED", "仅支持 CNY")
    amount = parse_amount(body.amount)
    row = None
    if body.payee_id:
        row = db.get(Payee, body.payee_id)
        if row is None or row.user_id != user.id or row.status != "active":
            raise LantaiError("PAYEE_NOT_FOUND", "收款人不存在")
    else:
        if not (body.payee_account_no and body.payee_name):
            raise LantaiError("PAYEE_NOT_FOUND", "需提供 payee_id，或 payee_account_no + payee_name")
        bank_code = body.bank_code or HOME_BANK
        row = db.scalar(select(Payee).where(Payee.user_id == user.id, Payee.account_no == body.payee_account_no,
                                            Payee.bank_code == bank_code, Payee.status == "active"))
        if row is None:
            payee = {"payee_id": None, "account_no": body.payee_account_no, "name": body.payee_name,
                     "bank_code": bank_code,
                     "bank_name": "澜台" if bank_code == HOME_BANK else (body.bank_name or "他行")}
    if row is not None:
        payee = {"payee_id": row.id, "account_no": row.account_no, "name": row.name,
                 "bank_code": row.bank_code, "bank_name": row.bank_name}
    return {"from_account_id": body.from_account_id, "amount_cents": amount, "currency": "CNY",
            "memo": body.memo, "payee": payee}


def build_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    payee = params["payee"]
    amount = params["amount_cents"]
    bank = payee["bank_code"]
    fee = fee_for(bank, amount)

    target = None
    if bank == HOME_BANK:
        target = db.scalar(select(Account).where(Account.account_no == payee["account_no"],
                                                 Account.bank_code == HOME_BANK))
        if target is None or target.status != "active":
            raise LantaiError("PAYEE_NOT_FOUND", "收款账户不存在或不可用")
    if lock:
        acct.lock_accounts(db, *[i for i in (params["from_account_id"], target.id if target else None) if i])
    acc = acct.get_owned_account(db, user.id, params["from_account_id"])
    if target is not None and target.id == acc.id:
        raise LantaiError("SAME_ACCOUNT", "不能转给同一账户")
    if acc.balance_cents < amount + fee:
        raise LantaiError("INSUFFICIENT_BALANCE", "余额不足", {"balance": fmt(acc.balance_cents)})

    own_target = target is not None and target.user_id == user.id
    payee_row = db.get(Payee, payee["payee_id"]) if payee["payee_id"] else None
    is_new = not own_target and (payee_row is None or payee_row.first_paid_at is None)
    name_mismatch = (target is not None and not own_target and payee_row is None
                     and target.user.name != payee["name"])
    hit = db.scalar(select(Blacklist.id).where(Blacklist.account_no == payee["account_no"],
                                               Blacklist.bank_code == bank)) is not None

    rctx = engine.build_context(db, user.id, acc, "transfer", amount, now, fee_cents=fee,
                                is_new_payee=is_new, blacklist_hit=hit, name_mismatch=name_mismatch,
                                cross_bank=bank != HOME_BANK)
    summary = {
        "from": f"{acct.TYPE_LABEL.get(acc.type, acc.type)} {mask(acc.account_no)}",
        "to": f"{payee['name']} {mask(payee['account_no'])}", "bank": payee["bank_name"],
        "amount": fmt(amount), "fee": fmt(fee), "total_debit": fmt(amount + fee),
        "balance_after": fmt(acc.balance_cents - amount - fee), "memo": params.get("memo"),
    }
    return Plan("transfer", params, summary, engine.evaluate(rctx),
                {"account": acc, "target": target, "payee_row": payee_row, "fee": fee})


def execute(db: Session, op, plan: Plan, now) -> dict:
    p = plan.params
    payee = p["payee"]
    acc, target, payee_row, fee = (plan.data[k] for k in ("account", "target", "payee_row", "fee"))
    amount = p["amount_cents"]

    acct.debit(db, acc, amount + fee)
    txn = acct.add_txn(db, acc, "out", "transfer", amount, now, fee=fee, counterparty=payee["name"],
                       counterparty_masked=mask(payee["account_no"]), memo=p.get("memo"), operation_id=op.id)
    if target is not None:
        acct.credit(db, target, amount)
        acct.add_txn(db, target, "in", "transfer", amount, now, counterparty=acc.user.name,
                     counterparty_masked=mask(acc.account_no), memo=p.get("memo"), operation_id=op.id)

    own_target = target is not None and target.user_id == acc.user_id
    if payee_row is not None:
        payee_row.first_paid_at = payee_row.first_paid_at or now
    elif not own_target:
        db.add(Payee(id=new_id("pye"), user_id=acc.user_id, name=payee["name"],
                     account_no=payee["account_no"], bank_code=payee["bank_code"],
                     bank_name=payee["bank_name"], first_paid_at=now))
    return {"transaction_id": txn.id, "balance_after": fmt(acc.balance_cents), "fee": fmt(fee),
            "executed_at": clock.iso(now)}
