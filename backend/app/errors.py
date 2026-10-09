"""统一业务异常与错误码 → HTTP 状态码映射。"""

_STATUS = {
    "AUTH_INVALID": 401, "AUTH_EXPIRED": 401, "AUTH_REVOKED": 401,
    "CHANNEL_NOT_ALLOWED": 403, "SCOPE_INSUFFICIENT": 403, "USER_FROZEN": 403,
    "ACCOUNT_FROZEN": 403, "ACCOUNT_CLOSED": 403,
    "RESOURCE_NOT_OWNED": 404, "PAYEE_NOT_FOUND": 404, "OPERATION_NOT_FOUND": 404,
    "AMOUNT_INVALID": 422, "CURRENCY_UNSUPPORTED": 422, "INSUFFICIENT_BALANCE": 422,
    "SAME_ACCOUNT": 422, "PRODUCT_NOT_AVAILABLE": 422, "AMOUNT_BELOW_MIN": 422,
    "AMOUNT_ABOVE_MAX": 422, "VALIDATION_ERROR": 422,
    "HOLDING_NOT_ACTIVE": 409, "IDEMPOTENCY_CONFLICT": 409, "OPERATION_EXPIRED": 409,
    "OPERATION_STATE_INVALID": 409, "PARAMS_TAMPERED": 409, "RISK_BLOCKED": 409,
    "OTP_REQUIRED": 403, "OTP_INVALID": 400, "OTP_LOCKED": 403, "OTP_EXPIRED": 400,
    "EXECUTION_FAILED": 500, "INTERNAL_ERROR": 500,
}


class LantaiError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = _STATUS.get(code, 400)
        self.details = details or {}
