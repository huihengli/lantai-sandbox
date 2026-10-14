"""Agent 加强验证 step_up="otp"：只能变严不能放宽，确认时复核保持，原因码与审计留痕。"""


def codes(r):
    return [x["code"] for x in r["data"]["risk"]["reasons"]]


def test_step_up_raises_confirm_to_otp(client, lin):
    plain = lin.transfer("500.00")["data"]
    assert plain["status"] == "PREPARED" and plain["risk"]["required_action"] == "confirm"
    r = lin.transfer("500.00", step_up="otp")
    d = r["data"]
    assert d["status"] == "OTP_PENDING" and d["risk"]["required_action"] == "otp" and d["risk"]["level"] == "medium"
    assert "AGENT_STEP_UP" in codes(r)


def test_step_up_never_lowers_existing_requirement(client, lin):
    new_payee = dict(payee_id=None, payee_account_no="6217000040003456", payee_name="张三")
    base = lin.transfer("45000.00", **new_payee)["data"]
    up = lin.transfer("45000.00", step_up="otp", **new_payee)["data"]
    assert base["risk"]["required_action"] == up["risk"]["required_action"] == "otp"
    assert up["risk"]["level"] == base["risk"]["level"] == "high"  # 已是 high，不被 AGENT_STEP_UP(medium) 拉低
    blocked = lin.transfer("10.00", payee_id=None, payee_account_no="6222000088886666", payee_name="刘某某",
                           bank_code="OTHER", step_up="otp")["data"]
    assert blocked["status"] == "BLOCKED" and blocked["risk"]["required_action"] == "block"


def test_step_up_only_accepts_otp(client, lin):
    for bad in ("confirm", "none", "OTP", ""):
        r = client.post("/api/v1/transfers/prepare", headers=lin.agent,
                        json={"from_account_id": "acc_001", "payee_id": "pye_001", "amount": "1.00", "step_up": bad})
        assert r.status_code == 422


def test_step_up_survives_confirm_recheck(client, lin):
    op = lin.transfer("500.00", step_up="otp")["data"]["operation_id"]
    assert lin.confirm(op)["error"]["code"] == "OTP_REQUIRED"  # 确认时重新风控仍要求 OTP
    lin.otp(op)
    assert lin.confirm(op)["data"]["status"] == "EXECUTED"
    assert lin.balance() == "50300.00"


def test_step_up_on_other_prepare_endpoints(client, lin):
    r = client.post("/api/v1/deposits/prepare", headers=lin.agent,
                    json={"account_id": "acc_002", "product_id": "prd_3m", "amount": "10000.00", "step_up": "otp"}).json()
    assert r["data"]["status"] == "OTP_PENDING" and "AGENT_STEP_UP" in codes(r)
    client.post("/api/v1/cards/crd_001/freeze", headers=lin.agent)
    r = client.post("/api/v1/cards/crd_001/report-loss/prepare", headers=lin.agent, json={"step_up": "otp"}).json()
    assert r["data"]["status"] == "OTP_PENDING" and "AGENT_STEP_UP" in codes(r)


def test_step_up_in_precheck_and_audit(client, lin):
    pre = client.post("/api/v1/risk/precheck", headers=lin.agent,
                      json={"from_account_id": "acc_001", "payee_id": "pye_001", "amount": "1.00", "step_up": "otp"}).json()
    assert pre["data"]["risk"]["required_action"] == "otp" and "AGENT_STEP_UP" in codes(pre)
    op = lin.transfer("500.00", step_up="otp")["data"]["operation_id"]
    row = next(r for r in client.get("/ui/audit", params={"actor": "agent"}, headers=lin.session).json()["data"]
               if r["operation_id"] == op and r["action"] == "prepare:transfer")
    assert row["detail"]["step_up"] == "otp" and any(x["code"] == "AGENT_STEP_UP" for x in row["risk"]["reasons"])


def test_step_up_is_part_of_idempotency(client, lin):
    body = {"from_account_id": "acc_001", "payee_id": "pye_001", "amount": "1.00"}
    h = {**lin.agent, "Idempotency-Key": "k-step"}
    assert client.post("/api/v1/transfers/prepare", headers=h, json=body).json()["data"]["status"] == "PREPARED"
    r = client.post("/api/v1/transfers/prepare", headers=h, json={**body, "step_up": "otp"}).json()
    assert r["error"]["code"] == "IDEMPOTENCY_CONFLICT"  # 不能用同一幂等键把已创建的操作“加严/放宽”
