"""模块 3：卡片与额度。原则：收紧立即生效，放宽需用户确认。"""
from tests.conftest import ADMIN, Actor


def post(client, lin, path, json=None):
    return client.post(f"/api/v1{path}", json=json or {}, headers=lin.agent).json()


def put(client, lin, path, json):
    return client.put(f"/api/v1{path}", json=json, headers=lin.agent)


def card(client, lin, cid="crd_001"):
    return client.get(f"/api/v1/cards/{cid}", headers=lin.agent).json()["data"]


def finish(lin, op):
    """用户通道：需要 OTP 则先验证，再确认。"""
    if op["data"]["status"] == "OTP_PENDING":
        lin.otp(op["data"]["operation_id"])
    return lin.confirm(op["data"]["operation_id"])


def reasons(op):
    return [r["code"] for r in op["data"]["risk"]["reasons"]]


def test_list_cards_masked(client, lin):
    cards = client.get("/api/v1/cards", headers=lin.agent).json()["data"]
    assert {c["id"] for c in cards} == {"crd_001", "crd_002"}
    c = card(client, lin)
    assert c["card_no_masked"] == "****1001" and c["status"] == "active"
    assert c["controls"] == {"online": True, "overseas": False, "atm": True}
    assert "6217000010001001" not in str(c)


def test_freeze_is_direct_idempotent_and_audited(client, lin):
    r = post(client, lin, "/cards/crd_001/freeze")
    assert r["data"]["changed"] is True and r["data"]["card"]["status"] == "frozen"
    assert post(client, lin, "/cards/crd_001/freeze")["data"]["changed"] is False
    audit = client.get("/ui/audit", headers=lin.session).json()["data"]
    assert any(a["action"] == "card_freeze" and a["actor"] == "agent" for a in audit)


def test_unfreeze_needs_user_confirmation_and_otp(client, lin):
    post(client, lin, "/cards/crd_001/freeze")
    op = post(client, lin, "/cards/crd_001/unfreeze/prepare")
    assert op["data"]["status"] == "OTP_PENDING" and "CARD_UNFREEZE" in reasons(op)
    assert op["data"]["summary"]["change"] == "已冻结 → 正常"
    assert lin.confirm(op["data"]["operation_id"])["error"]["code"] == "OTP_REQUIRED"
    assert finish(lin, op)["data"]["status"] == "EXECUTED"
    assert card(client, lin)["status"] == "active"
    # 状态不符时不能再解冻
    assert post(client, lin, "/cards/crd_001/unfreeze/prepare")["error"]["code"] == "CARD_STATE_INVALID"


def test_admin_lock_then_unlock(client, lin):
    client.post("/admin/cards/crd_001/lock", headers=ADMIN)
    assert card(client, lin)["status"] == "locked"
    assert post(client, lin, "/cards/crd_001/freeze")["error"]["code"] == "CARD_STATE_INVALID"
    op = post(client, lin, "/cards/crd_001/unfreeze/prepare")
    assert op["data"]["summary"]["action"] == "解锁卡片"
    finish(lin, op)
    assert card(client, lin)["status"] == "active"


def test_report_loss_then_reissue_once(client, lin):
    assert post(client, lin, "/cards/crd_001/report-loss")["data"]["card"]["status"] == "lost"
    assert post(client, lin, "/cards/crd_001/freeze")["error"]["code"] == "CARD_STATE_INVALID"
    assert put(client, lin, "/cards/crd_001/controls", {"online": False}).json()["error"]["code"] == "CARD_STATE_INVALID"
    op = post(client, lin, "/cards/crd_001/reissue/prepare")
    assert "CARD_REISSUE" in reasons(op)
    res = finish(lin, op)["data"]["result"]
    new_id = res["card_id"]
    assert card(client, lin)["replaced_by"] == new_id
    assert card(client, lin, new_id)["status"] == "active" and card(client, lin, new_id)["card_no_masked"] != "****1001"
    assert post(client, lin, "/cards/crd_001/reissue/prepare")["error"]["code"] == "CARD_STATE_INVALID"
    assert post(client, lin, "/cards/crd_002/reissue/prepare")["error"]["code"] == "CARD_STATE_INVALID"  # 未挂失


def test_controls_tighten_direct_loosen_needs_confirm(client, lin):
    ok = put(client, lin, "/cards/crd_001/controls", {"online": False, "atm": False}).json()
    assert ok["data"]["card"]["controls"] == {"online": False, "overseas": False, "atm": False}
    denied = put(client, lin, "/cards/crd_001/controls", {"overseas": True})
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert card(client, lin)["controls"]["overseas"] is False
    op = post(client, lin, "/cards/crd_001/controls/prepare", {"overseas": True, "online": True})
    assert op["data"]["status"] == "OTP_PENDING" and set(reasons(op)) == {"CONTROL_OVERSEAS_ON", "CONTROL_LOOSEN"}
    finish(lin, op)
    assert card(client, lin)["controls"] == {"online": True, "overseas": True, "atm": False}
    assert put(client, lin, "/cards/crd_001/controls", {}).json()["data"]["changed"] is False


def test_card_limits_lower_direct_raise_needs_confirm(client, lin):
    assert put(client, lin, "/cards/crd_001/limits", {"single_limit": "1000.00"}).json()["data"]["card"]["limits"] == {"single": "1000.00", "daily": "50000.00"}
    assert put(client, lin, "/cards/crd_001/limits", {"daily_limit": "60000.00"}).json()["error"]["code"] == "CONFIRM_REQUIRED"
    op = post(client, lin, "/cards/crd_001/limits/prepare", {"daily_limit": "60000.00"})
    assert "LIMIT_RAISE" in reasons(op) and op["data"]["status"] == "OTP_PENDING"
    finish(lin, op)
    assert card(client, lin)["limits"]["daily"] == "60000.00"


def test_limit_validations(client, lin):
    assert put(client, lin, "/cards/crd_001/limits", {}).json()["error"]["code"] == "VALIDATION_ERROR"
    assert put(client, lin, "/cards/crd_001/limits", {"single_limit": "60000.00"}).json()["error"]["code"] == "VALIDATION_ERROR"  # 单笔 > 单日
    assert post(client, lin, "/cards/crd_001/limits/prepare", {"daily_limit": "900000.00"})["error"]["code"] == "AMOUNT_ABOVE_MAX"
    assert put(client, lin, "/cards/crd_001/limits", {"single_limit": "abc"}).json()["error"]["code"] == "AMOUNT_INVALID"


def test_account_limits_affect_transfer_risk(client, lin):
    r = put(client, lin, "/accounts/acc_001/limits", {"single_limit": "1000.00"}).json()
    assert r["data"]["limits"]["single"] == "1000.00"
    blocked = lin.transfer("2000.00")
    assert blocked["data"]["status"] == "BLOCKED" and "SINGLE_LIMIT_EXCEEDED" in reasons(blocked)
    assert put(client, lin, "/accounts/acc_001/limits", {"single_limit": "9000.00"}).json()["error"]["code"] == "CONFIRM_REQUIRED"
    op = post(client, lin, "/accounts/acc_001/limits/prepare", {"single_limit": "9000.00"})
    assert "LIMIT_RAISE" in reasons(op)
    finish(lin, op)
    assert lin.transfer("2000.00")["data"]["status"] == "PREPARED"


def test_apply_card_and_quota(client, lin):
    for _ in range(2):
        op = post(client, lin, "/cards/apply/prepare", {"account_id": "acc_001"})
        assert op["data"]["status"] == "PREPARED" and reasons(op) == ["CARD_APPLY"]  # 低风险，仅需确认
        assert finish(lin, op)["data"]["status"] == "EXECUTED"
    assert len([c for c in client.get("/api/v1/cards", headers=lin.agent).json()["data"] if c["account_id"] == "acc_001"]) == 3
    assert post(client, lin, "/cards/apply/prepare", {"account_id": "acc_001"})["error"]["code"] == "CARD_QUOTA_REACHED"
    assert post(client, lin, "/cards/apply/prepare", {"account_id": "acc_101"})["error"]["code"] == "RESOURCE_NOT_OWNED"


def test_cards_ownership_and_scope(client, lin):
    zhou = Actor(client, "13900000002")
    assert client.get("/api/v1/cards/crd_001", headers=zhou.agent).status_code == 404
    assert client.post("/api/v1/cards/crd_001/freeze", headers=zhou.agent).json()["error"]["code"] == "RESOURCE_NOT_OWNED"
    # 未授予 protect 的 Agent 令牌不能直接冻结
    g = client.post("/ui/agent-grants", json={"scopes": ["read", "prepare"]}, headers=lin.session).json()["data"]
    weak = {"Authorization": "Bearer " + g["agent_token"]}
    r = client.post("/api/v1/cards/crd_001/freeze", headers=weak)
    assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_INSUFFICIENT"
    # 但仍可走 prepare 流程
    assert client.post("/api/v1/cards/apply/prepare", json={"account_id": "acc_001"}, headers=weak).status_code == 200


def test_grant_rejects_unknown_scope(client, lin):
    r = client.post("/ui/agent-grants", json={"scopes": ["read", "confirm"]}, headers=lin.session).json()
    assert r["error"]["code"] == "SCOPE_INSUFFICIENT"
