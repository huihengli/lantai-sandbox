"""模块 2：收款人管理与手机号解析。"""
from tests.conftest import Actor

ZHANG = {"account_no": "6217000040003456", "name": "张三"}


def add(client, lin, **kw):
    return client.post("/api/v1/payees", json={**ZHANG, **kw}, headers=lin.agent)


def test_add_payee_then_list_and_search(client, lin):
    r = add(client, lin, alias="三哥").json()["data"]
    assert r["name"] == "张三" and r["alias"] == "三哥" and r["already_exists"] is False
    assert r["account_no_masked"] == "****3456" and r["ever_paid"] is False
    assert "6217000040003456" not in str(r)
    names = lambda q: [p["name"] for p in client.get("/api/v1/payees", params={"q": q}, headers=lin.agent).json()["data"]]  # noqa: E731
    assert names("三哥") == ["张三"] and names("张") == ["张三"] and names("3456") == ["张三"] and names("不存在") == []
    assert add(client, lin).json()["data"]["already_exists"] is True


def test_add_payee_validations(client, lin):
    mismatch = add(client, lin, name="张山").json()["error"]
    assert mismatch["code"] == "PAYEE_NOT_FOUND"
    missing = add(client, lin, account_no="6217000099999999").json()["error"]
    assert missing == {**mismatch, "details": {}} or missing["message"] == mismatch["message"]  # 不存在与户名不符不可区分
    assert add(client, lin, account_no="6217000010001002", name="测试1").json()["error"]["code"] == "SAME_ACCOUNT"
    bl = add(client, lin, account_no="6222000088886666", name="刘某某", bank_code="OTHER")
    assert bl.status_code == 404 and bl.json()["error"]["message"] == mismatch["message"]  # 黑名单不可探测


def test_added_payee_still_triggers_new_payee_otp(client, lin):
    pid = add(client, lin).json()["data"]["id"]
    r = lin.transfer("1000.00", payee_id=pid)
    assert r["data"]["status"] == "OTP_PENDING"
    assert "NEW_PAYEE" in [x["code"] for x in r["data"]["risk"]["reasons"]]


def test_update_alias_and_soft_delete_then_readd(client, lin):
    pid = add(client, lin).json()["data"]["id"]
    r = client.patch(f"/api/v1/payees/{pid}", json={"alias": "老张"}, headers=lin.agent).json()
    assert r["data"]["alias"] == "老张"
    assert client.delete(f"/api/v1/payees/{pid}", headers=lin.agent).json()["data"]["deleted"] is True
    assert pid not in [p["id"] for p in client.get("/api/v1/payees", headers=lin.agent).json()["data"]]
    assert client.patch(f"/api/v1/payees/{pid}", json={"alias": "x"}, headers=lin.agent).json()["error"]["code"] == "PAYEE_NOT_FOUND"
    again = add(client, lin).json()["data"]
    assert again["id"] == pid and again["already_exists"] is False  # 软删除后重新添加，复用原记录


def test_payee_ownership(client, lin):
    zhou = Actor(client, "13900000002")
    assert client.delete("/api/v1/payees/pye_001", headers=zhou.agent).json()["error"]["code"] == "PAYEE_NOT_FOUND"
    assert client.get("/api/v1/payees", headers=zhou.agent).json()["data"] == []


def test_resolve_phone_returns_only_masked_info(client, lin):
    r = client.get("/api/v1/payees/resolve", params={"phone": "13600000003"}, headers=lin.agent).json()["data"]
    assert r["name_masked"] == "张*" and r["phone_masked"] == "136****0003" and r["bank"] == "澜台"
    assert "6217" not in str(r) and "3456" not in str(r)
    miss = client.get("/api/v1/payees/resolve", params={"phone": "13000000000"}, headers=lin.agent)
    assert miss.status_code == 404
    assert client.get("/api/v1/payees/resolve", params={"phone": "123"}, headers=lin.agent).status_code == 422


def test_resolve_phone_rate_limited(client, lin):
    for _ in range(10):
        client.get("/api/v1/payees/resolve", params={"phone": "13600000003"}, headers=lin.agent)
    r = client.get("/api/v1/payees/resolve", params={"phone": "13600000003"}, headers=lin.agent)
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


def test_transfer_by_phone_requires_full_name(client, lin):
    ok = lin.transfer("500.00", payee_id=None, payee_phone="13600000003", payee_name="张三")
    assert ok["data"]["summary"]["to"] == "张三 ****3456"
    assert "PAYEE_NAME_MISMATCH" not in [x["code"] for x in ok["data"]["risk"]["reasons"]]
    bad = lin.transfer("500.00", payee_id=None, payee_phone="13600000003", payee_name="张山")
    assert "PAYEE_NAME_MISMATCH" in [x["code"] for x in bad["data"]["risk"]["reasons"]]
    assert lin.transfer("500.00", payee_id=None, payee_phone="13600000003")["error"]["code"] == "PAYEE_NOT_FOUND"
    assert lin.transfer("500.00", payee_id=None, payee_phone="13000000000", payee_name="x")["error"]["code"] == "PAYEE_NOT_FOUND"
