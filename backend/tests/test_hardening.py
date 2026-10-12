"""安全加固回归：并发重复执行（F-01/F-02）、最小披露（F-03）、登录防暴破（F-04）、管理接口门控（F-05）。"""
import pytest
from sqlalchemy.orm.attributes import set_committed_value

from app import clock, config
from app.db import SessionLocal
from app.errors import LantaiError
from app.models import DepositHolding, User
from app.security import auth, ratelimit
from app.services import audit, deposit, operation
from tests.conftest import ADMIN, Actor
from tests.test_wealth import finish, holdings, red, sub


def _stale_confirm(lin, op_id, monkeypatch):
    """模拟并发：另一请求在对方执行完毕后才进入 confirm，但读到的仍是执行前的 PREPARED 快照。"""
    assert lin.confirm(op_id)["data"]["status"] == "EXECUTED"
    orig = operation.get_op

    def stale(db, user_id, oid):
        op = orig(db, user_id, oid)
        set_committed_value(op, "status", "PREPARED")
        return op

    monkeypatch.setattr(operation, "get_op", stale)
    db = SessionLocal()
    user = db.get(User, "usr_001")
    out = operation.confirm(audit.Ctx(db, "req_t", user.id, "user", "ui"), user, op_id)
    db.commit()
    db.close()
    return out


def test_f01_stale_confirm_does_not_execute_twice(client, lin, monkeypatch):
    op = lin.transfer("500.00")["data"]["operation_id"]
    out = _stale_confirm(lin, op, monkeypatch)
    assert out["status"] == "EXECUTED"
    assert lin.balance() == "50300.00"  # 只扣一次


def test_f01_early_withdraw_twice_via_two_operations(client, lin):
    a = client.post("/api/v1/deposits/hld_001/early-withdraw/prepare", headers=lin.agent).json()["data"]["operation_id"]
    b = client.post("/api/v1/deposits/hld_001/early-withdraw/prepare", headers=lin.agent).json()["data"]["operation_id"]
    before = client.get("/api/v1/accounts/acc_002/balance", headers=lin.agent).json()["data"]["balance"]
    for op in (a, b):
        if lin.confirm(op).get("error", {}).get("code") == "OTP_REQUIRED":
            lin.otp(op)
            lin.confirm(op)
    after = client.get("/api/v1/accounts/acc_002/balance", headers=lin.agent).json()["data"]["balance"]
    assert float(after) - float(before) == pytest.approx(20003.29, abs=0.02)  # 仅入账一次
    assert client.get(f"/ui/operations/{b}", headers=lin.session).json()["data"]["status"] == "FAILED"


def test_f01_redeem_twice_via_two_operations(client, lin):
    finish(lin, sub(client, lin, "wp_mix", "1231.00"))
    hid = holdings(client, lin)[0]["id"]
    ops = [red(client, lin, hid)["data"]["operation_id"] for _ in range(2)]
    for op in ops:
        lin.confirm(op)
    assert lin.balance() == "50800.00"  # 申购 1231 + 赎回 1231，仅一次入账
    assert holdings(client, lin)[0]["shares"] == "0.00"


def test_f02_settlement_claim_is_atomic(client, lin):
    db = SessionLocal()
    stale = db.get(DepositHolding, "hld_001")  # 旧快照
    deposit._claim(db, stale, "matured", clock.now(), 100)
    with pytest.raises(LantaiError):  # 第二次认领失败 → 不会重复入账
        deposit._claim(db, stale, "matured", clock.now(), 100)
    db.rollback()
    db.close()


def test_f02_matured_deposit_credited_once(client, lin):
    clock.set_time(clock.now().replace(tzinfo=None) + __import__("datetime").timedelta(days=120))
    lin2 = Actor(client)
    first = lin2.c.get("/api/v1/accounts/acc_002/balance", headers=lin2.agent).json()["data"]["balance"]
    again = lin2.c.get("/api/v1/accounts/acc_002/balance", headers=lin2.agent).json()["data"]["balance"]
    assert first == again


def test_f03_prepare_only_token_learns_no_balance(client, lin):
    g = client.post("/ui/agent-grants", json={"scopes": ["prepare"]}, headers=lin.session).json()["data"]
    h = {"Authorization": "Bearer " + g["agent_token"]}
    r = client.post("/api/v1/transfers/prepare", headers=h,
                    json={"from_account_id": "acc_001", "payee_id": "pye_001", "amount": "999999.00"}).json()
    assert r["error"]["code"] == "INSUFFICIENT_BALANCE" and r["error"]["details"] == {}
    assert "50800" not in str(r) and "balance" not in r["error"]["details"]
    ok = client.post("/api/v1/transfers/prepare", headers=h,
                     json={"from_account_id": "acc_001", "payee_id": "pye_001", "amount": "100.00"}).json()["data"]
    assert "balance_after" not in ok["summary"]
    op = ok["operation_id"]
    lin.confirm(op)
    got = client.get(f"/api/v1/operations/{op}", headers=lin.agent).json()["data"]
    assert "balance_after" not in got["result"]
    ui = client.get(f"/ui/operations/{op}", headers=lin.session).json()["data"]
    assert "balance_after" in ui["result"]  # 用户通道仍可见


def test_f03_balance_message_does_not_reveal_holds(client, lin):
    client.post("/api/v1/accounts/acc_001/holds", json={"amount": "50000.00"}, headers=lin.agent)
    msg = lin.transfer("5000.00")["error"]["message"]
    assert msg == "余额不足"  # 不区分「可用余额不足」，避免暴露资金预留


def test_f04_login_lockout_and_no_user_oracle(client):
    for _ in range(config.LOGIN_FAIL_LIMIT_PHONE):
        r = client.post("/ui/login", json={"phone": "13800000001", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/ui/login", json={"phone": "13800000001", "password": "Lantai@2026"})
    assert r.status_code == 429  # 锁定期内连正确口令也拒绝
    ghost = [client.post("/ui/login", json={"phone": "13899990000", "password": "x"}).status_code
             for _ in range(config.LOGIN_FAIL_LIMIT_PHONE + 1)]
    assert ghost[0] == 401 and ghost[-1] == 429  # 不存在的手机号同样限频


def test_f04_password_hash_upgrade(client, lin):
    new = auth.hash_password("pw")
    assert new.startswith(f"pbkdf2${config.PASSWORD_ITERATIONS}$") and auth.verify_password("pw", new)
    legacy = auth.hashlib.pbkdf2_hmac("sha256", b"pw", b"salt", auth.LEGACY_ITERATIONS).hex()
    legacy = f"salt${legacy}"
    assert auth.verify_password("pw", legacy) and not auth.verify_password("no", legacy) and auth.needs_rehash(legacy)
    with SessionLocal() as db:
        u = db.get(User, "usr_001")
        u.password_hash = legacy
        db.commit()
    assert client.post("/ui/login", json={"phone": "13800000001", "password": "Lantai@2026"}).status_code == 401
    with SessionLocal() as db:
        db.get(User, "usr_001").password_hash = f"salt${auth.hashlib.pbkdf2_hmac('sha256', b'Lantai@2026', b'salt', auth.LEGACY_ITERATIONS).hex()}"
        db.commit()
    assert client.post("/ui/login", json={"phone": "13800000001", "password": "Lantai@2026"}).status_code == 200
    with SessionLocal() as db:
        assert not auth.needs_rehash(db.get(User, "usr_001").password_hash)  # 登录成功后已升级


def test_f05_admin_disabled_returns_404(client, monkeypatch):
    assert client.get("/admin/audit", headers=ADMIN).status_code == 200
    monkeypatch.setattr(config, "ADMIN_ENABLED", False)
    r = client.get("/admin/audit", headers=ADMIN)
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


# ---------------- P2 / P3 ----------------
def _new_payee_transfer(lin):
    return lin.transfer("100.00", payee_id=None, payee_account_no="6217000040003456", payee_name="张三")


def test_f06_otp_hash_is_keyed_and_demo_hint_gated(client, lin, monkeypatch):
    from app.models import OtpChallenge
    op = _new_payee_transfer(lin)["data"]
    assert op["status"] == "OTP_PENDING"
    with SessionLocal() as db:
        ch = db.query(OtpChallenge).filter_by(operation_id=op["operation_id"]).one()
        import hashlib
        assert ch.code_hash != hashlib.sha256(f"{op['operation_id']}:123456".encode()).hexdigest()  # 非可预计算的裸哈希
    assert client.get(f"/ui/operations/{op['operation_id']}/otp-hint", headers=lin.session).status_code == 200
    monkeypatch.setattr(config, "OTP_DEMO_MODE", False)
    assert client.get(f"/ui/operations/{op['operation_id']}/otp-hint", headers=lin.session).status_code == 404
    from app.security import otp as otp_mod
    with SessionLocal() as db:
        o = db.get(__import__("app.models", fromlist=["PendingOperation"]).PendingOperation, op["operation_id"])
        assert otp_mod.issue(db, o).demo_code == ""  # 非演示模式不存明文


def test_f06_otp_failures_limited_per_user(client, lin):
    for _ in range(config.OTP_USER_FAIL_LIMIT):
        op = _new_payee_transfer(lin)["data"]["operation_id"]
        lin.otp(op, "000000")
    op = _new_payee_transfer(lin)["data"]["operation_id"]
    assert lin.otp(op, "123456")["error"]["code"] == "RATE_LIMITED"


def test_f08_payee_add_rate_limited(client, lin):
    codes = [client.post("/api/v1/payees", json={"account_no": f"62170000999{i:05d}", "name": "x"},
                         headers=lin.agent).status_code for i in range(config.PAYEE_ADD_LIMIT + 1)]
    assert codes[-1] == 429 and set(codes[:-1]) == {404}


def test_f09_pending_cap_body_limit_and_token_rate(client, lin, monkeypatch):
    monkeypatch.setattr(config, "MAX_ACTIVE_OPERATIONS", 3)
    for _ in range(3):
        assert lin.transfer("1.00")["ok"]
    assert lin.transfer("1.00")["error"]["code"] == "TOO_MANY_PENDING"
    big = client.post("/api/v1/payees", content=b"x" * (config.MAX_BODY_BYTES + 1),
                      headers={**lin.agent, "content-type": "application/json"})
    assert big.status_code == 413
    monkeypatch.setattr(config, "TOKEN_RATE_LIMIT", 3)
    ratelimit.reset()
    codes = [client.get("/api/v1/accounts", headers=lin.agent).status_code for _ in range(5)]
    assert codes[:3] == [200] * 3 and codes[-1] == 429


def test_f10_security_headers(client):
    h = client.get("/healthz").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in h["content-security-policy"] and h["referrer-policy"] == "no-referrer"


def test_f12_logout_can_revoke_agent_grants(client, lin):
    assert client.get("/api/v1/accounts", headers=lin.agent).status_code == 200
    client.post("/ui/logout", params={"revoke_grants": "true"}, headers=lin.session)
    assert client.get("/api/v1/accounts", headers=lin.agent).json()["error"]["code"] == "AUTH_REVOKED"


def test_f13_audit_append_only_and_survives_reset(client, lin):
    from app.models import AuditLog
    from app.seed.seed_data import reset_database
    with SessionLocal() as db:
        row = db.query(AuditLog).first()
        row.result = "x"
        with pytest.raises(RuntimeError):
            db.flush()
        db.rollback()
        assert any("client" in (r.detail_json or "") for r in db.query(AuditLog).all())  # 记录来源
        n = db.query(AuditLog).count()
    reset_database(keep_audit=True)
    with SessionLocal() as db:
        assert db.query(AuditLog).count() >= n


def test_f15_like_wildcards_and_lengths(client, lin):
    r = client.get("/api/v1/accounts/acc_001/transactions", params={"keyword": "%"}, headers=lin.agent).json()
    assert r["data"]["items"] == []  # % 按字面匹配，不再匹配全部
    assert client.get("/api/v1/payees", params={"q": "_"}, headers=lin.agent).json()["data"] == []
    long_key = client.post("/api/v1/transfers/prepare", headers={**lin.agent, "Idempotency-Key": "k" * 101},
                           json={"from_account_id": "acc_001", "payee_id": "pye_001", "amount": "1.00"})
    assert long_key.status_code == 422
    too_long = client.post("/api/v1/payees", json={"account_no": "1" * 500, "name": "x"}, headers=lin.agent)
    assert too_long.status_code == 422


def test_f16_blacklist_matches_any_bank(client, lin):
    r = lin.transfer("10.00", payee_id=None, payee_account_no="6222000088886666", payee_name="刘某某", bank_code="SOMEOTHER")
    assert "BLACKLIST_HIT" in [x["code"] for x in r["data"]["risk"]["reasons"]]


def test_f17_idempotent_prepare_race_returns_first_response(client, lin):
    from app.services import idempotency
    with SessionLocal() as db:
        assert idempotency.store(db, "k1", "usr_001", "e", "h", {"a": 1}) is True
        db.commit()
    with SessionLocal() as db:
        assert idempotency.store(db, "k1", "usr_001", "e", "h", {"a": 2}) is False  # 并发抢先 → 不抛 500


def test_f18_static_path_check():
    from app import main
    if hasattr(main, "_inside_dist"):
        assert main._inside_dist(main._DIST + "/index.html") and not main._inside_dist(main._DIST + "-evil/x")
