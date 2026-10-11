"""账户读写原语：归属校验、条件扣款/入账、流水。"""
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app import clock
from app.errors import LantaiError
from app.models import Account, Hold, Transaction
from app.money import new_id

TYPE_LABEL = {"demand": "活期账户", "savings": "储蓄账户"}


def get_owned_account(db: Session, user_id: str, account_id: str, lock: bool = False,
                      require_active: bool = True) -> Account:
    stmt = select(Account).where(Account.id == account_id)
    if lock:
        stmt = stmt.with_for_update()
    acc = db.scalar(stmt)
    if acc is None or acc.user_id != user_id:
        raise LantaiError("RESOURCE_NOT_OWNED", "账户不存在")
    if require_active:
        if acc.status == "frozen":
            raise LantaiError("ACCOUNT_FROZEN", "账户已冻结")
        if acc.status == "closed":
            raise LantaiError("ACCOUNT_CLOSED", "账户已销户")
    return acc


def lock_accounts(db: Session, *account_ids: str) -> None:
    """按 id 排序加锁，避免互转时死锁（SQLite 下 FOR UPDATE 被忽略）。"""
    db.execute(select(Account.id).where(Account.id.in_(account_ids)).order_by(Account.id).with_for_update())


def held_amount(db: Session, account_id: str) -> int:
    """当前生效的预留总额（未到期的 active 预留）。"""
    return int(db.scalar(select(func.coalesce(func.sum(Hold.amount_cents), 0)).where(
        Hold.account_id == account_id, Hold.status == "active",
        or_(Hold.expires_at.is_(None), Hold.expires_at > clock.now()))))


def available_cents(db: Session, acc: Account) -> int:
    return acc.balance_cents - held_amount(db, acc.id)


def debit(db: Session, acc: Account, cents: int) -> None:
    """条件扣款：可用余额（余额 − 预留）必须足够。"""
    held = held_amount(db, acc.id)
    res = db.execute(update(Account).where(Account.id == acc.id, Account.balance_cents >= cents + held)
                     .values(balance_cents=Account.balance_cents - cents)
                     .execution_options(synchronize_session=False))
    if res.rowcount != 1:
        raise LantaiError("INSUFFICIENT_BALANCE", "可用余额不足" if held else "余额不足", {"held": held / 100})
    db.refresh(acc)


def credit(db: Session, acc: Account, cents: int) -> None:
    db.execute(update(Account).where(Account.id == acc.id)
               .values(balance_cents=Account.balance_cents + cents)
               .execution_options(synchronize_session=False))
    db.refresh(acc)


def add_txn(db: Session, acc: Account, direction: str, category: str, amount: int, now: datetime,
            fee: int = 0, counterparty: str | None = None, counterparty_masked: str | None = None,
            memo: str | None = None, operation_id: str | None = None,
            merchant_category: str | None = None, card_id: str | None = None) -> Transaction:
    txn = Transaction(
        id=new_id("txn"), account_id=acc.id, direction=direction, category=category,
        amount_cents=amount, fee_cents=fee, balance_after_cents=acc.balance_cents,
        counterparty_name=counterparty, counterparty_account_masked=counterparty_masked,
        merchant_category=merchant_category, card_id=card_id, memo=memo, operation_id=operation_id, occurred_at=now)
    db.add(txn)
    return txn
