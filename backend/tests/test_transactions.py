"""模块 1：流水增强（keyword / counterparty / merchant_category）与 14 个月历史数据。"""
from datetime import datetime, timezone

from sqlalchemy import select

from app import db as dbm
from app.models import Account, Transaction

URL = "/api/v1/accounts/acc_001/transactions"


def items(client, lin, **params):
    params.setdefault("limit", 100)
    return client.get(URL, params=params, headers=lin.agent).json()["data"]["items"]


def test_keyword_matches_memo_and_counterparty(client, lin):
    aa = items(client, lin, keyword="AA")
    assert aa and all("AA" in (t["memo"] or "") or "AA" in (t["counterparty"] or "") for t in aa)
    assert {t["counterparty"] for t in aa} <= {"王五"}
    assert {t["counterparty"] for t in items(client, lin, keyword="视频")} == {"澜视频会员"}


def test_counterparty_filter_and_merchant_category(client, lin):
    assert {t["counterparty"] for t in items(client, lin, counterparty="李四")} == {"李四"}
    food = items(client, lin, merchant_category="餐饮")
    assert food and {t["merchant_category"] for t in food} == {"餐饮"}
    subs = items(client, lin, merchant_category="订阅")
    assert {t["counterparty"] for t in subs} == {"澜视频会员", "澜云盘", "澜音乐"}


def test_history_covers_twelve_months_with_anomalies(client, lin):
    first = None
    cursor = 0
    while cursor is not None:
        page = client.get(URL, params={"limit": 100, "cursor": cursor}, headers=lin.agent).json()["data"]
        first = page["items"][-1]
        cursor = page["next_cursor"]
    assert (datetime.now(timezone.utc) - datetime.fromisoformat(first["occurred_at"])).days > 360
    big = items(client, lin, min_amount="5000.00", direction="out")
    assert any(t["counterparty"] == "数码商城" for t in big)
    assert any(t["counterparty"] == "GLOBAL GIFTS LTD" for t in items(client, lin, keyword="境外"))


def test_balance_chain_is_consistent():
    with dbm.SessionLocal() as s:
        for acc in s.scalars(select(Account).where(Account.id.in_(["acc_001", "acc_002"]))):
            txns = s.scalars(select(Transaction).where(Transaction.account_id == acc.id)
                             .order_by(Transaction.occurred_at, Transaction.id)).all()
            bal = txns[0].balance_after_cents - (txns[0].amount_cents if txns[0].direction == "in" else -txns[0].amount_cents)
            for t in txns:
                bal += t.amount_cents if t.direction == "in" else -t.amount_cents
                assert bal == t.balance_after_cents
            assert bal == acc.balance_cents
