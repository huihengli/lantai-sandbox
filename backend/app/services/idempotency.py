import hashlib
import json
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock, config
from app.errors import LantaiError
from app.models import IdempotencyRecord


def request_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def lookup(db: Session, key: str | None, user_id: str, endpoint: str, req_hash: str) -> dict | None:
    if not key:
        return None
    rec = db.get(IdempotencyRecord, (key, user_id, endpoint))
    if rec is None or rec.created_at < clock.now() - timedelta(seconds=config.IDEMPOTENCY_TTL_SECONDS):
        if rec is not None:
            db.delete(rec)
            db.flush()
        return None
    if rec.request_hash != req_hash:
        raise LantaiError("IDEMPOTENCY_CONFLICT", "同一幂等键对应的请求内容不一致")
    return json.loads(rec.response_json)


def store(db: Session, key: str | None, user_id: str, endpoint: str, req_hash: str, response: dict) -> bool:
    """False 表示并发请求已抢先写入同一幂等键（调用方应回滚并返回首次响应）。"""
    if not key:
        return True
    db.add(IdempotencyRecord(key=key, user_id=user_id, endpoint=endpoint, request_hash=req_hash,
                             response_json=json.dumps(response, ensure_ascii=False), created_at=clock.now()))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


def purge_expired(db: Session) -> None:
    """惰性清理过期幂等记录。"""
    db.execute(delete(IdempotencyRecord).where(
        IdempotencyRecord.created_at < clock.now() - timedelta(seconds=config.IDEMPOTENCY_TTL_SECONDS)))
