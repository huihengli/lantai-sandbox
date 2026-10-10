"""种子数据：按“能触发每一条风控规则”反向设计，详见《澜台后端方案》§11。

演示账号（密码均为 Lantai@2026）：
  测试1 13800000001（主演示）  测试2 13900000002（归属校验）
  张三 13600000003 / 李四 13700000004（行内收款方）
"""
import random
from datetime import timedelta

from app import clock, config, db
from app.models import (Account, AutopayPlan, Blacklist, Card, DepositHolding, DepositProduct, Payee,
                        Transaction, User)
from app.money import new_id
from app.security.auth import hash_password
from app.services.deposit import add_months

PASSWORD = "Lantai@2026"
OTHER_BANK = ("OTHER", "示例他行")

USERS = [
    ("usr_001", "测试1", "13800000001"), ("usr_002", "测试2", "13900000002"),
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
# 商户 → 商户品类
SHOPS = {"超市": "日用", "便利店": "日用", "地铁出行": "交通", "打车": "交通", "咖啡店": "餐饮", "外卖": "餐饮",
         "书店": "购物", "药房": "医疗", "电影院": "娱乐"}
MONTHS = 14  # 历史流水覆盖月数（供 Agent 做月/年度分析）


def _at(now, days, rng, hour=None):
    """days 天前的时间；指定 hour 时取澜台本地该整点附近。"""
    base = now - timedelta(days=days)
    if hour is None:
        return base - timedelta(minutes=rng.randint(0, 600))
    local = clock.local(base).replace(hour=hour, minute=rng.randint(0, 59), second=0, microsecond=0)
    return local - config.TZ


def _history(db_, now) -> None:
    """生成 14 个月历史流水，保证 balance_after 链条与最终余额一致。

    元素：(时间, 方向, 类别, 金额, 对方, 备注, 商户品类)。固定随机种子，结果可复现。
    周期性扣款的日期与 autopay_plans.next_debit_date 对齐（距今 N 天前 + 30*k）。
    """
    rng = random.Random(42)
    items: dict[str, list[tuple]] = {"acc_001": [], "acc_002": []}
    a1 = items["acc_001"]
    for k in range(MONTHS):
        m = 30 * k
        a1.append((_at(now, 15 + m, rng), "in", "salary", 1_200_000, "澜台科技有限公司", "工资", "收入"))
        a1.append((_at(now, 27 + m, rng), "out", "autopay", 350_000, "房东", "房租自动扣款", "居住"))
        a1.append((_at(now, 25 + m, rng), "out", "autopay", 200_000, "信用卡中心", "信用卡还款", "还款"))
        a1.append((_at(now, 18 + m, rng), "out", "autopay", rng.randint(15_000, 24_000), "水电燃气", "水电费", "生活缴费"))
        a1.append((_at(now, 22 + m, rng), "out", "autopay", 2_500, "澜视频会员", "会员自动续费", "订阅"))
        a1.append((_at(now, 12 + m, rng), "out", "autopay", 900, "澜云盘", "存储自动续费", "订阅"))
        a1.append((_at(now, 5 + m, rng), "out", "autopay", 1_500, "澜音乐", "会员自动续费", "订阅"))
        for _ in range(22):
            shop = rng.choice(list(SHOPS))
            a1.append((_at(now, m + rng.randint(1, 30), rng), "out", "other", rng.randint(1_800, 32_000),
                       shop, None, SHOPS[shop]))
    for days, name, amt, memo in [(33, "李四", 80_000, "还款"), (12, "王五", 150_000, "聚餐AA"),
                                  (100, "李四", 200_000, "借款"), (170, "王五", 120_000, "聚餐AA"),
                                  (250, "李四", 60_000, "还款"), (330, "王五", 90_000, "AA")]:
        a1.append((_at(now, days, rng), "out", "transfer", amt, name, memo, None))
    # 供异常识别演示：一笔明显偏大的消费、一笔凌晨境外消费
    a1.append((_at(now, 70, rng), "out", "other", 880_000, "数码商城", "笔记本电脑", "购物"))
    a1.append((_at(now, 9, rng, hour=3), "out", "other", 320_000, "GLOBAL GIFTS LTD", "境外消费", "购物"))

    items["acc_002"] = [(_at(now, 380, rng), "in", "transfer", 10_000_000, "测试1（他行）", "转入", None),
                        (_at(now, 30, rng), "out", "deposit_out", 2_000_000, "澜台稳盈 3 个月", None, None)]

    for acc_id, rows in items.items():
        acc = db_.get(Account, acc_id)
        bal = acc.balance_cents - sum(a if d == "in" else -a for _, d, _, a, _, _, _ in rows)
        assert bal >= 0, f"{acc_id} 历史起始余额为负，请调整种子"
        for i, (at, d, cat, amt, cp, memo, mcat) in enumerate(sorted(rows, key=lambda x: x[0])):
            at = at.replace(microsecond=i)  # 保证时间唯一，流水顺序（及余额链）可确定
            bal += amt if d == "in" else -amt
            db_.add(Transaction(id=new_id("txn"), account_id=acc_id, direction=d, category=cat,
                                amount_cents=amt, balance_after_cents=bal, counterparty_name=cp,
                                merchant_category=mcat, memo=memo, occurred_at=at))


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
            AutopayPlan(id="apy_001", account_id="acc_001", merchant="房东", amount_cents=350_000,
                        next_debit_date=today + timedelta(days=3), merchant_category="居住"),
            AutopayPlan(id="apy_002", account_id="acc_001", merchant="信用卡中心", amount_cents=200_000,
                        next_debit_date=today + timedelta(days=5), merchant_category="还款"),
            AutopayPlan(id="apy_003", account_id="acc_001", merchant="澜视频会员", amount_cents=2_500,
                        next_debit_date=today + timedelta(days=8), merchant_category="订阅"),
            AutopayPlan(id="apy_004", account_id="acc_001", merchant="澜云盘", amount_cents=900,
                        next_debit_date=today + timedelta(days=18), merchant_category="订阅"),
            AutopayPlan(id="apy_005", account_id="acc_001", merchant="澜音乐", amount_cents=1_500,
                        next_debit_date=today + timedelta(days=25), merchant_category="订阅"),
        ])
        for cid, aid in [("crd_001", "acc_001"), ("crd_002", "acc_002"), ("crd_101", "acc_101")]:
            acc = next(a for a in ACCOUNTS if a[0] == aid)
            s.add(Card(id=cid, user_id=acc[1], account_id=aid, card_no=acc[2], type="debit", status="active",
                       online_enabled=True, overseas_enabled=False, atm_enabled=True,
                       single_limit_cents=config.CARD_DEFAULT_SINGLE_CENTS,
                       daily_limit_cents=config.CARD_DEFAULT_DAILY_CENTS, created_at=now - timedelta(days=400)))
        s.flush()
        _history(s, now)
        s.commit()


def reset_database() -> None:
    db.drop_tables()
    db.create_tables()
    seed()
