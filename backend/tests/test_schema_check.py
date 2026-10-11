"""旧库升级检测：数据库缺表/缺列时应能发现，避免运行期的隐蔽 500。"""
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.db import schema_problems
from app.models import Base


def _engine():
    return create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})


def test_fresh_schema_has_no_problems():
    eng = _engine()
    Base.metadata.create_all(eng)
    assert schema_problems(eng) == []


def test_detects_missing_table_and_column():
    eng = _engine()
    with eng.begin() as c:  # 模拟早期版本的 users 表：没有 risk_level 等后加的列
        c.execute(text("CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT, phone TEXT, phone_masked TEXT, "
                       "password_hash TEXT, risk_profile TEXT, status TEXT, created_at TEXT)"))
    problems = schema_problems(eng)
    assert "users.risk_level 缺失" in problems and "users.risk_assessed_at 缺失" in problems
    assert "缺少表 wealth_products" in problems and "缺少表 cards" in problems
