"""事件流：把"发生了什么"以只读、递增的流提供给 Agent 轮询（入账/扣款、操作状态、卡片/协议变化）。
银行不推送、不调度；提醒、对账、定时触发全部由 Agent 基于此实现。"""
import json

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import clock, config
from app.models import Event

MAX_PAGE = 200


def emit(db: Session, user_id: str, type_: str, ref_id: str | None, data: dict) -> None:
    db.add(Event(ts=clock.now(), user_id=user_id, type=type_, ref_id=ref_id,
                 data_json=json.dumps(data, ensure_ascii=False)))


def purge_old(db: Session) -> None:
    db.execute(delete(Event).where(Event.ts < clock.now() - timedelta(days=config.EVENT_RETENTION_DAYS)))


def view(e: Event) -> dict:
    return {"id": e.id, "ts": clock.iso(e.ts), "type": e.type, "ref_id": e.ref_id, "data": json.loads(e.data_json)}


def fetch(db: Session, user_id: str, after_id: int, limit: int, types: list[str] | None) -> dict:
    stmt = select(Event).where(Event.user_id == user_id, Event.id > after_id)
    if types:
        stmt = stmt.where(Event.type.in_(types))
    rows = list(db.scalars(stmt.order_by(Event.id).limit(min(limit, MAX_PAGE) + 1)))
    page = rows[:limit]
    latest = db.scalar(select(Event.id).where(Event.user_id == user_id).order_by(Event.id.desc()).limit(1)) or 0
    return {"items": [view(e) for e in page], "next_after_id": page[-1].id if page else after_id,
            "has_more": len(rows) > limit, "latest_id": latest}
