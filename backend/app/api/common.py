from fastapi import Request

from app.errors import LantaiError


def ok(request: Request, data) -> dict:
    return {"ok": True, "request_id": request.state.request_id, "data": data}


def intent_of(body) -> str | None:
    ctx = getattr(body, "agent_context", None)
    return ctx.intent_summary if ctx else None


def idem_key(request: Request, body) -> str | None:
    key = request.headers.get("idempotency-key") or getattr(body, "idempotency_key", None)
    if key and len(key) > 100:
        raise LantaiError("VALIDATION_ERROR", "Idempotency-Key 过长（最多 100 字符）")
    return key
