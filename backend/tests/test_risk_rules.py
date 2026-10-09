"""每条风控规则：按《方案》§11.5 的触发方式逐条验证。"""
import pytest

from app import clock
from tests.conftest import ADMIN, Actor


def codes(res):
    return [r["code"] for r in res["data"]["risk"]["reasons"]]


def test_normal_transfer_low_risk_and_executes(lin):
    r = lin.transfer("500.00")
    d = r["data"]
    assert d["status"] == "PREPARED" and d["risk"]["required_action"] == "confirm" and codes(r) == []
    assert d["confirm_by"] == "user_interface" and d["confirm_url"].endswith(d["operation_id"])
    out = lin.confirm(d["operation_id"])
    assert out["data"]["status"] == "EXECUTED"
    assert lin.balance() == "50300.00"


def test_blacklist_blocks_without_confirm_url(lin):
    r = lin.transfer("1000.00", payee_id=None, payee_account_no="6222000088886666", payee_name="刘某某",
                     bank_code="OTHER")
    assert r["data"]["status"] == "BLOCKED" and "confirm_url" not in r["data"]
    assert "BLACKLIST_HIT" in codes(r)
    assert lin.confirm(r["data"]["operation_id"])["error"]["code"] == "RISK_BLOCKED"
    assert lin.balance() == "50800.00"


def test_single_limit_blocks(lin):
    r = lin.transfer("60000.00", frm="acc_002")
    assert r["data"]["status"] == "BLOCKED" and "SINGLE_LIMIT_EXCEEDED" in codes(r)


def test_daily_limit_blocks_fourth(lin):
    for _ in range(3):
        r = lin.transfer("30000.00", frm="acc_002")
        if r["data"]["status"] == "OTP_PENDING":
            lin.otp(r["data"]["operation_id"])
        assert lin.confirm(r["data"]["operation_id"])["data"]["status"] == "EXECUTED"
    r = lin.transfer("30000.00", frm="acc_002")
    assert r["data"]["status"] == "BLOCKED" and "DAILY_LIMIT_EXCEEDED" in codes(r)


def test_new_payee_needs_otp(lin):
    r = lin.transfer("2000.00", payee_id=None, payee_account_no="6217000040003456", payee_name="张三")
    assert r["data"]["status"] == "OTP_PENDING" and "NEW_PAYEE" in codes(r)
    assert r["data"]["risk"]["required_action"] == "otp"


def test_large_amount_and_ratio(lin):
    assert "LARGE_AMOUNT" in codes(lin.transfer("50000.00", frm="acc_002"))
    r = lin.transfer("42000.00")  # 占余额 82.7%
    assert "HIGH_BALANCE_RATIO" in codes(r)
    assert "HIGH_BALANCE_RATIO" not in codes(lin.transfer("40640.00"))  # 恰好 80%，不触发


def test_rapid_repeat_third_needs_otp(lin):
    for i in range(2):
        r = lin.transfer("100.00")
        assert codes(r) == [] and lin.confirm(r["data"]["operation_id"])["data"]["status"] == "EXECUTED"
    r = lin.transfer("100.00")
    assert "RAPID_REPEAT" in codes(r) and r["data"]["status"] == "OTP_PENDING"


def test_night_is_hint_only(client, lin):
    client.post("/admin/clock", json={"set_time": clock.iso(clock.now())[:10] + "T02:30:00"}, headers=ADMIN)
    r = lin.transfer("500.00")
    assert codes(r) == ["NIGHT_TRANSACTION"] and r["data"]["risk"]["required_action"] == "confirm"


def test_autopay_at_risk_hint(lin):
    r = lin.transfer("46000.00")
    assert "AUTOPAY_AT_RISK" in codes(r)


def test_cross_bank_fee(lin):
    r = lin.transfer("5000.00", payee_id="pye_002")
    assert "CROSS_BANK_FEE" in codes(r) and r["data"]["summary"]["fee"] == "5.00"
    assert lin.confirm(r["data"]["operation_id"])["data"]["status"] == "EXECUTED"
    assert lin.balance() == "45795.00"


def test_name_mismatch(lin):
    r = lin.transfer("1000.00", payee_id=None, payee_account_no="6217000040003456", payee_name="张山")
    assert "PAYEE_NAME_MISMATCH" in codes(r)


def test_early_withdraw_loss(client, lin):
    r = client.post("/api/v1/deposits/hld_001/early-withdraw/prepare", json={}, headers=lin.agent).json()
    assert codes(r) == ["EARLY_WITHDRAW_LOSS"] and r["data"]["status"] == "PREPARED"
    s = r["data"]["summary"]
    assert s["interest"] == "3.29" and s["interest_loss"] == "74.21"  # 20000*0.2%*30/365；到期 20000*1.55%/4=77.50
    assert lin.confirm(r["data"]["operation_id"])["data"]["status"] == "EXECUTED"
    assert lin.balance("acc_002") == "140003.29"


def test_precheck_creates_no_operation(client, lin):
    r = client.post("/api/v1/risk/precheck", json={"from_account_id": "acc_001", "payee_id": "pye_001",
                                                   "amount": "42000.00"}, headers=lin.agent).json()
    assert "HIGH_BALANCE_RATIO" in [x["code"] for x in r["data"]["risk"]["reasons"]]
    ops = client.get("/ui/operations", headers=lin.session).json()["data"]
    assert ops == []


@pytest.mark.parametrize("amount", ["0", "0.00", "-5", "1.234", "abc", "1e3"])
def test_invalid_amount(lin, amount):
    assert lin.transfer(amount)["error"]["code"] == "AMOUNT_INVALID"
