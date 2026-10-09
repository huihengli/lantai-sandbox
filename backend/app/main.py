import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app import config
from app.api import admin, ui, v1
from app.db import SessionLocal, create_tables
from app.errors import LantaiError
from app.models import User
from app.seed.seed_data import seed

log = logging.getLogger("lantai")


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    with SessionLocal() as db:
        empty = db.scalar(select(User.id).limit(1)) is None
    if empty:
        seed()
    yield


app = FastAPI(
    title="澜台 Lantai 模拟银行 API",
    description="面向智能金融助手 Agent 的模拟银行后端。Agent 通道 /api/v1，用户通道 /ui，演示管理 /admin。"
                "后端不信任 Agent：所有限额、黑名单、归属、确认校验均在此完成。",
    version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = "req_" + uuid.uuid4().hex[:8]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


def _error(request: Request, status: int, code: str, message: str, details: dict | None = None):
    return JSONResponse(status_code=status, content={
        "ok": False, "request_id": getattr(request.state, "request_id", ""),
        "error": {"code": code, "message": message, "details": details or {}}})


@app.exception_handler(LantaiError)
async def lantai_error_handler(request: Request, exc: LantaiError):
    return _error(request, exc.status, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errs = [{"loc": ".".join(str(i) for i in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
    return _error(request, 422, "VALIDATION_ERROR", "请求参数不合法", {"errors": errs})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    log.exception("unhandled error")
    return _error(request, 500, "INTERNAL_ERROR", "服务内部错误")


@app.get("/healthz", tags=["admin"])
def healthz():
    return {"status": "ok"}


app.include_router(v1.router)
app.include_router(ui.router)
app.include_router(admin.router)


# ---- 托管前端构建产物（SPA）：未构建时跳过 ----
_DIST = os.path.abspath(config.FRONTEND_DIST)
if os.path.isfile(os.path.join(_DIST, "index.html")):
    _API_PREFIXES = ("api/", "ui/", "admin/", "docs", "redoc", "openapi.json", "healthz")
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(_API_PREFIXES):
            return _error_response(path)
        candidate = os.path.join(_DIST, path)
        if path and os.path.isfile(candidate) and os.path.abspath(candidate).startswith(_DIST):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_DIST, "index.html"))

    def _error_response(path: str):
        return JSONResponse(status_code=404, content={"ok": False, "request_id": "", "error": {
            "code": "NOT_FOUND", "message": f"接口不存在：/{path}", "details": {}}})
