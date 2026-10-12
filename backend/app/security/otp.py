"""模拟 OTP：验证码只通过用户通道（/ui）展示，Agent 通道任何响应都不含。"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import clock, config
from app.errors import LantaiError
from app.models import OtpChallenge, PendingOperation
from app.money import new_id
from app.security import ratelimit
from app.services import audit, events


def _hash(op_id: str, code: str) -> str:
    return hmac.new(config.OTP_PEPPER.encode(), f"{op_id}:{code}".encode(), hashlib.sha256).hexdigest()


def issue(db: Session, op: PendingOperation) -> OtpChallenge:
    code = config.OTP_FIXED_CODE or f"{secrets.randbelow(10**6):06d}"
    ch = OtpChallenge(
        id=new_id("otp"), operation_id=op.id, code_hash=_hash(op.id, code),
        demo_code=code if config.OTP_DEMO_MODE else "",  # 非演示模式不存明文
        max_attempts=config.OTP_MAX_ATTEMPTS, status="issued",
        expires_at=clock.now() + timedelta(seconds=config.OPERATION_TTL_SECONDS),
    )
    db.add(ch)
    return ch


def latest(db: Session, op_id: str) -> OtpChallenge | None:
    return db.scalar(select(OtpChallenge).where(OtpChallenge.operation_id == op_id)
                     .order_by(OtpChallenge.expires_at.desc()))


def verify(ctx: audit.Ctx, op: PendingOperation, code: str) -> None:
    db = ctx.db
    ch = latest(db, op.id)
    if ch is None:
        raise LantaiError("OTP_REQUIRED", "该操作没有待验证的 OTP")
    if ch.status == "locked":
        raise LantaiError("OTP_LOCKED", "OTP 已锁定，请重新发起操作")
    if ch.expires_at <= clock.now():
        ch.status = "expired"
        raise LantaiError("OTP_EXPIRED", "OTP 已过期，请重新发起操作")
    fail_key = f"otp:{op.user_id}"
    if ratelimit.is_blocked(fail_key, config.OTP_USER_FAIL_LIMIT, config.OTP_USER_FAIL_WINDOW):
        raise LantaiError("RATE_LIMITED", "验证码错误次数过多，请稍后再试")
    if hmac.compare_digest(_hash(op.id, code), ch.code_hash):
        ch.status = "verified"
        op.status = "OTP_VERIFIED"
        events.emit(db, op.user_id, "operation", op.id, {"operation_id": op.id, "op_type": op.type, "status": op.status})
        audit.log(ctx, "otp_verify", operation_id=op.id)
        return
    ratelimit.record(fail_key)
    db.execute(update(OtpChallenge).where(OtpChallenge.id == ch.id).values(attempts=OtpChallenge.attempts + 1)
               .execution_options(synchronize_session=False))  # 原子自增，防并发少计
    db.refresh(ch)
    left = ch.max_attempts - ch.attempts
    if left <= 0:
        ch.status = "locked"
        op.status = "OTP_LOCKED"
        events.emit(db, op.user_id, "operation", op.id, {"operation_id": op.id, "op_type": op.type, "status": op.status})
    db.commit()  # 错误次数必须落库，不能随异常回滚（拒绝记录由 guarded 写入审计）
    if left <= 0:
        raise LantaiError("OTP_LOCKED", "OTP 错误次数过多，操作已锁定，请重新发起")
    raise LantaiError("OTP_INVALID", "OTP 不正确", {"attempts_left": left})
