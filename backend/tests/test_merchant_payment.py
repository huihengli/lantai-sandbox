"""模块 6：商户支付（卡片 + 商户 + 订单号）。"""
from tests.conftest import Actor


def pay(client, lin, merchant="mch_flower", amount="299.00", order="ORD-1", card="crd_001", **kw):
    return client.post("/api/v1/payments/merchant/prepare", headers=lin.agent, json={
        "card_id": card, "merchant_id": merchant, "amount": amount, "order_ref": order, **kw}).json()


def codes(r):
    return [x["code"] for x in r["data"]["risk"]["reasons"]]


def finish(lin, r):
    if r["data"]["status"] == "OTP_PENDING":
        lin.otp(r["data"]["operation_id"])
    return lin.confirm(r["data"]["operation_id"])


def test_merchant_catalog_hides_risky(client, lin):
    ms = client.get("/api/v1/merchants", headers=lin.agent).json()["data"]
    assert [m["id"] for m in ms] == ["mch_cake", "mch_flower", "mch_global", "mch_mart", "mch_video"]
    assert next(m for m in ms if m["id"] == "mch_global")["overseas"] is True


def test_first_payment_needs_otp_then_executes(client, lin):
    r = pay(client, lin)
    assert r["data"]["status"] == "OTP_PENDING" and codes(r) == ["NEW_MERCHANT"]
    assert r["data"]["summary"]["merchant"] == "澜花坊" and r["data"]["summary"]["order_ref"] == "ORD-1"
    assert finish(lin, r)["data"]["status"] == "EXECUTED"
    assert lin.balance() == "50501.00"
    t = client.get("/api/v1/accounts/acc_001/transactions", params={"limit": 1}, headers=lin.agent).json()["data"]["items"][0]
    assert (t["counterparty"], t["memo"], t["merchant_category"], t["amount"]) == ("澜花坊", "ORD-1", "礼品", "299.00")
    # 第二次向同一商户支付：不再是新商户，仅需确认
    again = pay(client, lin, order="ORD-2")
    assert again["data"]["status"] == "PREPARED" and codes(again) == []


def test_duplicate_order_is_rejected(client, lin):
    finish(lin, pay(client, lin))
    assert pay(client, lin)["error"]["code"] == "ORDER_ALREADY_PAID"
    assert pay(client, lin, merchant="mch_cake")["data"]["status"] in ("PREPARED", "OTP_PENDING")  # 不同商户同订单号不冲突


def test_frozen_or_lost_card_is_blocked(client, lin):
    client.post("/api/v1/cards/crd_001/freeze", headers=lin.agent)
    r = pay(client, lin)
    assert r["data"]["status"] == "BLOCKED" and "CARD_NOT_USABLE" in codes(r) and "confirm_url" not in r["data"]
    assert lin.confirm(r["data"]["operation_id"])["error"]["code"] == "RISK_BLOCKED"
    assert lin.balance() == "50800.00"


def test_online_control_off_blocks_online_but_not_offline(client, lin):
    client.put("/api/v1/cards/crd_001/controls", json={"online": False}, headers=lin.agent)
    r = pay(client, lin)
    assert r["data"]["status"] == "BLOCKED" and "CONTROL_DISABLED" in codes(r)
    assert pay(client, lin, order="ORD-OFF", channel="offline")["data"]["status"] != "BLOCKED"


def test_overseas_requires_control_then_otp(client, lin):
    r = pay(client, lin, merchant="mch_global", order="G-1")
    assert r["data"]["status"] == "BLOCKED" and "CONTROL_DISABLED" in codes(r) and "OVERSEAS_PAYMENT" in codes(r)
    op = client.post("/api/v1/cards/crd_001/controls/prepare", json={"overseas": True}, headers=lin.agent).json()
    lin.otp(op["data"]["operation_id"])
    lin.confirm(op["data"]["operation_id"])
    ok = pay(client, lin, merchant="mch_global", order="G-2")
    assert ok["data"]["status"] == "OTP_PENDING" and codes(ok) == ["OVERSEAS_PAYMENT"]  # 历史已向该商户付过款，非新商户


def test_card_limits_single_and_daily(client, lin):
    assert "CARD_LIMIT_EXCEEDED" in codes(pay(client, lin, card="crd_002", amount="20000.01", order="X"))
    for i in range(2):  # crd_002：单笔 2 万，单日 5 万
        assert finish(lin, pay(client, lin, card="crd_002", merchant="mch_mart", amount="18000.00", order=f"M-{i}"))["data"]["status"] == "EXECUTED"
    third = pay(client, lin, card="crd_002", merchant="mch_mart", amount="18000.00", order="M-3")
    assert third["data"]["status"] == "BLOCKED" and "CARD_LIMIT_EXCEEDED" in codes(third)
    assert "36000.00" not in third["data"]["risk"]["reasons"][0]["message"]  # Agent 通道不披露当日累计
    ui = lin.c.get(f"/ui/operations/{third['data']['operation_id']}", headers=lin.session).json()["data"]
    assert "今日已用 36000.00" in ui["risk"]["reasons"][0]["message"]  # 用户通道保留


def test_risky_merchant_blocked(client, lin):
    r = pay(client, lin, merchant="mch_risky", amount="100.00", order="R-1")
    assert r["data"]["status"] == "BLOCKED" and "MERCHANT_RISKY" in codes(r)
    assert pay(client, lin, merchant="mch_nope")["error"]["code"] == "MERCHANT_NOT_FOUND"


def test_confirm_rechecks_card_state(client, lin):
    r = pay(client, lin, merchant="mch_video", amount="25.00", order="V-1")
    client.post("/api/v1/cards/crd_001/freeze", headers=lin.agent)
    out = lin.confirm(r["data"]["operation_id"])
    assert out["error"]["code"] == "RISK_BLOCKED"
    assert client.get(f"/api/v1/operations/{r['data']['operation_id']}", headers=lin.agent).json()["data"]["status"] == "BLOCKED"


def test_ownership_validation_and_auth(client, lin):
    zhou = Actor(client, "13900000002")
    assert pay(client, zhou, card="crd_001")["error"]["code"] == "RESOURCE_NOT_OWNED"
    bad = client.post("/api/v1/payments/merchant/prepare", headers=lin.agent,
                      json={"card_id": "crd_001", "merchant_id": "mch_cake", "amount": "10.00"})
    assert bad.status_code == 422  # 缺少 order_ref
    assert pay(client, lin, amount="0")["error"]["code"] == "AMOUNT_INVALID"
