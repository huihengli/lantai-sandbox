from fastapi import Request


def ok(request: Request, data) -> dict:
    return {"ok": True, "request_id": request.state.request_id, "data": data}


def intent_of(body) -> str | None:
    ctx = getattr(body, "agent_context", None)
    return ctx.intent_summary if ctx else None


def idem_key(request: Request, body) -> str | None:
    return request.headers.get("idempotency-key") or getattr(body, "idempotency_key", None)
