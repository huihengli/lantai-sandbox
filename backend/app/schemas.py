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
    payee_phone: str | None = None  # 行内手机号收款：需同时给出完整户名核验
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
    scopes: list[str] = ["read", "prepare", "protect"]
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


class PayeeIn(BaseModel):
    account_no: str
    name: str
    bank_code: str = "LANTAI"
    bank_name: str | None = None
    alias: str | None = Field(None, max_length=32)


class PayeePatch(BaseModel):
    alias: str | None = Field(None, max_length=32)


class CardApplyIn(PrepareBase):
    account_id: str


class CardOnlyIn(PrepareBase):
    card_id: str | None = None  # 由路径参数填充


class CardControlsIn(PrepareBase):
    card_id: str | None = None
    online: bool | None = None
    overseas: bool | None = None
    atm: bool | None = None


class CardLimitsIn(PrepareBase):
    card_id: str | None = None
    single_limit: str | None = None
    daily_limit: str | None = None


class AccountLimitsIn(PrepareBase):
    account_id: str | None = None
    single_limit: str | None = None
    daily_limit: str | None = None


class MandateCancelIn(PrepareBase):
    mandate_id: str | None = None  # 由路径参数填充
