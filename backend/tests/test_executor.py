"""确认执行器通道 /api/exec：独立令牌、通道隔离、确认/OTP/拒绝、越权与审计。"""
import pytest

from tests.conftest import Actor


def grant(client, who, scopes=None):
    body = {} if scopes is None else {"scopes": scopes}
    return client.post("/ui/executor-grants", json=body, headers=who.session).json()


@pytest.fixture()
def exe(client, lin):
    g = grant(client, lin)["data"]
    assert g["executor_token"].startswith("lt_x_") and g["scopes"] == ["confirm", "otp"]
    return {"Authorization": "Bearer " + g["executor_token"]}


def test_executor_grant_scopes_are_limited(client, lin):
    for bad in (["read"], ["prepare"], ["confirm", "grant"], []):
        assert grant(client, lin, bad)["error"]["code"] in ("SCOPE_INSUFFICIENT", "VALIDATION_ERROR")
    assert grant(client, lin, ["confirm"])["data"]["scopes"] == ["confirm"]
    # Agent 令牌仍然拿不到 confirm/otp，也不能签发执行器令牌
    assert client.post("/ui/agent-grants", json={"scopes": ["confirm"]}, headers=lin.session).json()["error"]["code"] == "SCOPE_INSUFFICIENT"
    assert client.post("/ui/executor-grants", json={}, headers=lin.agent).json()["error"]["code"] == "CHANNEL_NOT_ALLOWED"


def test_channels_are_isolated(client, lin, exe):
    op = lin.transfer("100.00")["data"]["operation_id"]
    # 执行器令牌不能访问 Agent 通道与用户通道
    assert client.get("/api/v1/accounts", headers=exe).json()["error"]["code"] == "CHANNEL_NOT_ALLOWED"
    assert client.post("/api/v1/transfers/prepare", headers=exe,
                       json={"from_account_id": "acc_001", "payee_id": "pye_001", "amount": "1.00"}).status_code == 403
    assert client.post(f"/ui/operations/{op}/confirm", headers=exe).json()["error"]["code"] == "CHANNEL_NOT_ALLOWED"
    # Agent 令牌与用户会话都不能调用执行器通道
    for h in (lin.agent, lin.session):
        r = client.post(f"/api/exec/operations/{op}/confirm", headers=h)
        assert r.status_code == 403 and r.json()["error"]["code"] == "CHANNEL_NOT_ALLOWED"
    assert lin.balance() == "50800.00"


def test_executor_confirms_after_dialog(client, lin, exe):
    op = lin.transfer("500.00")["data"]["operation_id"]
    detail = client.get(f"/api/exec/operations/{op}", headers=exe).json()["data"]
    assert detail["status"] == "PREPARED" and detail["summary"]["amount"] == "500.00"
    done = client.post(f"/api/exec/operations/{op}/confirm", headers=exe).json()["data"]
    assert done["status"] == "EXECUTED" and lin.balance() == "50300.00"
    again = client.post(f"/api/exec/operations/{op}/confirm", headers=exe).json()["data"]
    assert again["status"] == "EXECUTED" and lin.balance() == "50300.00"  # 重复确认不重复执行
    log = client.get("/ui/audit", headers=lin.session).json()["data"]
    row = next(r for r in log if r["action"] == "confirm:transfer")
    assert (row["actor"], row["channel"]) == ("executor", "exec")


def test_executor_otp_flow(client, lin, exe):
    op = lin.transfer("100.00", payee_id=None, payee_account_no="6217000040003456", payee_name="张三")["data"]
    assert op["status"] == "OTP_PENDING"
    oid = op["operation_id"]
    assert client.post(f"/api/exec/operations/{oid}/confirm", headers=exe).json()["error"]["code"] == "OTP_REQUIRED"
    assert client.post(f"/api/exec/operations/{oid}/verify-otp", json={"code": "000000"}, headers=exe).json()["error"]["code"] == "OTP_INVALID"
    assert client.post(f"/api/exec/operations/{oid}/verify-otp", json={"code": "123456"}, headers=exe).json()["data"]["status"] == "OTP_VERIFIED"
    assert client.post(f"/api/exec/operations/{oid}/confirm", headers=exe).json()["data"]["status"] == "EXECUTED"


def test_confirm_only_executor_cannot_submit_otp(client, lin):
    h = {"Authorization": "Bearer " + grant(client, lin, ["confirm"])["data"]["executor_token"]}
    oid = lin.transfer("100.00", payee_id=None, payee_account_no="6217000040003456", payee_name="张三")["data"]["operation_id"]
    r = client.post(f"/api/exec/operations/{oid}/verify-otp", json={"code": "123456"}, headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_INSUFFICIENT"


def test_executor_reject(client, lin, exe):
    op = lin.transfer("100.00")["data"]["operation_id"]
    assert client.post(f"/api/exec/operations/{op}/reject", headers=exe).json()["data"]["status"] == "CANCELLED"
    assert client.post(f"/api/exec/operations/{op}/confirm", headers=exe).json()["error"]["code"] == "OPERATION_STATE_INVALID"
    assert lin.balance() == "50800.00"


def test_executor_cannot_touch_other_users_operations(client, lin, exe):
    other = Actor(client, "13900000002")
    op = other.transfer("10.00", payee_id=None, frm="acc_101", payee_account_no="6217000010001001", payee_name="测试1")
    oid = op["data"]["operation_id"]
    for method, path in (("get", ""), ("post", "/confirm"), ("post", "/reject")):
        r = getattr(client, method)(f"/api/exec/operations/{oid}{path}", headers=exe)
        assert r.status_code == 404 and r.json()["error"]["code"] == "OPERATION_NOT_FOUND"


def test_executor_token_revocation(client, lin):
    g = grant(client, lin)["data"]
    h = {"Authorization": "Bearer " + g["executor_token"]}
    op = lin.transfer("1.00")["data"]["operation_id"]
    assert client.get(f"/api/exec/operations/{op}", headers=h).status_code == 200
    listed = client.get("/ui/executor-grants", headers=lin.session).json()["data"]
    assert listed[0]["grant_id"] == g["grant_id"] and "executor_token" not in listed[0]  # 明文只返回一次
    assert client.delete(f"/ui/executor-grants/{g['grant_id']}", headers=lin.session).json()["data"]["revoked"]
    assert client.get(f"/api/exec/operations/{op}", headers=h).json()["error"]["code"] == "AUTH_REVOKED"
    # 不能用执行器接口撤销 Agent 授权，反之亦然
    assert client.delete(f"/ui/executor-grants/{lin.grant_id}", headers=lin.session).json()["error"]["code"] == "RESOURCE_NOT_OWNED"


def test_logout_revoke_grants_covers_executor(client, lin, exe):
    op = lin.transfer("1.00")["data"]["operation_id"]
    client.post("/ui/logout", params={"revoke_grants": "true"}, headers=lin.session)
    assert client.get(f"/api/exec/operations/{op}", headers=exe).json()["error"]["code"] == "AUTH_REVOKED"
