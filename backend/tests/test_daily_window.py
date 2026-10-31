"""日累计口径：只统计澜台本地自然日 [当日 00:00, 次日 00:00) 内的流水。

演示时银行时钟会被往回拨（`docs/演示脚本.md` 的拨钟速查：做下一场前拨回更早的白天）。
回拨之后，之前按"未来日期"记账的流水仍然满足 `occurred_at >= 当日 00:00`：求和没有上界就会被
算进"今天"。实测——11-02 执行了 7 笔转账共 625 元，把时钟拨回 10-31 后
`GET /api/v1/accounts/acc_001/balance` 仍报 `today_transferred_out=625`，可当日流水只有 5 元，
Agent 的日累计基线因此被抬到 635（真实 10 元），安全控制台与风控日限额都跟着错。
"""
from datetime import timedelta

from app import clock
from tests.conftest import ADMIN


def _codes(res: dict) -> list[str]:
    return [r["code"] for r in res["data"]["risk"]["reasons"]]


def _rewind_days(client, days: int) -> None:
    """把银行时钟往回拨整 `days` 天，时辰仍放在白天（避开夜间提示干扰）。"""
    local = clock.local(clock.now()) - timedelta(days=days)
    when = local.replace(hour=14, minute=0, second=0, microsecond=0)
    client.post("/admin/clock", json={"set_time": when.isoformat()}, headers=ADMIN)


def _balance(lin, acc: str = "acc_001") -> dict:
    return lin.c.get(f"/api/v1/accounts/{acc}/balance", headers=lin.agent).json()["data"]


def _finish(lin, res: dict) -> None:
    if res["data"]["status"] == "OTP_PENDING":
        lin.otp(res["data"]["operation_id"])
    assert lin.confirm(res["data"]["operation_id"])["data"]["status"] == "EXECUTED"


def test_today_transferred_out_ignores_rows_recorded_after_the_rewind(client, lin):
    _finish(lin, lin.transfer("500.00"))
    assert _balance(lin)["today_transferred_out"] == "500.00"

    _rewind_days(client, 1)  # 那笔转账现在记在"明天"
    after = _balance(lin)
    assert after["today_transferred_out"] == "0.00"
    assert after["daily_remaining"] == after["daily_limit"]  # 日剩余额度同样不该被未来流水占掉

    # 回拨之后发生的新流水照常计入今日
    _finish(lin, lin.transfer("300.00"))
    assert _balance(lin)["today_transferred_out"] == "300.00"


def test_daily_limit_does_not_count_rows_from_after_the_rewind(client, lin):
    """风控日限额：不能因为"未来那天"的转账而提前拒绝今天的转账。"""
    for _ in range(2):  # 两笔各 30000 元，合计 60000（低于 acc_002 的单笔 50000 与日限额 100000）
        _finish(lin, lin.transfer("30000.00", frm="acc_002"))
    assert _balance(lin, "acc_002")["today_transferred_out"] == "60000.00"

    _rewind_days(client, 1)
    res = lin.transfer("45000.00", frm="acc_002")  # 60000 + 45000 会超日限额；今天只用 45000 则不会
    assert "DAILY_LIMIT_EXCEEDED" not in _codes(res)


def test_card_limit_does_not_count_payments_from_after_the_rewind(client, lin):
    """卡片日限额同一个口径：回拨后不再把"未来那天"的商户支付算进今日已用。"""

    def pay(amount: str, order: str) -> dict:
        return client.post(
            "/api/v1/payments/merchant/prepare",
            headers=lin.agent,
            json={"card_id": "crd_002", "merchant_id": "mch_mart", "amount": amount, "order_ref": order},
        ).json()

    for order in ("ORD-A", "ORD-B"):
        _finish(lin, pay("20000.00", order))
    _rewind_days(client, 1)

    # 卡片日限额 50000：未来那天的 40000 若被算进来，这一笔就超限
    res = pay("20000.00", "ORD-C")
    assert "CARD_LIMIT_EXCEEDED" not in _codes(res)
