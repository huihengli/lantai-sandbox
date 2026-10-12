"""模块 4：代扣协议（列表、取消）。订阅识别不在银行侧。"""
from tests.conftest import ADMIN, Actor


def mandates(client, lin, **params):
    return client.get("/api/v1/mandates", params=params, headers=lin.agent).json()["data"]


def test_list_mandates(client, lin):
    ms = mandates(client, lin)
    assert [m["merchant"] for m in ms] == ["房东", "信用卡中心", "澜视频会员", "澜云盘", "澜音乐"]  # 按下次扣款日排序
    video = next(m for m in ms if m["merchant"] == "澜视频会员")
    assert video["amount"] == "25.00" and video["cycle"] == "monthly" and video["merchant_category"] == "订阅"
    assert {m["status"] for m in ms} == {"active"}


def test_mandates_match_transaction_history(client, lin):
    """代扣协议与流水可交叉核对：Agent 凭此识别订阅。"""
    txns = client.get("/api/v1/accounts/acc_001/transactions", params={"merchant_category": "订阅", "limit": 100},
                      headers=lin.agent).json()["data"]["items"]
    assert {t["counterparty"] for t in txns} == {m["merchant"] for m in mandates(client, lin, status="active")
                                                  if m["merchant_category"] == "订阅"}


def test_cancel_requires_user_confirmation(client, lin):
    op = client.post("/api/v1/mandates/apy_003/cancel/prepare", headers=lin.agent).json()
    assert op["data"]["status"] == "PREPARED" and op["data"]["risk"]["reasons"][0]["code"] == "MANDATE_CANCEL"
    assert op["data"]["summary"]["merchant"] == "澜视频会员"
    assert next(m for m in mandates(client, lin) if m["id"] == "apy_003")["status"] == "active"  # 未确认前不变
    assert client.post(f"/ui/operations/{op['data']['operation_id']}/confirm", headers=lin.agent).status_code == 403
    assert lin.confirm(op["data"]["operation_id"])["data"]["status"] == "EXECUTED"
    cancelled = mandates(client, lin, status="cancelled")
    assert [m["id"] for m in cancelled] == ["apy_003"] and cancelled[0]["cancelled_at"]
    again = client.post("/api/v1/mandates/apy_003/cancel/prepare", headers=lin.agent).json()
    assert again["error"]["code"] == "MANDATE_NOT_ACTIVE"


def test_mandate_ownership(client, lin):
    zhou = Actor(client, "13900000002")
    assert mandates(client, zhou) == []
    r = client.post("/api/v1/mandates/apy_001/cancel/prepare", headers=zhou.agent)
    assert r.status_code == 404 and r.json()["error"]["code"] == "RESOURCE_NOT_OWNED"


def test_admin_charge_creates_recurring_transaction(client, lin):
    before = lin.balance()
    r = client.post("/admin/mandates/apy_003/charge", headers=ADMIN).json()["data"]
    assert r["balance_after"] == "50775.00"
    assert next(m for m in mandates(client, lin) if m["id"] == "apy_003")["next_debit_date"] == r["next_debit_date"]
    first = client.get("/api/v1/accounts/acc_001/transactions", params={"limit": 1}, headers=lin.agent).json()["data"]["items"][0]
    assert first["counterparty"] == "澜视频会员" and first["category"] == "autopay" and first["amount"] == "25.00"
    assert before == "50800.00"


def test_cancelled_mandate_cannot_be_charged_and_drops_out_of_risk(client, lin):
    op = client.post("/api/v1/mandates/apy_001/cancel/prepare", headers=lin.agent).json()
    lin.confirm(op["data"]["operation_id"])
    assert client.post("/admin/mandates/apy_001/charge", headers=ADMIN).json()["error"]["code"] == "MANDATE_NOT_ACTIVE"
    r = lin.transfer("49000.00")  # 房租协议已取消，仅剩信用卡 2000 元在 7 天内；转后余额 1800 < 2000
    ui = client.get(f"/ui/operations/{r['data']['operation_id']}", headers=lin.session).json()["data"]
    risk = next(x for x in ui["risk"]["reasons"] if x["code"] == "AUTOPAY_AT_RISK")
    assert "房东" not in risk["message"] and "信用卡中心" in risk["message"]
