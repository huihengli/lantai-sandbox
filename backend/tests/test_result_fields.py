"""接口文档 §4.2：各操作类型 result 的字段口径，以及 executed_at 的时间基准。

两件事固定在这里：
1. result 是白名单：每个 type 只返回文档列出的字段（Agent 通道还额外裁掉 balance_after）；
2. executed_at 走银行时钟（app.clock），时区偏移与 GET /api/v1/clock 的 now 完全一致。
"""
from datetime import datetime, timedelta

from tests.conftest import ADMIN, Actor


def finish(who, r):
    """走完两阶段：需要 OTP 的先验证，再确认；返回确认后的 data。"""
    if r["data"]["status"] == "OTP_PENDING":
        who.otp(r["data"]["operation_id"])
    return who.confirm(r["data"]["operation_id"])["data"]


def bank_offset(client, who):
    now = client.get("/api/v1/clock", headers=who.agent).json()["data"]["now"]
    return datetime.fromisoformat(now).utcoffset()


def assert_bank_time(client, who, ts):
    """executed_at 必须是带偏移的 ISO8601，且偏移与 /api/v1/clock 相同。"""
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None, "executed_at 必须带时区偏移"
    assert parsed.utcoffset() == bank_offset(client, who)


def confirm_and_get(client, who, op):
    """确认后从 Agent 通道重新取操作，断言的就是文档承诺的 Agent 可见 result。"""
    finish(who, op)
    return client.get(f"/api/v1/operations/{op['data']['operation_id']}", headers=who.agent).json()["data"]["result"]


def test_transfer_result(client, lin):
    r = confirm_and_get(client, lin, lin.transfer("2000.00"))
    assert set(r) == {"transaction_id", "fee", "executed_at"}  # balance_after 只在用户通道
    assert r["transaction_id"].startswith("txn_") and r["fee"] == "0.00"  # 行内转账不收费
    assert_bank_time(client, lin, r["executed_at"])


def test_merchant_payment_result(client, lin):
    op = client.post("/api/v1/payments/merchant/prepare", headers=lin.agent, json={
        "card_id": "crd_001", "merchant_id": "mch_flower", "amount": "299.00", "order_ref": "ORD-1"}).json()
    r = confirm_and_get(client, lin, op)
    assert set(r) == {"transaction_id", "order_ref", "fee", "executed_at"}
    assert (r["order_ref"], r["fee"]) == ("ORD-1", "0.00")  # 商户支付不收费，仍返回 fee 以便统一展示
    assert_bank_time(client, lin, r["executed_at"])


def test_deposit_create_and_early_withdraw_result(client, lin):
    op = client.post("/api/v1/deposits/prepare", headers=lin.agent,
                     json={"account_id": "acc_002", "product_id": "prd_3m", "amount": "1000.00"}).json()
    r = confirm_and_get(client, lin, op)
    assert set(r) == {"holding_id", "transaction_id", "maturity_date", "executed_at"}
    assert r["holding_id"].startswith("hld_")
    assert datetime.strptime(r["maturity_date"], "%Y-%m-%d").date() > datetime.fromisoformat(r["executed_at"]).date()
    assert_bank_time(client, lin, r["executed_at"])  # maturity_date 是本地日期，不带偏移

    early = client.post("/api/v1/deposits/hld_001/early-withdraw/prepare", headers=lin.agent).json()
    r = confirm_and_get(client, lin, early)
    assert set(r) == {"holding_id", "principal", "interest", "executed_at"}
    assert (r["holding_id"], r["principal"]) == ("hld_001", "20000.00")
    assert_bank_time(client, lin, r["executed_at"])


def test_wealth_subscribe_and_redeem_result(client, lin):
    op = client.post("/api/v1/wealth/subscribe/prepare", headers=lin.agent,
                     json={"account_id": "acc_001", "product_id": "wp_mix", "amount": "1231.00"}).json()
    sub = confirm_and_get(client, lin, op)
    assert set(sub) == {"holding_id", "transaction_id", "shares", "nav", "executed_at"}
    assert (sub["shares"], sub["nav"]) == ("1000.00", "1.2310")  # 1231.00 / 1.2310 = 1000 份
    assert_bank_time(client, lin, sub["executed_at"])

    op = client.post("/api/v1/wealth/redeem/prepare", headers=lin.agent,
                     json={"holding_id": sub["holding_id"]}).json()
    red = confirm_and_get(client, lin, op)
    assert set(red) == {"holding_id", "transaction_id", "shares", "nav", "amount", "pnl", "executed_at"}
    assert (red["shares"], red["nav"], red["amount"]) == ("1000.00", "1.2310", "1231.00")  # 份额×净值可复核金额
    assert_bank_time(client, lin, red["executed_at"])


def test_card_results(client, lin):
    apply_op = client.post("/api/v1/cards/apply/prepare", headers=lin.agent, json={"account_id": "acc_001"}).json()
    r = confirm_and_get(client, lin, apply_op)
    assert set(r) == {"card_id", "card_no_masked", "status", "status_text", "executed_at"}
    assert (r["status"], r["status_text"]) == ("active", "正常") and r["card_no_masked"].startswith("****")

    loss = confirm_and_get(client, lin, client.post("/api/v1/cards/crd_001/report-loss/prepare",
                                                    headers=lin.agent).json())
    assert (loss["card_no_masked"], loss["status_text"]) == ("****1001", "已挂失")
    assert_bank_time(client, lin, loss["executed_at"])

    reissue = confirm_and_get(client, lin, client.post("/api/v1/cards/crd_001/reissue/prepare",
                                                       headers=lin.agent).json())
    assert reissue["card_id"] != "crd_001" and reissue["status_text"] == "正常"

    client.post("/api/v1/cards/crd_002/freeze", headers=lin.agent)
    unfreeze = confirm_and_get(client, lin, client.post("/api/v1/cards/crd_002/unfreeze/prepare",
                                                        headers=lin.agent).json())
    assert (unfreeze["card_no_masked"], unfreeze["status_text"]) == ("****1002", "正常")


def test_card_controls_and_limits_result_carry_card_snapshot(client, lin):
    op = client.post("/api/v1/cards/crd_002/limits/prepare", headers=lin.agent,
                     json={"daily_limit": "60000.00"}).json()
    limits = confirm_and_get(client, lin, op)
    assert set(limits) == {"card", "executed_at"}
    assert (limits["card"]["card_no_masked"], limits["card"]["status_text"]) == ("****1002", "正常")
    assert limits["card"]["limits"]["daily"] == "60000.00"

    op = client.post("/api/v1/cards/crd_002/controls/prepare", headers=lin.agent, json={"overseas": True}).json()
    controls = confirm_and_get(client, lin, op)
    assert set(controls) == {"card", "executed_at"}
    assert controls["card"]["status_text"] == "正常" and controls["card"]["controls"]["overseas"] is True
    assert_bank_time(client, lin, controls["executed_at"])


def test_account_limits_and_mandate_cancel_result(client, lin):
    op = client.post("/api/v1/accounts/acc_001/limits/prepare", headers=lin.agent,
                     json={"daily_limit": "60000.00"}).json()
    r = confirm_and_get(client, lin, op)
    assert set(r) == {"account_id", "limits", "executed_at"}
    assert (r["account_id"], r["limits"]["daily"]) == ("acc_001", "60000.00")
    assert_bank_time(client, lin, r["executed_at"])

    op = client.post("/api/v1/mandates/apy_003/cancel/prepare", headers=lin.agent).json()
    m = confirm_and_get(client, lin, op)
    assert set(m) == {"mandate_id", "merchant", "status", "executed_at"}
    assert (m["mandate_id"], m["merchant"], m["status"]) == ("apy_003", "澜视频会员", "cancelled")


def test_executed_at_follows_bank_clock_not_agent_host(client, lin):
    """演示时钟可被快进：executed_at 必须跟着银行时钟走，且与 /api/v1/clock 同时区。"""
    t0 = datetime.fromisoformat(client.get("/api/v1/clock", headers=lin.agent).json()["data"]["now"])
    client.post("/admin/clock", json={"advance_seconds": 6 * 3600}, headers=ADMIN)
    fresh = Actor(client)  # 快进后旧令牌已过期，重新登录签发
    before = datetime.fromisoformat(client.get("/api/v1/clock", headers=fresh.agent).json()["data"]["now"])
    r = finish(fresh, fresh.transfer("100.00"))["result"]
    after = datetime.fromisoformat(client.get("/api/v1/clock", headers=fresh.agent).json()["data"]["now"])
    at = datetime.fromisoformat(r["executed_at"])
    assert at.utcoffset() == t0.utcoffset() == before.utcoffset() == after.utcoffset()  # 同一时区偏移
    assert at - t0 >= timedelta(hours=6)  # 跟着被快进的银行时钟，而不是本机时间
    assert before - timedelta(seconds=1) <= at <= after + timedelta(seconds=1)  # 落在两次取时的区间内
