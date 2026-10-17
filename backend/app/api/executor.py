"""确认执行器通道 /api/exec：只接受 executor_token（lt_x_*）。
执行器是 Agent 侧的确定性 workflow：LLM 调用确认工具 → interrupt → 执行器拉取操作详情、弹出确认框 →
用户手动确认（需要时输入短信验证码）→ 调用本通道 → 结果回写 Agent 上下文。
因此只有 GET 详情（渲染确认框、给用户看）返回完整视图；verify-otp / confirm / reject 的返回会进入 LLM 上下文，
统一按 Agent 视图裁剪（无 balance_after，敏感风控原因中性化）。
Agent 令牌与用户会话都不能调用这里；执行器令牌也不能调用 /api/v1 与 /ui。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.common import ok
from app import clock
from app.db import get_db
from app.models import AuthToken
from app.schemas import OtpIn
from app.security.auth import Principal, make_ctx, require
from app.services import audit, operation

router = APIRouter(prefix="/api/exec", tags=["executor"])

CONFIRM = Depends(require("confirm", executor_only=True))
OTP = Depends(require("otp", executor_only=True))
EXECUTOR = Depends(require(executor_only=True))  # 仅认人：有效执行器令牌即可，不额外要求 scope


@router.get("/me")
def me(request: Request, p: Principal = EXECUTOR, db: Session = Depends(get_db)):
    """执行器用自己的令牌向银行核验身份，不依赖运行时转交的 user_id。
    只返回认人所需字段；issued_at 取所属授权的签发时间，供"锁定后重新授权"判断。"""
    grant = db.get(AuthToken, p.token.issued_by)
    audit.log(make_ctx(request, db, p), "exec_whoami")  # grant_id 由 ctx 自动写入 detail
    db.commit()
    return ok(request, {"token_kind": p.kind, "user_id": p.user.id, "grant_id": p.token.issued_by,
                        "scopes": sorted(p.scopes), "issued_at": clock.iso(grant.created_at if grant else None),
                        "expires_at": clock.iso(p.token.expires_at)})


@router.get("/operations/{op_id}")
def get_operation(op_id: str, request: Request, p: Principal = CONFIRM, db: Session = Depends(get_db)):
    """确认框渲染用：与用户确认中心看到的内容一致（摘要、风控原因、是否需要 OTP、有效期）。
    仅供执行器展示给用户，不应写回 LLM 上下文。"""
    return ok(request, operation.view(operation.get_op(db, p.user.id, op_id), p.actor))


@router.post("/operations/{op_id}/verify-otp")
def verify_otp(op_id: str, body: OtpIn, request: Request, p: Principal = OTP, db: Session = Depends(get_db)):
    """提交用户在确认框中输入的短信验证码。"""
    ctx = make_ctx(request, db, p)
    out = audit.guarded(ctx, "otp_verify", lambda: operation.verify_otp(ctx, p.user, op_id, body.code), op_id)
    return ok(request, operation.trim_for_llm(out))


@router.post("/operations/{op_id}/confirm")
def confirm(op_id: str, request: Request, p: Principal = CONFIRM, db: Session = Depends(get_db)):
    """用户在确认框点击“确认”后调用。执行前同样重新风控、重新校验余额与状态。"""
    ctx = make_ctx(request, db, p)
    out = audit.guarded(ctx, "confirm", lambda: operation.confirm(ctx, p.user, op_id), op_id)
    return ok(request, operation.trim_for_llm(out))


@router.post("/operations/{op_id}/reject")
def reject(op_id: str, request: Request, p: Principal = CONFIRM, db: Session = Depends(get_db)):
    """用户在确认框点击“拒绝”后调用。"""
    ctx = make_ctx(request, db, p)
    out = audit.guarded(ctx, "reject", lambda: operation.cancel(ctx, p.user, op_id, "reject"), op_id)
    return ok(request, operation.trim_for_llm(out))
