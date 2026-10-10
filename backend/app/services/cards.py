"""卡片与额度。

设计原则：收紧立即生效（冻结、挂失、调低额度、关闭开关，Agent 可直接执行），
放宽需用户确认（解冻、补发、新卡、调高额度、打开开关，走 prepare → 确认/OTP）。
卡片状态只影响卡片渠道（商户支付、ATM），不影响账户间转账。
"""
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, config
from app.errors import LantaiError
from app.models import Account, Card, User
from app.money import fmt, mask, new_id, parse_amount
from app.risk import engine
from app.services import account as acct
from app.services import audit
from app.services.plan import Plan

CONTROLS = {"online": "线上支付", "overseas": "境外交易", "atm": "ATM 取现"}
STATUS_TEXT = {"active": "正常", "frozen": "已冻结", "locked": "已锁定", "lost": "已挂失"}


def view(c: Card) -> dict:
    return {
        "id": c.id, "account_id": c.account_id, "card_no_masked": mask(c.card_no), "type": c.type,
        "status": c.status, "status_text": STATUS_TEXT.get(c.status, c.status),
        "controls": {"online": c.online_enabled, "overseas": c.overseas_enabled, "atm": c.atm_enabled},
        "limits": {"single": fmt(c.single_limit_cents), "daily": fmt(c.daily_limit_cents)},
        "replaced_by": c.replaced_by, "created_at": clock.iso(c.created_at),
    }


def list_cards(db: Session, user_id: str) -> list[Card]:
    return list(db.scalars(select(Card).where(Card.user_id == user_id).order_by(Card.created_at, Card.id)))


def get_owned(db: Session, user_id: str, card_id: str, lock: bool = False) -> Card:
    stmt = select(Card).where(Card.id == card_id)
    c = db.scalar(stmt.with_for_update() if lock else stmt)
    if c is None or c.user_id != user_id:
        raise LantaiError("RESOURCE_NOT_OWNED", "卡片不存在")
    return c


def _set_status(c: Card, status: str) -> None:
    c.status = status
    c.status_changed_at = clock.now()


def _new_card_no(db: Session) -> str:
    while True:
        no = "621790" + "".join(str(secrets.randbelow(10)) for _ in range(10))
        if db.scalar(select(Card.id).where(Card.card_no == no)) is None:
            return no


# ---------------- 直接生效（保护性）----------------
def freeze(ctx: audit.Ctx, user: User, card_id: str) -> dict:
    c = get_owned(ctx.db, user.id, card_id, lock=True)
    if c.status == "frozen":
        return {"card": view(c), "changed": False}
    if c.status != "active":
        raise LantaiError("CARD_STATE_INVALID", f"卡片当前为{STATUS_TEXT[c.status]}，无法冻结")
    _set_status(c, "frozen")
    audit.log(ctx, "card_freeze", detail={"card_id": c.id})
    return {"card": view(c), "changed": True}


def report_loss(ctx: audit.Ctx, user: User, card_id: str) -> dict:
    c = get_owned(ctx.db, user.id, card_id, lock=True)
    if c.status == "lost":
        return {"card": view(c), "changed": False}
    _set_status(c, "lost")
    audit.log(ctx, "card_report_loss", detail={"card_id": c.id})
    return {"card": view(c), "changed": True}


def _confirm_required(what: str, items: list[str], prepare_path: str) -> LantaiError:
    return LantaiError("CONFIRM_REQUIRED", f"{what}属于放宽权限，需走 prepare 并由用户确认",
                       {"items": items, "use": prepare_path})


def tighten_controls(ctx: audit.Ctx, user: User, card_id: str, changes: dict) -> dict:
    c = get_owned(ctx.db, user.id, card_id, lock=True)
    _require_usable(c)
    loosen = [k for k, v in changes.items() if v and not getattr(c, f"{k}_enabled")]
    if loosen:
        raise _confirm_required("打开交易开关", loosen, f"/api/v1/cards/{c.id}/controls/prepare")
    changed = [k for k, v in changes.items() if not v and getattr(c, f"{k}_enabled")]
    for k in changed:
        setattr(c, f"{k}_enabled", False)
    if changed:
        audit.log(ctx, "card_controls_tighten", detail={"card_id": c.id, "closed": changed})
    return {"card": view(c), "changed": bool(changed)}


def lower_limits(ctx: audit.Ctx, user: User, card_id: str, single: int | None, daily: int | None) -> dict:
    c = get_owned(ctx.db, user.id, card_id, lock=True)
    _require_usable(c)
    new_single, new_daily = _resolve_limits(c.single_limit_cents, c.daily_limit_cents, single, daily, "card")
    if new_single > c.single_limit_cents or new_daily > c.daily_limit_cents:
        raise _confirm_required("调高额度", ["single" if new_single > c.single_limit_cents else "daily"],
                                f"/api/v1/cards/{c.id}/limits/prepare")
    changed = (new_single, new_daily) != (c.single_limit_cents, c.daily_limit_cents)
    c.single_limit_cents, c.daily_limit_cents = new_single, new_daily
    if changed:
        audit.log(ctx, "card_limits_lower", detail={"card_id": c.id, "single": fmt(new_single), "daily": fmt(new_daily)})
    return {"card": view(c), "changed": changed}


def lower_account_limits(ctx: audit.Ctx, user: User, account_id: str, single: int | None, daily: int | None) -> dict:
    a = acct.get_owned_account(ctx.db, user.id, account_id, lock=True, require_active=False)
    new_single, new_daily = _resolve_limits(a.single_limit_cents, a.daily_limit_cents, single, daily, "account")
    if new_single > a.single_limit_cents or new_daily > a.daily_limit_cents:
        raise _confirm_required("调高转账额度", ["single" if new_single > a.single_limit_cents else "daily"],
                                f"/api/v1/accounts/{a.id}/limits/prepare")
    changed = (new_single, new_daily) != (a.single_limit_cents, a.daily_limit_cents)
    a.single_limit_cents, a.daily_limit_cents = new_single, new_daily
    if changed:
        audit.log(ctx, "account_limits_lower", detail={"account_id": a.id, "single": fmt(new_single), "daily": fmt(new_daily)})
    return {"account_id": a.id, "limits": {"single": fmt(a.single_limit_cents), "daily": fmt(a.daily_limit_cents)},
            "changed": changed}


def _require_usable(c: Card) -> None:
    if c.status == "lost":
        raise LantaiError("CARD_STATE_INVALID", "卡片已挂失，无法修改设置")


def _resolve_limits(cur_single: int, cur_daily: int, single: int | None, daily: int | None, target: str) -> tuple[int, int]:
    if single is None and daily is None:
        raise LantaiError("VALIDATION_ERROR", "至少提供 single_limit 或 daily_limit")
    max_single = config.CARD_MAX_SINGLE_CENTS if target == "card" else config.ACCOUNT_MAX_SINGLE_CENTS
    max_daily = config.CARD_MAX_DAILY_CENTS if target == "card" else config.ACCOUNT_MAX_DAILY_CENTS
    new_single = cur_single if single is None else single
    new_daily = cur_daily if daily is None else daily
    if new_single > max_single or new_daily > max_daily:
        raise LantaiError("AMOUNT_ABOVE_MAX", f"额度上限：单笔 {fmt(max_single)} 元，单日 {fmt(max_daily)} 元")
    if new_single > new_daily:
        raise LantaiError("VALIDATION_ERROR", "单笔额度不得高于单日额度")
    return new_single, new_daily


def parse_limits(body) -> tuple[int | None, int | None]:
    return (parse_amount(body.single_limit) if body.single_limit else None,
            parse_amount(body.daily_limit) if body.daily_limit else None)


# ---------------- 需要确认（prepare → confirm）----------------
def _plan(db: Session, user: User, acc: Account, op_type: str, now, params: dict, summary: dict,
          change: dict, data: dict) -> Plan:
    rctx = engine.build_context(db, user.id, acc, op_type, 0, now, change=change)
    return Plan(op_type, params, summary, engine.evaluate(rctx), data)


def normalize_apply(db: Session, user: User, body) -> dict:
    return {"account_id": body.account_id}


def build_apply_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    acc = acct.get_owned_account(db, user.id, params["account_id"], lock=lock)
    n = len([c for c in list_cards(db, user.id) if c.account_id == acc.id and c.status != "lost"])
    if n >= config.MAX_CARDS_PER_ACCOUNT:
        raise LantaiError("CARD_QUOTA_REACHED", f"每个账户最多持有 {config.MAX_CARDS_PER_ACCOUNT} 张有效卡片")
    summary = {"action": "申请新借记卡", "account": f"{acct.TYPE_LABEL.get(acc.type, acc.type)} {mask(acc.account_no)}",
               "change": f"默认单笔 {fmt(config.CARD_DEFAULT_SINGLE_CENTS)} 元 / 单日 {fmt(config.CARD_DEFAULT_DAILY_CENTS)} 元；"
                         "境外交易默认关闭"}
    return _plan(db, user, acc, "card_apply", now, params, summary, {}, {"account": acc})


def execute_apply(db: Session, op, plan: Plan, now) -> dict:
    acc = plan.data["account"]
    c = _create_card(db, acc, now)
    return {"card_id": c.id, "card_no_masked": mask(c.card_no), "executed_at": clock.iso(now)}


def _create_card(db: Session, acc: Account, now, like: Card | None = None) -> Card:
    c = Card(id=new_id("crd"), user_id=acc.user_id, account_id=acc.id, card_no=_new_card_no(db), type="debit",
             status="active", online_enabled=like.online_enabled if like else True,
             overseas_enabled=like.overseas_enabled if like else False, atm_enabled=like.atm_enabled if like else True,
             single_limit_cents=like.single_limit_cents if like else config.CARD_DEFAULT_SINGLE_CENTS,
             daily_limit_cents=like.daily_limit_cents if like else config.CARD_DEFAULT_DAILY_CENTS,
             created_at=now, status_changed_at=now)
    db.add(c)
    return c


def normalize_card_only(db: Session, user: User, body) -> dict:
    return {"card_id": body.card_id}


def _card_account(db: Session, user: User, c: Card, lock: bool) -> Account:
    return acct.get_owned_account(db, user.id, c.account_id, lock=lock, require_active=False)


def build_unfreeze_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    c = get_owned(db, user.id, params["card_id"], lock=lock)
    if c.status not in ("frozen", "locked"):
        raise LantaiError("CARD_STATE_INVALID", f"卡片当前为{STATUS_TEXT[c.status]}，无需解冻/解锁")
    summary = {"action": "解锁卡片" if c.status == "locked" else "解冻卡片", "card": mask(c.card_no),
               "change": f"{STATUS_TEXT[c.status]} → 正常"}
    return _plan(db, user, _card_account(db, user, c, lock), "card_unfreeze", now, params, summary,
                 {"from": c.status}, {"card": c})


def execute_unfreeze(db: Session, op, plan: Plan, now) -> dict:
    c = plan.data["card"]
    _set_status(c, "active")
    return {"card_id": c.id, "status": c.status, "executed_at": clock.iso(now)}


def build_reissue_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    c = get_owned(db, user.id, params["card_id"], lock=lock)
    if c.status != "lost":
        raise LantaiError("CARD_STATE_INVALID", "仅已挂失的卡片可以补发")
    if c.replaced_by:
        raise LantaiError("CARD_STATE_INVALID", "该卡片已补发过新卡")
    summary = {"action": "补发新卡", "card": mask(c.card_no), "change": "新卡沿用原卡的额度与开关设置，旧卡号作废"}
    return _plan(db, user, _card_account(db, user, c, lock), "card_reissue", now, params, summary, {}, {"card": c})


def execute_reissue(db: Session, op, plan: Plan, now) -> dict:
    old = plan.data["card"]
    acc = db.get(Account, old.account_id)
    new = _create_card(db, acc, now, like=old)
    old.replaced_by = new.id
    return {"card_id": new.id, "card_no_masked": mask(new.card_no), "executed_at": clock.iso(now)}


def normalize_controls(db: Session, user: User, body) -> dict:
    changes = {k: getattr(body, k) for k in CONTROLS if getattr(body, k) is not None}
    if not changes:
        raise LantaiError("VALIDATION_ERROR", "至少提供 online / overseas / atm 之一")
    return {"card_id": body.card_id, "changes": changes}


def build_controls_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    c = get_owned(db, user.id, params["card_id"], lock=lock)
    _require_usable(c)
    diff = {k: v for k, v in params["changes"].items() if v != getattr(c, f"{k}_enabled")}
    loosen = [k for k, v in diff.items() if v]
    summary = {"action": "调整交易开关", "card": mask(c.card_no),
               "change": "；".join(f"{CONTROLS[k]}：{'关闭' if not v else '开启'}" for k, v in diff.items()) or "无变化"}
    return _plan(db, user, _card_account(db, user, c, lock), "card_controls", now, params, summary,
                 {"loosen": loosen}, {"card": c, "diff": diff})


def execute_controls(db: Session, op, plan: Plan, now) -> dict:
    c = plan.data["card"]
    for k, v in plan.data["diff"].items():
        setattr(c, f"{k}_enabled", v)
    return {"card": view(c), "executed_at": clock.iso(now)}


def normalize_limits(db: Session, user: User, body) -> dict:
    single, daily = parse_limits(body)
    key = "card_id" if hasattr(body, "card_id") else "account_id"
    return {key: getattr(body, key), "single_limit_cents": single, "daily_limit_cents": daily}


def _limit_summary(cur_s, cur_d, new_s, new_d) -> str:
    return f"单笔 {fmt(cur_s)} → {fmt(new_s)} 元；单日 {fmt(cur_d)} → {fmt(new_d)} 元"


def build_card_limits_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    c = get_owned(db, user.id, params["card_id"], lock=lock)
    _require_usable(c)
    ns, nd = _resolve_limits(c.single_limit_cents, c.daily_limit_cents, params["single_limit_cents"],
                             params["daily_limit_cents"], "card")
    summary = {"action": "调整卡片额度", "card": mask(c.card_no), "change": _limit_summary(c.single_limit_cents, c.daily_limit_cents, ns, nd)}
    change = {"raise": ns > c.single_limit_cents or nd > c.daily_limit_cents, "old": fmt(c.daily_limit_cents), "new": fmt(nd)}
    return _plan(db, user, _card_account(db, user, c, lock), "card_limits", now, params, summary, change,
                 {"card": c, "new": (ns, nd)})


def execute_card_limits(db: Session, op, plan: Plan, now) -> dict:
    c = plan.data["card"]
    c.single_limit_cents, c.daily_limit_cents = plan.data["new"]
    return {"card": view(c), "executed_at": clock.iso(now)}


def build_account_limits_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    a = acct.get_owned_account(db, user.id, params["account_id"], lock=lock, require_active=False)
    ns, nd = _resolve_limits(a.single_limit_cents, a.daily_limit_cents, params["single_limit_cents"],
                             params["daily_limit_cents"], "account")
    summary = {"action": "调整账户转账额度", "account": f"{acct.TYPE_LABEL.get(a.type, a.type)} {mask(a.account_no)}",
               "change": _limit_summary(a.single_limit_cents, a.daily_limit_cents, ns, nd)}
    change = {"raise": ns > a.single_limit_cents or nd > a.daily_limit_cents, "old": fmt(a.daily_limit_cents), "new": fmt(nd)}
    return _plan(db, user, a, "account_limits", now, params, summary, change, {"account": a, "new": (ns, nd)})


def execute_account_limits(db: Session, op, plan: Plan, now) -> dict:
    a = plan.data["account"]
    a.single_limit_cents, a.daily_limit_cents = plan.data["new"]
    return {"account_id": a.id, "limits": {"single": fmt(a.single_limit_cents), "daily": fmt(a.daily_limit_cents)},
            "executed_at": clock.iso(now)}
