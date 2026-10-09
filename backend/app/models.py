"""数据表定义。金额一律为整数分；时间为 naive UTC。"""
from datetime import date, datetime

from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

HOME_BANK = "LANTAI"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    phone_masked: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(200))
    risk_profile: Mapped[str] = mapped_column(String(20), default="normal")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (CheckConstraint("balance_cents >= 0"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    account_no: Mapped[str] = mapped_column(String(32), unique=True)
    type: Mapped[str] = mapped_column(String(20))
    bank_code: Mapped[str] = mapped_column(String(20), default=HOME_BANK)
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    balance_cents: Mapped[int] = mapped_column(BigInteger)
    daily_limit_cents: Mapped[int] = mapped_column(BigInteger)
    single_limit_cents: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    user: Mapped[User] = relationship()


class Payee(Base):
    __tablename__ = "payees"
    __table_args__ = (UniqueConstraint("user_id", "account_no", "bank_code"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    account_no: Mapped[str] = mapped_column(String(32))
    bank_code: Mapped[str] = mapped_column(String(20))
    bank_name: Mapped[str] = mapped_column(String(64))
    first_paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("idx_txn_acc_time", "account_id", "occurred_at"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    direction: Mapped[str] = mapped_column(String(8))  # in / out
    category: Mapped[str] = mapped_column(String(20))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    fee_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    balance_after_cents: Mapped[int] = mapped_column(BigInteger)
    counterparty_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counterparty_account_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    memo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    operation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)


class DepositProduct(Base):
    __tablename__ = "deposit_products"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    term_months: Mapped[int] = mapped_column(Integer)
    annual_rate_bp: Mapped[int] = mapped_column(Integer)
    min_amount_cents: Mapped[int] = mapped_column(BigInteger)
    max_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    early_rate_bp: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="on_sale")


class DepositHolding(Base):
    __tablename__ = "deposit_holdings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("deposit_products.id"))
    principal_cents: Mapped[int] = mapped_column(BigInteger)
    start_date: Mapped[date] = mapped_column(Date)
    maturity_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="holding")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    interest_paid_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    product: Mapped[DepositProduct] = relationship()
    account: Mapped[Account] = relationship()


class AutopayPlan(Base):
    __tablename__ = "autopay_plans"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    merchant: Mapped[str] = mapped_column(String(64))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    next_debit_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")


class PendingOperation(Base):
    __tablename__ = "pending_operations"
    __table_args__ = (Index("idx_op_user_status", "user_id", "status"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(32))
    params_json: Mapped[str] = mapped_column(Text)
    params_hash: Mapped[str] = mapped_column(String(64))
    summary_json: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(10))
    required_action: Mapped[str] = mapped_column(String(10))
    risk_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    initiator: Mapped[str] = mapped_column(String(10))
    agent_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("pending_operations.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    demo_code: Mapped[str] = mapped_column(String(10))  # 模拟短信内容，仅 /ui 通道可见
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(10), default="issued")
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(20))  # user_session / agent_token
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    scopes: Mapped[str] = mapped_column(String(200))
    issued_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Blacklist(Base):
    __tablename__ = "blacklist"
    __table_args__ = (UniqueConstraint("account_no", "bank_code"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_no: Mapped[str] = mapped_column(String(32))
    bank_code: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(60), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("idx_audit_user_ts", "user_id", "ts"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor: Mapped[str] = mapped_column(String(10))
    channel: Mapped[str] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(60))
    operation_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    agent_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String(10))
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
