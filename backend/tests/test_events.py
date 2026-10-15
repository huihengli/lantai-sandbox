"""模块 7：事件流（只读、递增、按用户隔离）。Agent 靠它做提醒与对账。"""
from tests.conftest import ADMIN, Actor


def feed(client, who, **params):
    return client.get("/api/v1/events", params=params, headers=who.agent).json()["data"]


def kinds(page):
    return [(e["type"], e["data"].get("status") or e["data"].get("change")) for e in page["items"]]


def test_fresh_user_has_empty_feed(client, lin):
    page = feed(client, lin)
    assert page == {"items": [], "next_after_id": 0, "has_more": False, "latest_id": 0}


def test_transfer_emits_operation_and_transaction_events(client, lin):
    op = lin.transfer("500.00")["data"]["operation_id"]
    lin.confirm(op)
    page = feed(client, lin)
    assert [e["type"] for e in page["items"]] == ["operation", "txn_out", "operation"]
    assert page["items"][0]["data"]["status"] == "PREPARED" and page["items"][2]["data"]["status"] == "EXECUTED"
    out = page["items"][1]["data"]
    assert (out["amount"], out["counterparty"], out["operation_id"]) == ("500.00", "李四", op)
    assert "balance_after" not in out
    assert [e["id"] for e in page["items"]] == sorted(e["id"] for e in page["items"])  # 严格递增


def test_incoming_transfer_visible_to_receiver_only(client, lin):
    lin.confirm(lin.transfer("500.00")["data"]["operation_id"])
    li = Actor(client, "13700000004")  # 李四
    page = feed(client, li)
    assert kinds(page) == [("txn_in", None)]
    assert page["items"][0]["data"]["amount"] == "500.00" and page["items"][0]["data"]["counterparty"] == "测试1"
    zhou = Actor(client, "13900000002")
    assert feed(client, zhou)["items"] == []


def test_cursor_pagination_and_type_filter(client, lin):
    for i in range(2):  # 第 3 笔会触发 RAPID_REPEAT 需要 OTP，故只做 2 笔 → 共 6 条事件
        lin.confirm(lin.transfer("10.00", memo=f"n{i}")["data"]["operation_id"])
    first = feed(client, lin, limit=4)
    assert len(first["items"]) == 4 and first["has_more"] is True
    rest = feed(client, lin, after_id=first["next_after_id"], limit=50)
    assert rest["has_more"] is False and len(first["items"]) + len(rest["items"]) == 6
    only_txn = feed(client, lin, types="txn_out")
    assert [e["type"] for e in only_txn["items"]] == ["txn_out"] * 2
    caught_up = feed(client, lin, after_id=rest["latest_id"])
    assert caught_up["items"] == [] and caught_up["next_after_id"] == rest["latest_id"]


def test_otp_and_expiry_and_cancel_events(client, lin):
    op = lin.transfer("2000.00", payee_id=None, payee_account_no="6217000040003456", payee_name="张三")["data"]["operation_id"]
    lin.otp(op)
    expired = lin.transfer("100.00")["data"]["operation_id"]
    cancelled = lin.transfer("100.00", memo="c")["data"]["operation_id"]
    client.post(f"/api/v1/operations/{cancelled}/cancel", headers=lin.agent)
    client.post("/admin/clock", json={"advance_seconds": 301}, headers=ADMIN)
    client.get(f"/api/v1/operations/{expired}", headers=lin.agent)  # 惰性过期
    statuses = [(e["data"]["operation_id"], e["data"]["status"]) for e in feed(client, lin, types="operation")["items"]]
    assert (op, "OTP_PENDING") in statuses and (op, "OTP_VERIFIED") in statuses
    assert (cancelled, "CANCELLED") in statuses and (expired, "EXPIRED") in statuses


def test_otp_locked_event(client, lin):
    op = lin.transfer("2000.00", payee_id=None, payee_account_no="6217000040003456", payee_name="张三")["data"]["operation_id"]
    for _ in range(3):
        lin.otp(op, "000000")
    assert (op, "OTP_LOCKED") in [(e["data"]["operation_id"], e["data"]["status"]) for e in feed(client, lin, types="operation")["items"]]


def test_card_mandate_events(client, lin):
    client.post("/api/v1/cards/crd_001/freeze", headers=lin.agent)
    client.put("/api/v1/accounts/acc_001/limits", json={"single_limit": "1000.00"}, headers=lin.agent)
    m = client.post("/api/v1/mandates/apy_003/cancel/prepare", headers=lin.agent).json()["data"]["operation_id"]
    lin.confirm(m)
    client.post("/admin/mandates/apy_004/charge", headers=ADMIN)
    types = [(e["type"], e["data"].get("status") or e["data"].get("change")) for e in feed(client, lin, limit=100)["items"]]
    assert ("card", "frozen") in types and ("account", "limits") in types
    assert ("mandate", "cancelled") in types and ("txn_out", None) in types


def test_events_require_auth_and_validate_params(client, lin):
    assert client.get("/api/v1/events").status_code == 401
    assert client.get("/api/v1/events", params={"limit": 0}, headers=lin.agent).status_code == 422
    assert client.get("/api/v1/events", params={"after_id": -1}, headers=lin.agent).status_code == 422
