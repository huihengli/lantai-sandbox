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
from app.db import SessionLocal, create_tables, schema_problems
from app.errors import LantaiError
from app.models import User
from app.seed.seed_data import reset_database, seed

log = logging.getLogger("lantai")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if config.APP_ENV == "prod" and "lantai_dev" in config.DATABASE_URL:
        raise RuntimeError("APP_ENV=prod 不得使用默认数据库口令")
    if config.APP_ENV == "prod" and config.ADMIN_ENABLED and (
            config.ADMIN_KEY == "dev-admin-key" or len(config.ADMIN_KEY) < config.ADMIN_KEY_MIN_LENGTH):
        raise RuntimeError(f"APP_ENV=prod 且启用 /admin 时，必须设置至少 {config.ADMIN_KEY_MIN_LENGTH} 位的强随机 ADMIN_KEY")
    create_tables()
    problems = schema_problems()
    if problems:
        if config.RESET_DB_ON_START:
            log.warning("数据库结构落后于代码（%s），按 RESET_DB_ON_START=1 重建", "; ".join(problems[:5]))
            reset_database()
        else:
            raise RuntimeError(
                f"数据库结构与当前代码不一致（共 {len(problems)} 处，如：{'; '.join(problems[:3])}）。"
                "开发环境请删除 backend/data/lantai.db 后重启（Postgres 请删除数据卷），"
                "或设置环境变量 RESET_DB_ON_START=1 让服务启动时清空并重建。")
    with SessionLocal() as db:
        empty = db.scalar(select(User.id).limit(1)) is None
    if empty:
        seed()
    yield


app = FastAPI(
    title="澜台 Lantai 模拟银行 API",
    description="面向智能金融助手 Agent 的模拟银行后端。Agent 通道 /api/v1，用户通道 /ui，演示管理 /admin。"
                "后端不信任 Agent：所有限额、黑名单、归属、确认校验均在此完成。",
    version="1.0.0", lifespan=lifespan,
    docs_url="/docs" if config.DOCS_ENABLED else None, redoc_url="/redoc" if config.DOCS_ENABLED else None,
    openapi_url="/openapi.json" if config.DOCS_ENABLED else None)

_CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'"
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = "req_" + uuid.uuid4().hex[:8]
    if len(request.url.path) > 256:
        return _error(request, 404, "NOT_FOUND", "接口不存在")
    try:
        too_big = int(request.headers.get("content-length") or 0) > config.MAX_BODY_BYTES
    except ValueError:
        too_big = True
    if too_big:
        return _error(request, 413, "PAYLOAD_TOO_LARGE", "请求体过大")
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith(("/api/", "/ui/", "/admin/")):
        response.headers["Cache-Control"] = "no-store"
    if not request.url.path.startswith(_DOC_PATHS):  # 文档页依赖外部脚本，不加 CSP
        response.headers["Content-Security-Policy"] = _CSP
    if config.APP_ENV == "prod":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
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
        if path and os.path.isfile(candidate) and _inside_dist(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_DIST, "index.html"))

    def _inside_dist(candidate: str) -> bool:
        try:
            return os.path.commonpath([os.path.realpath(_DIST), os.path.realpath(candidate)]) == os.path.realpath(_DIST)
        except ValueError:
            return False

    def _error_response(path: str):
        return JSONResponse(status_code=404, content={"ok": False, "request_id": "", "error": {
            "code": "NOT_FOUND", "message": f"接口不存在：/{path}", "details": {}}})
