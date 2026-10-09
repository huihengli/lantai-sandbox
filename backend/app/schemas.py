from pydantic import BaseModel, Field


class AgentContext(BaseModel):
    """Agent 提供的上下文，仅写入审计，不参与任何风控判定。"""
    intent_summary: str | None = None
    user_utterance_excerpt: str | None = None


class PrepareBase(BaseModel):
    idempotency_key: str | None = Field(None, max_length=100)
    agent_context: AgentContext | None = None


class TransferIn(PrepareBase):
    from_account_id: str
    payee_id: str | None = None
    payee_account_no: str | None = None
    payee_name: str | None = None
    bank_code: str | None = None
    bank_name: str | None = None
    amount: str
    currency: str = "CNY"
    memo: str | None = Field(None, max_length=200)


class DepositIn(PrepareBase):
    account_id: str
    product_id: str
    amount: str


class EarlyWithdrawIn(PrepareBase):
    holding_id: str | None = None  # 由路径参数填充


class LoginIn(BaseModel):
    phone: str
    password: str


class GrantIn(BaseModel):
    scopes: list[str] = ["read", "prepare"]
    ttl_seconds: int | None = Field(None, gt=0)


class OtpIn(BaseModel):
    code: str


class ClockIn(BaseModel):
    set_time: str | None = None  # ISO8601，不带时区视为澜台本地时间
    advance_seconds: float | None = None


class BlacklistIn(BaseModel):
    account_no: str
    bank_code: str = "LANTAI"
    reason_code: str = "SCAM_REPORTED"
    source: str = "管理员录入"
