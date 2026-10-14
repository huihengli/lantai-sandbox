"""审计日志（只增不改）与请求上下文。"""
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy.orm import Session

from app import clock
from app.errors import LantaiError
from app.models import AuditLog

T = TypeVar("T")


@dataclass
class Ctx:
    db: Session
    request_id: str
    user_id: str | None
    actor: str  # agent / user / system / admin
    channel: str  # api / ui / admin
    agent_intent: str | None = None
    ip: str | None = None
    grant_id: str | None = None
    ua: str | None = None


def log(ctx: Ctx, action: str, result: str = "ok", operation_id: str | None = None,
        risk: dict | None = None, error_code: str | None = None, detail: dict | None = None) -> None:
    if ctx.grant_id:  # Agent / 执行器所属授权编号，二者相同即同一授权
        detail = {**(detail or {}), "grant_id": ctx.grant_id}
    if ctx.ip or ctx.ua:  # 来源信息放入 detail，避免改表结构
        detail = {**(detail or {}), "client": {"ip": ctx.ip, "ua": (ctx.ua or "")[:120]}}
    ctx.db.add(AuditLog(
        ts=clock.now(), user_id=ctx.user_id, actor=ctx.actor, channel=ctx.channel,
        action=action, operation_id=operation_id, agent_intent=ctx.agent_intent,
        risk_json=json.dumps(risk, ensure_ascii=False) if risk else None,
        result=result, error_code=error_code,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        request_id=ctx.request_id,
    ))


def guarded(ctx: Ctx, action: str, fn: Callable[[], T], operation_id: str | None = None) -> T:
    """执行写操作：成功提交；业务异常则回滚并把拒绝记录写入审计后再抛出。"""
    try:
        out = fn()
        ctx.db.commit()
        return out
    except LantaiError as exc:
        ctx.db.rollback()
        log(ctx, action, result="blocked" if exc.code == "RISK_BLOCKED" else "rejected",
            operation_id=operation_id, error_code=exc.code,
            detail={"message": exc.message, **exc.details})
        ctx.db.commit()
        raise
    except Exception:
        ctx.db.rollback()
        raise
