"""种子数据：按“能触发每一条风控规则”反向设计，详见《澜台后端方案》§11。

演示账号（密码均为 Lantai@2026）：
  林清 13800000001（主演示）  周敏 13900000002（归属校验）
  张三 13600000003 / 李四 13700000004（行内收款方）
"""
import random
from datetime import timedelta

from app import clock, config, db
from app.models import (Account, AutopayPlan, Blacklist, DepositHolding, DepositProduct, Payee,
                        Transaction, User)
from app.money import new_id
from app.security.auth import hash_password
from app.services.deposit import add_months

PASSWORD = "Lantai@2026"
OTHER_BANK = ("OTHER", "示例他行")

USERS = [
    ("usr_001", "林清", "13800000001"), ("usr_002", "周敏", "13900000002"),
    ("usr_003", "张三", "13600000003"), ("usr_004", "李四", "13700000004"),
]
# id, user, 卡号, 类型, 余额(分)
ACCOUNTS = [
    ("acc_001", "usr_001", "6217000010001001", "demand", 5_080_000),
    ("acc_002", "usr_001", "6217000010001002", "savings", 12_000_000),
    ("acc_101", "usr_002", "6217000020002001", "demand", 800_000),
    ("acc_201", "usr_003", "6217000040003456", "demand", 300_000),
    ("acc_301", "usr_004", "6217000030005678", "demand", 1_500_000),
]
PRODUCTS = [
    ("prd_3m", "澜台稳盈 3 个月", 3, 155, 100_000), ("prd_6m", "澜台稳盈 6 个月", 6, 185, 100_000),
    ("prd_12m", "澜台稳盈 1 年", 12, 215, 500_000), ("prd_36m", "澜台优享 3 年", 36, 275, 1_000_000),
]
SHOPS = ["超市", "地铁出行", "咖啡店", "外卖", "书店", "药房", "便利店", "打车"]


def _history(db_, now) -> None:
    """生成历史流水，保证 balance_after 链条与最终余额一致。"""
    rng = random.Random(42)
    plans: dict[str, list[tuple]] = {
        "acc_001": [(45, "in", "salary", 1_200_000, "澜台科技有限公司", "工资"),
                    (15, "in", "salary", 1_200_000, "澜台科技有限公司", "工资"),
                    (55, "out", "autopay", 350_000, "房东", "房租自动扣款"),
                    (25, "out", "autopay", 350_000, "房东", "房租自动扣款"),
                    (50, "out", "autopay", 200_000, "信用卡中心", "信用卡还款"),
                    (20, "out", "autopay", 200_000, "信用卡中心", "信用卡还款"),
                    (40, "out", "autopay", 18_650, "水电燃气", "水电费"),
                    (10, "out", "autopay", 19_230, "水电燃气", "水电费"),
                    (33, "out", "transfer", 80_000, "李四", "还款"),
                    (12, "out", "transfer", 150_000, "王五", "聚餐AA")],
        "acc_002": [(58, "in", "transfer", 10_000_000, "林清（他行）", "转入"),
                    (30, "out", "deposit_out", 2_000_000, "澜台稳盈 3 个月", None)],
    }
    for _ in range(28):
        plans["acc_001"].append((rng.randint(2, 60), "out", "other", rng.randint(1800, 32000),
                                 rng.choice(SHOPS), None))
    for acc_id, items in plans.items():
        acc = db_.get(Account, acc_id)
        net = sum(a if d == "in" else -a for _, d, _, a, _, _ in items)
        bal = acc.balance_cents - net
        assert bal >= 0, f"{acc_id} 历史起始余额为负，请调整种子"
        for days, d, cat, amt, cp, memo in sorted(items, key=lambda x: -x[0]):
            bal += amt if d == "in" else -amt
            at = now - timedelta(days=days, minutes=rng.randint(0, 600))
            db_.add(Transaction(id=new_id("txn"), account_id=acc_id, direction=d, category=cat,
                                amount_cents=amt, balance_after_cents=bal, counterparty_name=cp,
                                memo=memo, occurred_at=at))


def seed() -> None:
    now = clock.now()
    today = clock.local(now).date()
    pwd = hash_password(PASSWORD)
    with db.SessionLocal() as s:
        for uid, name, phone in USERS:
            s.add(User(id=uid, name=name, phone=phone, phone_masked=phone[:3] + "****" + phone[-4:],
                       password_hash=pwd, created_at=now - timedelta(days=400)))
        s.flush()
        for aid, uid, no, typ, bal in ACCOUNTS:
            s.add(Account(id=aid, user_id=uid, account_no=no, type=typ, bank_code=config.HOME_BANK,
                          balance_cents=bal, single_limit_cents=config.DEFAULT_SINGLE_LIMIT_CENTS,
                          daily_limit_cents=config.DEFAULT_DAILY_LIMIT_CENTS, created_at=now - timedelta(days=400)))
        s.flush()

        s.add_all([
            Payee(id="pye_001", user_id="usr_001", name="李四", account_no="6217000030005678",
                  bank_code=config.HOME_BANK, bank_name="澜台", first_paid_at=now - timedelta(days=33)),
            Payee(id="pye_002", user_id="usr_001", name="王五", account_no="6222000099009012",
                  bank_code=OTHER_BANK[0], bank_name=OTHER_BANK[1], first_paid_at=now - timedelta(days=12)),
        ])
        s.add(Blacklist(id="bl_001", account_no="6222000088886666", bank_code=OTHER_BANK[0],
                        reason_code="SCAM_REPORTED", source="模拟反诈中心（收款人：刘某某）", created_at=now))
        for pid, name, term, rate, minimum in PRODUCTS:
            s.add(DepositProduct(id=pid, name=name, term_months=term, annual_rate_bp=rate,
                                 min_amount_cents=minimum, early_rate_bp=20))
        start = today - timedelta(days=30)
        s.add(DepositHolding(id="hld_001", user_id="usr_001", account_id="acc_002", product_id="prd_3m",
                             principal_cents=2_000_000, start_date=start, maturity_date=add_months(start, 3)))
        s.add_all([
            AutopayPlan(id="apy_001", account_id="acc_001", merchant="房租", amount_cents=350_000,
                        next_debit_date=today + timedelta(days=3)),
            AutopayPlan(id="apy_002", account_id="acc_001", merchant="信用卡还款", amount_cents=200_000,
                        next_debit_date=today + timedelta(days=5)),
        ])
        s.flush()
        _history(s, now)
        s.commit()


def reset_database() -> None:
    db.drop_tables()
    db.create_tables()
    seed()
