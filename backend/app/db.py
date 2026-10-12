import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.models import Base


def _make_engine() -> Engine:
    url = config.DATABASE_URL
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs["poolclass"] = StaticPool
    else:
        path = url.removeprefix("sqlite:///")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    eng = create_engine(url, **kwargs)

    @event.listens_for(eng, "connect")
    def _pragmas(conn, _):  # noqa: ANN001
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        if "memory" not in url and url != "sqlite://":
            cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return eng


engine = _make_engine()
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def create_tables() -> None:
    Base.metadata.create_all(engine)


def schema_problems(eng: Engine | None = None) -> list[str]:
    """对比代码模型与现有数据库：缺表、缺列。create_all 不会给旧表补列，旧库升级后会出现隐蔽的 500。"""
    insp = inspect(eng or engine)
    problems: list[str] = []
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            problems.append(f"缺少表 {table.name}")
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        problems += [f"{table.name}.{c.name} 缺失" for c in table.columns if c.name not in have]
    return problems


def drop_tables(keep_audit: bool = False) -> None:
    tables = [t for t in Base.metadata.sorted_tables if not (keep_audit and t.name == "audit_logs")]
    Base.metadata.drop_all(engine, tables=tables)
