"""模块 8：风险测评、理财申购/赎回与适当性、定期到期结算。"""
from tests.conftest import ADMIN, Actor

ADMIN_NAV = lambda client, pid, nav: client.post(f"/admin/wealth/{pid}/nav", json={"nav": nav}, headers=ADMIN)  # noqa: E731


def sub(client, who, product="wp_mix", amount="1000.00", acc="acc_001"):
    return client.post("/api/v1/wealth/subscribe/prepare", headers=who.agent,
                       json={"account_id": acc, "product_id": product, "amount": amount}).json()


def red(client, who, holding, shares=None):
    body = {"holding_id": holding, **({"shares": shares} if shares else {})}
    return client.post("/api/v1/wealth/redeem/prepare", headers=who.agent, json=body).json()


def codes(r):
    return [x["code"] for x in r["data"]["risk"]["reasons"]]


def finish(who, r):
    if r["data"]["status"] == "OTP_PENDING":
        who.otp(r["data"]["operation_id"])
    return who.confirm(r["data"]["operation_id"])


def holdings(client, who):
    return client.get("/api/v1/wealth/holdings", headers=who.agent).json()["data"]


# ---------------- 风险测评 ----------------
def test_risk_profile_seeded_and_readable(client, lin):
    r = client.get("/api/v1/risk-profile", headers=lin.agent).json()["data"]
    assert (r["status"], r["level"], r["label"], r["max_product_risk"]) == ("valid", 3, "平衡型", 3)
    q = client.get("/api/v1/risk-profile/questionnaire", headers=lin.agent).json()["data"]
    assert len(q["questions"]) == 5 and q["levels"]["5"] == "进取型"


def test_only_user_channel_can_submit_assessment(client, lin):
    answers = {f"q{i}": 4 for i in range(1, 6)}
    denied = client.put("/ui/risk-profile", json={"answers": answers}, headers=lin.agent)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "CHANNEL_NOT_ALLOWED"
    ok = client.put("/ui/risk-profile", json={"answers": answers}, headers=lin.session).json()["data"]
    assert ok["level"] == 5 and ok["score"] == 20 and ok["label"] == "进取型"
    assert client.get("/api/v1/risk-profile", headers=lin.agent).json()["data"]["level"] == 5


def test_assessment_scoring_and_validation(client, lin):
    def level(vals):
        return client.put("/ui/risk-profile", json={"answers": {f"q{i + 1}": v for i, v in enumerate(vals)}}, headers=lin.session).json()["data"]["level"]
    assert level([1, 1, 1, 1, 1]) == 1 and level([2, 2, 2, 2, 2]) == 2 and level([3, 3, 3, 2, 2]) == 3 and level([4, 4, 3, 3, 3]) == 4
    bad = client.put("/ui/risk-profile", json={"answers": {"q1": 1}}, headers=lin.session).json()
    assert bad["error"]["code"] == "VALIDATION_ERROR"
    bad2 = client.put("/ui/risk-profile", json={"answers": {f"q{i}": 9 for i in range(1, 6)}}, headers=lin.session).json()
    assert bad2["error"]["code"] == "VALIDATION_ERROR"


def test_assessment_expires_after_a_year(client, lin):
    client.post("/admin/clock", json={"advance_seconds": 340 * 86400}, headers=ADMIN)
    lin2 = Actor(client)
    r = client.get("/api/v1/risk-profile", headers=lin2.agent).json()["data"]
    assert r["status"] == "expired" and r["max_product_risk"] is None and r["label"] == "平衡型"
    assert "RISK_PROFILE_MISSING" in codes(sub(client, lin2))


# ---------------- 适当性 ----------------
def test_products_carry_suitability(client, lin):
    ps = {p["id"]: p for p in client.get("/api/v1/wealth/products", headers=lin.agent).json()["data"]}
    assert [ps[k]["suitability"] for k in ("wp_money", "wp_bond", "wp_mix", "wp_growth", "wp_tech")] == ["match", "match", "match", "mismatch", "forbidden"]
    assert ps["wp_bond"]["nav"] == "1.0523" and ps["wp_bond"]["risk_label"] == "R2"
    zhou = Actor(client, "13900000002")
    assert {p["suitability"] for p in client.get("/api/v1/wealth/products", headers=zhou.agent).json()["data"]} == {"unassessed"}


def test_suitability_rules(client, lin):
    ok = sub(client, lin, "wp_mix")
    assert ok["data"]["status"] == "PREPARED" and codes(ok) == ["NAV_RISK_NOTICE"]
    mismatch = sub(client, lin, "wp_growth")
    assert mismatch["data"]["status"] == "OTP_PENDING" and "RISK_LEVEL_MISMATCH" in codes(mismatch)
    forbidden = sub(client, lin, "wp_tech")
    assert forbidden["data"]["status"] == "BLOCKED" and "RISK_LEVEL_FORBIDDEN" in codes(forbidden)
    assert lin.confirm(forbidden["data"]["operation_id"])["error"]["code"] == "RISK_BLOCKED"
    money = sub(client, lin, "wp_money")
    assert codes(money) == [] and money["data"]["status"] == "PREPARED"  # R1 货币基金无净值风险提示


def test_unassessed_user_cannot_buy(client, lin):
    zhou = Actor(client, "13900000002")
    r = sub(client, zhou, "wp_money", "100.00", acc="acc_101")
    assert r["data"]["status"] == "BLOCKED" and "RISK_PROFILE_MISSING" in codes(r)
    # 用户本人完成测评后即可购买
    client.put("/ui/risk-profile", json={"answers": {f"q{i}": 1 for i in range(1, 6)}}, headers=zhou.session)
    assert sub(client, zhou, "wp_money", "100.00", acc="acc_101")["data"]["status"] == "PREPARED"


# ---------------- 申购 / 赎回 ----------------
def test_subscribe_creates_holding_and_debits(client, lin):
    r = sub(client, lin, "wp_mix", "1231.00")
    assert r["data"]["summary"]["shares"] == "1000.00 份" and r["data"]["summary"]["nav"] == "1.2310"
    assert finish(lin, r)["data"]["status"] == "EXECUTED"
    assert lin.balance() == "49569.00"
    h = holdings(client, lin)[0]
    assert (h["product"], h["shares"], h["cost"], h["market_value"], h["pnl"], h["pnl_pct"]) == ("均衡混合基金 B", "1000.00", "1231.00", "1231.00", "0.00", "0.00%")
    txn = client.get("/api/v1/accounts/acc_001/transactions", params={"limit": 1}, headers=lin.agent).json()["data"]["items"][0]
    assert (txn["category"], txn["counterparty"], txn["direction"]) == ("wealth_out", "均衡混合基金 B", "out")
    finish(lin, sub(client, lin, "wp_mix", "123.10"))  # 追加申购并入同一持仓
    assert len(holdings(client, lin)) == 1 and holdings(client, lin)[0]["shares"] == "1100.00"


def test_subscribe_validations(client, lin):
    assert sub(client, lin, "wp_bond", "50.00")["error"]["code"] == "AMOUNT_BELOW_MIN"
    assert sub(client, lin, "wp_nope")["error"]["code"] == "PRODUCT_NOT_AVAILABLE"
    assert sub(client, lin, amount="99999.00")["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert sub(client, lin, amount="1.234")["error"]["code"] == "AMOUNT_INVALID"
    assert sub(client, lin, acc="acc_101")["error"]["code"] == "RESOURCE_NOT_OWNED"
    client.post("/api/v1/accounts/acc_001/holds", json={"amount": "50000.00"}, headers=lin.agent)
    assert sub(client, lin, amount="1000.00")["error"]["code"] == "INSUFFICIENT_BALANCE"  # 预留资金不可申购


def test_redeem_with_gain_and_partial(client, lin):
    finish(lin, sub(client, lin, "wp_mix", "1231.00"))
    hid = holdings(client, lin)[0]["id"]
    ADMIN_NAV(client, "wp_mix", "1.3541")  # +10%
    h = holdings(client, lin)[0]
    assert (h["market_value"], h["pnl"], h["pnl_pct"]) == ("1354.10", "123.10", "10.00%")
    part = red(client, lin, hid, "400.00")
    assert part["data"]["summary"]["amount"] == "541.64" and part["data"]["summary"]["pnl"] == "49.24"
    assert "REDEEM_LOSS" not in codes(part)
    assert finish(lin, part)["data"]["status"] == "EXECUTED"
    h = holdings(client, lin)[0]
    assert (h["shares"], h["cost"], h["status"]) == ("600.00", "738.60", "active")
    assert lin.balance() == "50110.64"  # 50800 - 1231 + 541.64
    full = red(client, lin, hid)
    assert full["data"]["summary"]["amount"] == "812.46"
    finish(lin, full)
    closed = holdings(client, lin)[0]
    assert closed["status"] == "closed" and closed["shares"] == "0.00"
    assert red(client, lin, hid)["error"]["code"] == "HOLDING_NOT_ACTIVE"
    assert lin.balance() == "50923.10"


def test_redeem_at_loss_warns(client, lin):
    finish(lin, sub(client, lin, "wp_mix", "1231.00"))
    hid = holdings(client, lin)[0]["id"]
    ADMIN_NAV(client, "wp_mix", "1.1079")  # -10%
    r = red(client, lin, hid)
    assert "REDEEM_LOSS" in codes(r) and "123.10" in r["data"]["risk"]["reasons"][0]["message"]
    assert r["data"]["status"] == "PREPARED"  # 提示类，仅需确认


def test_redeem_validations_and_ownership(client, lin):
    finish(lin, sub(client, lin, "wp_mix", "1231.00"))
    hid = holdings(client, lin)[0]["id"]
    assert red(client, lin, hid, "1000.01")["error"]["code"] == "AMOUNT_ABOVE_MAX"
    assert red(client, lin, hid, "0")["error"]["code"] == "AMOUNT_INVALID"
    assert red(client, lin, hid, "1.234")["error"]["code"] == "AMOUNT_INVALID"
    zhou = Actor(client, "13900000002")
    assert red(client, zhou, hid)["error"]["code"] == "RESOURCE_NOT_OWNED"
    assert ADMIN_NAV(client, "wp_mix", "0").json()["error"]["code"] == "VALIDATION_ERROR"
    assert ADMIN_NAV(client, "wp_mix", "1.23456").json()["error"]["code"] == "VALIDATION_ERROR"


def test_confirm_rechecks_suitability(client, lin):
    r = sub(client, lin, "wp_mix")
    client.put("/ui/risk-profile", json={"answers": {f"q{i}": 1 for i in range(1, 6)}}, headers=lin.session)  # 降为保守型 R1
    out = lin.confirm(r["data"]["operation_id"])
    assert out["error"]["code"] == "RISK_BLOCKED"  # R3 vs R1 相差两级


# ---------------- 定期到期结算 ----------------
def test_matured_deposit_is_settled_lazily(client, lin):
    before = lin.balance("acc_002")
    assert before == "120000.00"
    client.post("/admin/clock", json={"advance_seconds": 62 * 86400}, headers=ADMIN)  # 起息 30 天前 + 3 个月 → 约 92 天
    lin2 = Actor(client)  # 登录/鉴权请求即触发结算
    h = client.get("/api/v1/deposit/holdings", headers=lin2.agent).json()["data"][0]
    assert h["status"] == "matured" and h["interest_paid"] == "77.50"
    assert client.get("/api/v1/accounts/acc_002/balance", headers=lin2.agent).json()["data"]["balance"] == "140077.50"
    items = client.get("/api/v1/accounts/acc_002/transactions", params={"limit": 2}, headers=lin2.agent).json()["data"]["items"]
    assert {(t["category"], t["amount"]) for t in items} == {("deposit_in", "20000.00"), ("interest", "77.50")}
    ev = client.get("/api/v1/events", params={"types": "deposit"}, headers=lin2.agent).json()["data"]["items"]
    assert ev[0]["data"]["status"] == "matured"
    # 只结算一次
    again = client.get("/api/v1/accounts/acc_002/balance", headers=lin2.agent).json()["data"]["balance"]
    assert again == "140077.50"
