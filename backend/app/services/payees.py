"""收款人管理与手机号解析。"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import clock
from app.errors import LantaiError
from app.models import HOME_BANK, Account, Blacklist, Payee, User
from app.money import mask, new_id
from app.security import ratelimit
from app.services import audit

RESOLVE_LIMIT, RESOLVE_WINDOW = 10, 600  # 每用户 10 分钟最多 10 次


def view(p: Payee) -> dict:
    return {"id": p.id, "name": p.name, "alias": p.alias, "account_no_masked": mask(p.account_no),
            "bank": p.bank_name, "bank_code": p.bank_code, "ever_paid": p.first_paid_at is not None,
            "first_paid_at": clock.iso(p.first_paid_at)}


def mask_name(name: str) -> str:
    return name[:1] + "*" * max(len(name) - 1, 1)


def list_payees(db: Session, user_id: str, q: str | None = None) -> list[Payee]:
    stmt = select(Payee).where(Payee.user_id == user_id, Payee.status == "active")
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Payee.name.ilike(like), Payee.alias.ilike(like), Payee.account_no.like(f"%{q}")))
    return list(db.scalars(stmt.order_by(Payee.name)))


def _owned(db: Session, user_id: str, payee_id: str) -> Payee:
    p = db.get(Payee, payee_id)
    if p is None or p.user_id != user_id or p.status != "active":
        raise LantaiError("PAYEE_NOT_FOUND", "收款人不存在")
    return p


def add(ctx: audit.Ctx, user: User, body) -> dict:
    db = ctx.db
    bank = body.bank_code or HOME_BANK
    if bank == HOME_BANK:
        target = db.scalar(select(Account).where(Account.account_no == body.account_no, Account.bank_code == HOME_BANK))
        if target is None or target.status != "active":
            raise LantaiError("PAYEE_NOT_FOUND", "收款账户不存在或不可用")
        if target.user_id == user.id:
            raise LantaiError("SAME_ACCOUNT", "本人账户无需添加为收款人")
        if target.user.name != body.name:
            raise LantaiError("PAYEE_NAME_MISMATCH", "户名与该账户实际户名不一致")
        bank_name = "澜台"
    else:
        bank_name = body.bank_name or "他行"
    if db.scalar(select(Blacklist.id).where(Blacklist.account_no == body.account_no, Blacklist.bank_code == bank)):
        raise LantaiError("RISK_BLOCKED", "该账户已被列入涉诈风险名单，无法添加")

    row = db.scalar(select(Payee).where(Payee.user_id == user.id, Payee.account_no == body.account_no,
                                        Payee.bank_code == bank))
    existed = row is not None and row.status == "active"
    if row is None:
        row = Payee(id=new_id("pye"), user_id=user.id, name=body.name, account_no=body.account_no,
                    bank_code=bank, bank_name=bank_name)
        db.add(row)
    row.status, row.name = "active", body.name
    if body.alias is not None:
        row.alias = body.alias
    audit.log(ctx, "payee_add", detail={"payee": mask(body.account_no), "name": body.name})
    return {**view(row), "already_exists": existed}


def update_alias(ctx: audit.Ctx, user: User, payee_id: str, alias: str | None) -> dict:
    p = _owned(ctx.db, user.id, payee_id)
    p.alias = alias
    audit.log(ctx, "payee_update", detail={"payee_id": p.id})
    return view(p)


def remove(ctx: audit.Ctx, user: User, payee_id: str) -> dict:
    p = _owned(ctx.db, user.id, payee_id)
    p.status = "deleted"  # 软删除，保留历史转账关联
    audit.log(ctx, "payee_remove", detail={"payee_id": p.id})
    return {"id": p.id, "deleted": True}


def _primary_account(db: Session, phone: str) -> Account:
    owner = db.scalar(select(User).where(User.phone == phone, User.status == "active"))
    acc = None
    if owner is not None:
        accs = list(db.scalars(select(Account).where(Account.user_id == owner.id, Account.status == "active")
                               .order_by(Account.id)))
        acc = next((a for a in accs if a.type == "demand"), accs[0] if accs else None)
    if acc is None:
        raise LantaiError("PAYEE_NOT_FOUND", "该手机号未开通澜台账户")
    return acc


def account_no_by_phone(user: User, db: Session, phone: str) -> str:
    ratelimit.check(f"phone:{user.id}", RESOLVE_LIMIT, RESOLVE_WINDOW)
    return _primary_account(db, phone).account_no


def resolve_phone(db: Session, user: User, phone: str) -> dict:
    """只返回脱敏户名，不泄露账号；限频防枚举。"""
    ratelimit.check(f"phone:{user.id}", RESOLVE_LIMIT, RESOLVE_WINDOW)
    acc = _primary_account(db, phone)
    return {"phone_masked": phone[:3] + "****" + phone[-4:], "name_masked": mask_name(acc.user.name),
            "bank": "澜台", "bank_code": HOME_BANK, "hint": "转账时需填写完整户名以核验收款人"}
