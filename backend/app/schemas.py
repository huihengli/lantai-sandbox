from typing import Literal

from pydantic import BaseModel, Field


class AgentContext(BaseModel):
    """Agent 提供的上下文，仅写入审计，不参与任何风控判定。"""
    intent_summary: str | None = Field(None, max_length=500)
    user_utterance_excerpt: str | None = Field(None, max_length=500)


class PrepareBase(BaseModel):
    idempotency_key: str | None = Field(None, max_length=100)
    agent_context: AgentContext | None = None


class TransferIn(PrepareBase):
    from_account_id: str = Field(max_length=40)
    payee_id: str | None = Field(None, max_length=40)
    payee_account_no: str | None = Field(None, max_length=32)
    payee_name: str | None = Field(None, max_length=64)
    payee_phone: str | None = Field(None, max_length=20)  # 行内手机号收款：需同时给出完整户名核验
    bank_code: str | None = Field(None, max_length=20)
    bank_name: str | None = Field(None, max_length=40)
    amount: str = Field(max_length=24)
    currency: str = Field("CNY", max_length=8)
    memo: str | None = Field(None, max_length=200)


class DepositIn(PrepareBase):
    account_id: str = Field(max_length=40)
    product_id: str = Field(max_length=40)
    amount: str = Field(max_length=24)


class EarlyWithdrawIn(PrepareBase):
    holding_id: str | None = Field(None, max_length=40)  # 由路径参数填充


class LoginIn(BaseModel):
    phone: str = Field(max_length=32)
    password: str = Field(max_length=128)


class GrantIn(BaseModel):
    scopes: list[str] = Field(max_length=5, default=["read", "prepare", "protect"])
    ttl_seconds: int | None = Field(None, gt=0)


class ExecutorGrantIn(BaseModel):
    scopes: list[str] = Field(max_length=2, default=["confirm", "otp"])
    ttl_seconds: int | None = Field(None, gt=0)


class OtpIn(BaseModel):
    code: str = Field(max_length=10)


class ClockIn(BaseModel):
    set_time: str | None = Field(None, max_length=40)  # ISO8601，不带时区视为澜台本地时间
    advance_seconds: float | None = None


class BlacklistIn(BaseModel):
    account_no: str = Field(max_length=32)
    bank_code: str = Field("LANTAI", max_length=20)
    reason_code: str = Field("SCAM_REPORTED", max_length=40)
    source: str = Field("管理员录入", max_length=60)


class PayeeIn(BaseModel):
    account_no: str = Field(max_length=32)
    name: str = Field(max_length=64)
    bank_code: str = Field("LANTAI", max_length=20)
    bank_name: str | None = Field(None, max_length=40)
    alias: str | None = Field(None, max_length=32)


class PayeePatch(BaseModel):
    alias: str | None = Field(None, max_length=32)


class CardApplyIn(PrepareBase):
    account_id: str = Field(max_length=40)


class CardOnlyIn(PrepareBase):
    card_id: str | None = Field(None, max_length=40)  # 由路径参数填充


class CardControlsIn(PrepareBase):
    card_id: str | None = Field(None, max_length=40)
    online: bool | None = None
    overseas: bool | None = None
    atm: bool | None = None


class CardLimitsIn(PrepareBase):
    card_id: str | None = Field(None, max_length=40)
    single_limit: str | None = Field(None, max_length=24)
    daily_limit: str | None = Field(None, max_length=24)


class AccountLimitsIn(PrepareBase):
    account_id: str | None = Field(None, max_length=40)
    single_limit: str | None = Field(None, max_length=24)
    daily_limit: str | None = Field(None, max_length=24)


class MandateCancelIn(PrepareBase):
    mandate_id: str | None = Field(None, max_length=40)  # 由路径参数填充


class HoldIn(BaseModel):
    amount: str = Field(max_length=24)
    purpose: str | None = Field(None, max_length=60)
    until: str | None = Field(None, max_length=40)  # ISO8601 日期/时间；留空表示直到释放


class HoldReleaseIn(PrepareBase):
    hold_id: str | None = Field(None, max_length=40)  # 由路径参数填充


class MerchantPayIn(PrepareBase):
    card_id: str = Field(max_length=40)
    merchant_id: str = Field(max_length=40)
    amount: str = Field(max_length=24)
    order_ref: str = Field(..., min_length=1, max_length=60)  # 订单号：同一商户同一订单号只能支付一次
    channel: Literal["online", "offline"] = "online"


class WealthSubscribeIn(PrepareBase):
    account_id: str = Field(max_length=40)
    product_id: str = Field(max_length=40)
    amount: str = Field(max_length=24)


class WealthRedeemIn(PrepareBase):
    holding_id: str = Field(max_length=40)
    shares: str | None = Field(None, max_length=16)  # 缺省 = 全部赎回；最多两位小数
    account_id: str | None = Field(None, max_length=40)  # 缺省 = 原申购账户


class RiskAnswersIn(BaseModel):
    answers: dict[str, int] = Field(max_length=30)


class NavIn(BaseModel):
    nav: str = Field(max_length=16)  # 如 "1.0600"，最多四位小数
