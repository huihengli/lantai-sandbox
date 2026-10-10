"""模块 5：资金预留。创建直接生效（收紧），释放需用户确认（放宽）。"""
from datetime import date, timedelta

from tests.conftest import ADMIN, Actor

IN_30_DAYS = (date.today() + timedelta(days=30)).isoformat()


def hold(client, lin, amount="1000.00", acc="acc_001", **kw):
    return client.post(f"/api/v1/accounts/{acc}/holds", json={"amount": amount, **kw}, headers=lin.agent)


def bal(client, lin, acc="acc_001"):
    return client.get(f"/api/v1/accounts/{acc}/balance", headers=lin.agent).json()["data"]


def test_create_hold_reduces_available_not_balance(client, lin):
    r = hold(client, lin, purpose="爱人生日", until=IN_30_DAYS).json()["data"]
    assert r["hold"]["status"] == "active" and r["hold"]["created_by"] == "agent" and r["available_after"] == "49800.00"
    b = bal(client, lin)
    assert (b["balance"], b["held"], b["available"]) == ("50800.00", "1000.00", "49800.00")
    listed = client.get("/api/v1/accounts/acc_001/holds", headers=lin.agent).json()["data"]
    assert [h["purpose"] for h in listed] == ["爱人生日"]


def test_held_funds_cannot_be_transferred_or_deposited(client, lin):
    hold(client, lin, "10000.00")
    r = lin.transfer("45000.00")  # 可用 40800
    assert r["error"]["code"] == "INSUFFICIENT_BALANCE" and r["error"]["details"]["available"] == "40800.00"
    assert lin.transfer("40800.00")["data"]["status"] in ("PREPARED", "OTP_PENDING")
    d = client.post("/api/v1/deposits/prepare", json={"account_id": "acc_001", "product_id": "prd_3m", "amount": "45000.00"},
                    headers=lin.agent).json()
    assert d["error"]["code"] == "INSUFFICIENT_BALANCE"


def test_hold_created_after_prepare_blocks_confirm(client, lin):
    op = lin.transfer("40000.00")["data"]["operation_id"]
    hold(client, lin, "20000.00")  # 可用降为 30800
    r = lin.confirm(op)
    assert r["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert client.get(f"/api/v1/operations/{op}", headers=lin.agent).json()["data"]["status"] == "FAILED"
    assert lin.balance() == "50800.00"


def test_risk_uses_available_balance(client, lin):
    hold(client, lin, "10000.00")  # 可用 40800；42000 本就 > 80%，改用 33000：33000/40800=80.9% > 80%
    codes = [x["code"] for x in lin.transfer("33000.00")["data"]["risk"]["reasons"]]
    assert "HIGH_BALANCE_RATIO" in codes
    assert "HIGH_BALANCE_RATIO" not in [x["code"] for x in lin.transfer("32000.00")["data"]["risk"]["reasons"]]  # 78.4%


def test_release_requires_user_confirmation(client, lin):
    hid = hold(client, lin, "1000.00").json()["data"]["hold"]["id"]
    op = client.post(f"/api/v1/holds/{hid}/release/prepare", headers=lin.agent).json()
    assert op["data"]["status"] == "PREPARED" and op["data"]["risk"]["reasons"][0]["code"] == "HOLD_RELEASE"
    assert bal(client, lin)["held"] == "1000.00"  # 未确认前仍预留
    assert client.post(f"/ui/operations/{op['data']['operation_id']}/confirm", headers=lin.agent).status_code == 403
    assert lin.confirm(op["data"]["operation_id"])["data"]["status"] == "EXECUTED"
    b = bal(client, lin)
    assert (b["held"], b["available"]) == ("0.00", "50800.00")
    assert client.post(f"/api/v1/holds/{hid}/release/prepare", headers=lin.agent).json()["error"]["code"] == "HOLD_NOT_ACTIVE"


def test_hold_expires_lazily(client, lin):
    hold(client, lin, "1000.00", until=IN_30_DAYS)
    client.post("/admin/clock", json={"advance_seconds": 90 * 86400}, headers=ADMIN)
    # 令牌 30 分钟过期，重新登录
    lin2 = Actor(client)
    assert bal(client, lin2)["held"] == "0.00"
    h = client.get("/api/v1/accounts/acc_001/holds", params={"status": "expired"}, headers=lin2.agent).json()["data"]
    assert len(h) == 1


def test_hold_validations(client, lin):
    assert hold(client, lin, "99999.00").json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert hold(client, lin, "0").json()["error"]["code"] == "AMOUNT_INVALID"
    assert hold(client, lin, until="2020-01-01").json()["error"]["code"] == "VALIDATION_ERROR"
    assert hold(client, lin, until="2099-01-01").json()["error"]["code"] == "VALIDATION_ERROR"
    assert hold(client, lin, until="not-a-date").json()["error"]["code"] == "VALIDATION_ERROR"
    for _ in range(10):
        assert hold(client, lin, "10.00").status_code == 200
    assert hold(client, lin, "10.00").json()["error"]["code"] == "HOLD_LIMIT_REACHED"


def test_hold_ownership_and_scope(client, lin):
    zhou = Actor(client, "13900000002")
    assert hold(client, zhou, acc="acc_001").json()["error"]["code"] == "RESOURCE_NOT_OWNED"
    hid = hold(client, lin).json()["data"]["hold"]["id"]
    r = client.post(f"/api/v1/holds/{hid}/release/prepare", headers=zhou.agent)
    assert r.json()["error"]["code"] == "RESOURCE_NOT_OWNED"
    g = client.post("/ui/agent-grants", json={"scopes": ["read", "prepare"]}, headers=lin.session).json()["data"]
    weak = {"Authorization": "Bearer " + g["agent_token"]}
    r = client.post("/api/v1/accounts/acc_001/holds", json={"amount": "1.00"}, headers=weak)
    assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_INSUFFICIENT"


def test_mandate_charge_respects_hold(client, lin):
    hold(client, lin, "50700.00")  # 可用仅 100 元
    r = client.post("/admin/mandates/apy_001/charge", headers=ADMIN).json()  # 房租 3500
    assert r["error"]["code"] == "INSUFFICIENT_BALANCE"
