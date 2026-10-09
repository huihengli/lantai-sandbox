import os

os.environ["DATABASE_URL"] = "sqlite://"  # 内存库，必须在导入 app 之前设置

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import clock  # noqa: E402
from app.main import app  # noqa: E402
from app.seed.seed_data import reset_database  # noqa: E402

ADMIN = {"X-Admin-Key": "dev-admin-key"}


@pytest.fixture(autouse=True)
def fresh_db():
    clock.reset()
    local = clock.local(clock.now())
    clock.set_time(datetime(local.year, local.month, local.day, 14, 0))  # 固定在白天，避免夜间提示干扰
    reset_database()
    yield
    clock.reset()


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


class Actor:
    """封装一个已登录用户：user（用户通道）与 agent（Agent 通道）两套请求头。"""

    def __init__(self, client: TestClient, phone: str = "13800000001"):
        self.c = client
        r = client.post("/ui/login", json={"phone": phone, "password": "Lantai@2026"}).json()
        self.session = {"Authorization": "Bearer " + r["data"]["session_token"]}
        g = client.post("/ui/agent-grants", json={"scopes": ["read", "prepare"]}, headers=self.session).json()
        self.agent = {"Authorization": "Bearer " + g["data"]["agent_token"]}
        self.grant_id = g["data"]["grant_id"]

    def transfer(self, amount, payee_id="pye_001", frm="acc_001", **extra):
        body = {"from_account_id": frm, "amount": amount, **extra}
        if payee_id:
            body["payee_id"] = payee_id
        return self.c.post("/api/v1/transfers/prepare", json=body, headers=self.agent).json()

    def confirm(self, op_id):
        return self.c.post(f"/ui/operations/{op_id}/confirm", headers=self.session).json()

    def otp(self, op_id, code="123456"):
        return self.c.post(f"/ui/operations/{op_id}/verify-otp", json={"code": code}, headers=self.session).json()

    def balance(self, acc="acc_001"):
        return self.c.get(f"/api/v1/accounts/{acc}/balance", headers=self.agent).json()["data"]["balance"]


@pytest.fixture()
def lin(client):
    return Actor(client)
