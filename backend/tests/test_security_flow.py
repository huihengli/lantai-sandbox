"""校验链、通道隔离、状态机、OTP、幂等、审计、定期、金额守恒。"""
from sqlalchemy import func, select

from app import db as dbm
from app.models import Account
from tests.conftest import ADMIN, Actor

NEW_PAYEE = dict(payee_id=None, payee_account_no="6217000040003456", payee_name="张三")


def test_agent_cannot_confirm_and_it_is_audited(client, lin):
    op = lin.transfer("500.00")["data"]["operation_id"]
    r = client.post(f"/ui/operations/{op}/confirm", headers=lin.agent)
    assert r.status_code == 403 and r.json()["error"]["code"] == "CHANNEL_NOT_ALLOWED"
    assert lin.balance() == "50800.00"
    audit = client.get("/ui/audit", headers=lin.session).json()["data"]
    assert any(a["error_code"] == "CHANNEL_NOT_ALLOWED" and a["actor"] == "agent" for a in audit)


def test_grant_cannot_include_confirm(client, lin):
    r = client.post("/ui/agent-grants", json={"scopes": ["read", "confirm"]}, headers=lin.session)
    assert r.json()["error"]["code"] == "SCOPE_INSUFFICIENT"


def test_cannot_use_other_users_account(client, lin):
    r = client.get("/api/v1/accounts/acc_101/balance", headers=lin.agent)
    assert r.status_code == 404 and r.json()["error"]["code"] == "RESOURCE_NOT_OWNED"
    assert lin.transfer("100.00", frm="acc_101")["error"]["code"] == "RESOURCE_NOT_OWNED"


def test_other_users_operation_invisible(client, lin):
    op = lin.transfer("500.00")["data"]["operation_id"]
    zhou = Actor(client, "13900000002")
    assert client.get(f"/api/v1/operations/{op}", headers=zhou.agent).json()["error"]["code"] == "OPERATION_NOT_FOUND"
    assert zhou.confirm(op)["error"]["code"] == "OPERATION_NOT_FOUND"


def test_auth_errors_and_revoked_grant(client, lin):
    assert client.get("/api/v1/accounts").json()["error"]["code"] == "AUTH_INVALID"
    client.delete(f"/ui/agent-grants/{lin.grant_id}", headers=lin.session)
    assert client.get("/api/v1/accounts", headers=lin.agent).json()["error"]["code"] == "AUTH_REVOKED"


def test_agent_token_expires(client, lin):
    client.post("/admin/clock", json={"advance_seconds": 1801}, headers=ADMIN)
    assert client.get("/api/v1/accounts", headers=lin.agent).json()["error"]["code"] == "AUTH_EXPIRED"


def test_operation_expires(client, lin):
    op = lin.transfer("500.00")["data"]["operation_id"]
    client.post("/admin/clock", json={"advance_seconds": 301}, headers=ADMIN)
    # 用户会话同样 30 分钟有效，仍可用
    assert lin.confirm(op)["error"]["code"] == "OPERATION_EXPIRED"
    assert client.get(f"/api/v1/operations/{op}", headers=lin.agent).json()["data"]["status"] == "EXPIRED"


def test_otp_required_then_verified(lin):
    op = lin.transfer("2000.00", **NEW_PAYEE)["data"]["operation_id"]
    assert lin.confirm(op)["error"]["code"] == "OTP_REQUIRED"
    assert lin.otp(op)["data"]["status"] == "OTP_VERIFIED"
    assert lin.confirm(op)["data"]["status"] == "EXECUTED"
    assert lin.balance() == "48800.00"


def test_otp_locked_after_three_wrong(lin):
    op = lin.transfer("2000.00", **NEW_PAYEE)["data"]["operation_id"]
    assert lin.otp(op, "000000")["error"]["details"]["attempts_left"] == 2
    lin.otp(op, "000000")
    assert lin.otp(op, "000000")["error"]["code"] == "OTP_LOCKED"
    assert lin.otp(op)["error"]["code"] == "OTP_LOCKED"  # 正确码也不再接受
    assert lin.confirm(op)["error"]["code"] == "OTP_LOCKED"


def test_otp_never_visible_to_agent(client, lin):
    r = lin.transfer("2000.00", **NEW_PAYEE)
    op = r["data"]["operation_id"]
    assert "123456" not in str(r)
    assert client.get(f"/api/v1/operations/{op}", headers=lin.agent).text.find("123456") == -1
    assert client.get(f"/ui/operations/{op}/otp-hint", headers=lin.agent).json()["error"]["code"] == "CHANNEL_NOT_ALLOWED"
    assert "123456" in client.get(f"/ui/operations/{op}/otp-hint", headers=lin.session).json()["data"]["sms"]


def test_confirm_is_idempotent_and_single_debit(lin):
    op = lin.transfer("500.00")["data"]["operation_id"]
    lin.confirm(op)
    again = lin.confirm(op)
    assert again["data"]["status"] == "EXECUTED" and lin.balance() == "50300.00"


def test_cancel_and_reject(client, lin):
    op = lin.transfer("500.00")["data"]["operation_id"]
    r = client.post(f"/api/v1/operations/{op}/cancel", headers=lin.agent).json()
    assert r["data"]["status"] == "CANCELLED"
    assert lin.confirm(op)["error"]["code"] == "OPERATION_STATE_INVALID"
    op2 = lin.transfer("500.00")["data"]["operation_id"]
    assert client.post(f"/ui/operations/{op2}/reject", headers=lin.session).json()["data"]["status"] == "CANCELLED"


def test_idempotency_key(client, lin):
    kw = dict(idempotency_key="k-1")
    a = lin.transfer("500.00", **kw)
    b = lin.transfer("500.00", **kw)
    assert a["data"]["operation_id"] == b["data"]["operation_id"]
    assert len(client.get("/ui/operations", headers=lin.session).json()["data"]) == 1
    assert lin.transfer("600.00", **kw)["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_insufficient_balance_and_same_account(lin):
    assert lin.transfer("99999.00", frm="acc_001")["error"]["code"] == "INSUFFICIENT_BALANCE"
    r = lin.transfer("10.00", payee_id=None, payee_account_no="6217000010001001", payee_name="测试1")
    assert r["error"]["code"] == "SAME_ACCOUNT"


def test_transfer_to_own_account_is_not_new_payee(lin):
    r = lin.transfer("1000.00", payee_id=None, payee_account_no="6217000010001002", payee_name="测试1")
    assert r["data"]["status"] == "PREPARED"
    lin.confirm(r["data"]["operation_id"])
    assert lin.balance("acc_002") == "121000.00"


def test_new_payee_saved_after_confirm(client, lin):
    op = lin.transfer("2000.00", **NEW_PAYEE)["data"]["operation_id"]
    lin.otp(op)
    lin.confirm(op)
    names = [p["name"] for p in client.get("/api/v1/payees", headers=lin.agent).json()["data"]]
    assert "张三" in names
    r = lin.transfer("100.00", **NEW_PAYEE)  # 已保存且转过 → 不再是新收款人
    assert "NEW_PAYEE" not in [x["code"] for x in r["data"]["risk"]["reasons"]]


def test_deposit_create_flow(client, lin):
    p = client.get("/api/v1/deposit/products", headers=lin.agent).json()["data"]
    assert [x["id"] for x in p] == ["prd_3m", "prd_6m", "prd_12m", "prd_36m"]
    low = client.post("/api/v1/deposits/prepare", json={"account_id": "acc_001", "product_id": "prd_12m",
                                                        "amount": "1000.00"}, headers=lin.agent).json()
    assert low["error"]["code"] == "AMOUNT_BELOW_MIN"
    r = client.post("/api/v1/deposits/prepare", json={"account_id": "acc_001", "product_id": "prd_12m",
                                                      "amount": "10000.00"}, headers=lin.agent).json()
    assert r["data"]["summary"]["expected_interest"] == "215.00"
    assert lin.confirm(r["data"]["operation_id"])["data"]["status"] == "EXECUTED"
    assert lin.balance() == "40800.00"
    held = client.get("/api/v1/deposit/holdings", headers=lin.agent).json()["data"]
    assert len(held) == 2


def test_amount_conservation(client, lin):
    def total():
        with dbm.SessionLocal() as s:
            return s.scalar(select(func.sum(Account.balance_cents)))

    before = total()
    for amt, payee in (("500.00", "pye_001"), ("5000.00", "pye_002")):
        lin.confirm(lin.transfer(amt, payee_id=payee)["data"]["operation_id"])
    assert before - total() == 500_500  # 跨行转出 5000.00 + 手续费 5.00 离开本系统；行内转账守恒


def test_blacklist_admin_and_reset(client, lin):
    assert client.get("/admin/blacklist").json()["error"]["code"] == "AUTH_INVALID"
    lin.confirm(lin.transfer("500.00")["data"]["operation_id"])
    client.post("/admin/reset", headers=ADMIN)
    lin2 = Actor(client)
    assert lin2.balance() == "50800.00"
    client.post("/admin/blacklist", json={"account_no": "6217000030005678"}, headers=ADMIN)
    assert lin2.transfer("100.00")["data"]["status"] == "BLOCKED"


def test_transactions_filter_and_pagination(client, lin):
    url = "/api/v1/accounts/acc_001/transactions"
    page = client.get(url, params={"limit": 10}, headers=lin.agent).json()["data"]
    assert len(page["items"]) == 10 and page["next_cursor"] == 10
    outs = client.get(url, params={"direction": "in", "limit": 50}, headers=lin.agent).json()["data"]["items"]
    assert {t["direction"] for t in outs} == {"in"} and len(outs) == 2
    big = client.get(url, params={"min_amount": "1000.00", "limit": 50}, headers=lin.agent).json()["data"]["items"]
    assert big and all(float(t["amount"]) >= 1000 for t in big)


def test_openapi_and_spa_fallback(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/transfers/prepare" in paths and "/ui/operations/{op_id}/confirm" in paths
    from app.main import _DIST  # noqa: PLC0415
    import os, pytest  # noqa: E401, PLC0415
    if os.path.isfile(os.path.join(_DIST, "index.html")):
        assert "<div id=\"app\">" in client.get("/confirm/op_x").text
        assert client.get("/api/v1/nope").json()["error"]["code"] == "NOT_FOUND"
