import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event
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


def drop_tables() -> None:
    Base.metadata.drop_all(engine)
