"""演示管理接口，需 X-Admin-Key 头。"""
import hmac
from decimal import Decimal, InvalidOperation
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, config
from app.api.common import ok
from app.api.ui import audit_row
from app.db import SessionLocal, get_db
from app.errors import LantaiError
from app.models import AuditLog, Blacklist, Card, WealthProduct
from app.money import new_id
from app.security import ratelimit
from app.schemas import BlacklistIn, ClockIn, NavIn
from app.seed.seed_data import reset_database
from app.services import audit
from app.services import mandates as mandate_svc


def admin_only(request: Request) -> None:
    if not hmac.compare_digest(request.headers.get("x-admin-key", ""), config.ADMIN_KEY):
        raise LantaiError("AUTH_INVALID", "管理密钥无效")


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_only)])


def _ctx(request: Request, db: Session) -> audit.Ctx:
    return audit.Ctx(db, request.state.request_id, None, "admin", "admin")


@router.post("/reset")
def reset(request: Request):
    reset_database()
    ratelimit.reset()
    with SessionLocal() as db:  # 重置后写一条 reset 事件
        ctx = _ctx(request, db)
        audit.log(ctx, "reset")
        db.commit()
    return ok(request, {"reset": True, "now": clock.iso(clock.now())})


@router.post("/clock")
def set_clock(body: ClockIn, request: Request):
    if body.set_time:
        try:
            clock.set_time(datetime.fromisoformat(body.set_time))
        except ValueError:
            raise LantaiError("VALIDATION_ERROR", "set_time 需为 ISO8601 时间") from None
    if body.advance_seconds:
        clock.advance(body.advance_seconds)
    return ok(request, {"now": clock.iso(clock.now())})


@router.delete("/clock")
def reset_clock(request: Request):
    clock.reset()
    return ok(request, {"now": clock.iso(clock.now())})


@router.get("/blacklist")
def list_blacklist(request: Request, db: Session = Depends(get_db)):
    rows = db.scalars(select(Blacklist))
    return ok(request, [{"id": r.id, "account_no": r.account_no, "bank_code": r.bank_code,
                         "reason_code": r.reason_code, "source": r.source} for r in rows])


@router.post("/blacklist")
def add_blacklist(body: BlacklistIn, request: Request, db: Session = Depends(get_db)):
    def run():
        row = Blacklist(id=new_id("bl"), created_at=clock.now(), **body.model_dump())
        db.add(row)
        audit.log(_ctx(request, db), "blacklist_add", detail=body.model_dump())
        return {"id": row.id}

    return ok(request, audit.guarded(_ctx(request, db), "blacklist_add", run))


@router.delete("/blacklist/{item_id}")
def delete_blacklist(item_id: str, request: Request, db: Session = Depends(get_db)):
    row = db.get(Blacklist, item_id)
    if row is None:
        raise LantaiError("VALIDATION_ERROR", "黑名单条目不存在")
    db.delete(row)
    audit.log(_ctx(request, db), "blacklist_remove", detail={"id": item_id})
    db.commit()
    return ok(request, {"deleted": item_id})


@router.get("/audit")
def all_audit(request: Request, db: Session = Depends(get_db), limit: int = 200):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000)))
    return ok(request, [audit_row(r) for r in rows])


@router.post("/cards/{card_id}/lock")
def lock_card(card_id: str, request: Request, db: Session = Depends(get_db)):
    """演示用：模拟连续输错 PIN 导致卡片被锁定。"""
    def run():
        card = db.get(Card, card_id)
        if card is None:
            raise LantaiError("VALIDATION_ERROR", "卡片不存在")
        card.status, card.status_changed_at = "locked", clock.now()
        audit.log(_ctx(request, db), "card_lock", detail={"card_id": card_id})
        return {"card_id": card_id, "status": "locked"}

    return ok(request, audit.guarded(_ctx(request, db), "card_lock", run))


@router.post("/mandates/{mandate_id}/charge")
def charge_mandate(mandate_id: str, request: Request, db: Session = Depends(get_db)):
    """演示用：模拟商户发起一次代扣。"""
    ctx = _ctx(request, db)
    return ok(request, audit.guarded(ctx, "mandate_charge", lambda: mandate_svc.charge(ctx, mandate_id)))


@router.post("/wealth/{product_id}/nav")
def set_nav(product_id: str, body: NavIn, request: Request, db: Session = Depends(get_db)):
    """演示用：调整理财产品净值（制造盈亏）。"""
    def run():
        p = db.get(WealthProduct, product_id)
        if p is None:
            raise LantaiError("VALIDATION_ERROR", "产品不存在")
        try:
            d = Decimal(body.nav)
        except InvalidOperation:
            raise LantaiError("VALIDATION_ERROR", "nav 格式不合法") from None
        if d <= 0 or d != d.quantize(Decimal("0.0001")):
            raise LantaiError("VALIDATION_ERROR", "nav 需大于 0 且最多四位小数")
        p.nav_bp, p.nav_updated_at = int(d * 10000), clock.now()
        audit.log(_ctx(request, db), "wealth_nav_set", detail={"product_id": product_id, "nav": body.nav})
        return {"product_id": product_id, "nav": f"{d:.4f}"}

    return ok(request, audit.guarded(_ctx(request, db), "wealth_nav_set", run))
