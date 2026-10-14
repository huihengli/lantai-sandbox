"""确认执行器通道 /api/exec：独立令牌、通道隔离、确认/OTP/拒绝、越权与审计。"""
import pytest

from tests.conftest import Actor


def grant(client, who, **body):
    return client.post("/ui/agent-grants", json=body, headers=who.session).json()


@pytest.fixture()
def exe(client, lin):
    return lin.executor


def test_one_grant_issues_both_tokens(client, lin):
    g = grant(client, lin)["data"]
    assert g["agent_token"].startswith("lt_a_") and g["executor_token"].startswith("lt_x_")
    assert g["executor_scopes"] == ["confirm", "otp"] and "confirm" not in g["scopes"]
    only = grant(client, lin, with_executor=False)["data"]
    assert "executor_token" not in only
    listed = {x["grant_id"]: x for x in client.get("/ui/agent-grants", headers=lin.session).json()["data"]}
    assert listed[g["grant_id"]]["executor"] is True and listed[only["grant_id"]]["executor"] is False
    assert "executor_token" not in listed[g["grant_id"]] and "agent_token" not in listed[g["grant_id"]]  # 明文只返回一次
    # Agent 令牌仍然拿不到 confirm/otp；单独的执行器授权接口已移除
    assert grant(client, lin, scopes=["confirm"])["error"]["code"] == "SCOPE_INSUFFICIENT"
    assert client.post("/ui/executor-grants", json={}, headers=lin.session).status_code in (404, 405)


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


def test_revoking_agent_grant_revokes_its_executor(client, lin):
    g = grant(client, lin)["data"]
    agent = {"Authorization": "Bearer " + g["agent_token"]}
    h = {"Authorization": "Bearer " + g["executor_token"]}
    op = lin.transfer("1.00")["data"]["operation_id"]
    assert client.get(f"/api/exec/operations/{op}", headers=h).status_code == 200
    assert client.delete(f"/ui/agent-grants/{g['grant_id']}", headers=lin.session).json()["data"]["revoked"]
    assert client.get(f"/api/exec/operations/{op}", headers=h).json()["error"]["code"] == "AUTH_REVOKED"
    assert client.get("/api/v1/accounts", headers=agent).json()["error"]["code"] == "AUTH_REVOKED"
    assert client.get(f"/api/exec/operations/{op}", headers=lin.executor).status_code == 200  # 其他授权不受影响


def test_audit_links_executor_to_grant_and_filters(client, lin):
    op = lin.transfer("1.00")["data"]["operation_id"]
    client.post(f"/api/exec/operations/{op}/confirm", headers=lin.executor)
    only = client.get("/ui/audit", params={"actor": "executor"}, headers=lin.session).json()["data"]
    assert only and {r["actor"] for r in only} == {"executor"}
    assert only[0]["detail"]["grant_id"] == lin.grant_id  # 与发起 prepare 的 Agent 同一授权编号
    agent_rows = client.get("/ui/audit", params={"actor": "agent"}, headers=lin.session).json()["data"]
    assert any(r["detail"] and r["detail"].get("grant_id") == lin.grant_id for r in agent_rows)
    assert client.get("/ui/audit", params={"actor": "admin"}, headers=lin.session).status_code == 422


def test_logout_revoke_grants_covers_executor(client, lin, exe):
    op = lin.transfer("1.00")["data"]["operation_id"]
    client.post("/ui/logout", params={"revoke_grants": "true"}, headers=lin.session)
    assert client.get(f"/api/exec/operations/{op}", headers=exe).json()["error"]["code"] == "AUTH_REVOKED"


def test_executor_results_are_trimmed_for_llm_context(client, lin, exe):
    op = lin.transfer("500.00")["data"]["operation_id"]
    dialog = client.get(f"/api/exec/operations/{op}", headers=exe).json()["data"]
    assert "balance_after" in dialog["summary"]  # 确认框给用户看：完整视图
    done = client.post(f"/api/exec/operations/{op}/confirm", headers=exe).json()["data"]
    assert done["status"] == "EXECUTED"
    assert "balance_after" not in done["summary"] and "balance_after" not in done["result"]  # 回写上下文：裁剪
    rej = lin.transfer("1.00")["data"]["operation_id"]
    out = client.post(f"/api/exec/operations/{rej}/reject", headers=exe).json()["data"]
    assert out["status"] == "CANCELLED" and "balance_after" not in out["summary"]
    oid = lin.transfer("100.00", payee_id=None, payee_account_no="6217000040003456", payee_name="张三")["data"]["operation_id"]
    v = client.post(f"/api/exec/operations/{oid}/verify-otp", json={"code": "123456"}, headers=exe).json()["data"]
    assert v["status"] == "OTP_VERIFIED" and "balance_after" not in v["summary"]


def test_executor_risk_block_reasons_are_neutral(client, lin, exe):
    a = lin.transfer("600.00")["data"]["operation_id"]
    b = lin.transfer("600.00")["data"]["operation_id"]
    client.put("/api/v1/accounts/acc_001/limits", json={"single_limit": "1000.00", "daily_limit": "1000.00"},
               headers=lin.agent)
    assert client.post(f"/api/exec/operations/{a}/confirm", headers=exe).json()["data"]["status"] == "EXECUTED"
    err = client.post(f"/api/exec/operations/{b}/confirm", headers=exe).json()["error"]
    assert err["code"] == "RISK_BLOCKED"
    daily = next(r for r in err["details"]["reasons"] if r["code"] == "DAILY_LIMIT_EXCEEDED")
    assert daily["params"] == {} and "600.00" not in daily["message"]  # 不向上下文泄露今日已转出
