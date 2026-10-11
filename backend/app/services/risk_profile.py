"""客户风险测评（适当性管理的基础）。

测评结果由银行按答案计算，只能由用户在界面通道提交；Agent 只能读取等级与过期状态。
有效期 12 个月，过期视同未测评。"""
from datetime import timedelta

from app import clock, config
from app.errors import LantaiError
from app.models import User
from app.services import audit, events

LABELS = {1: "保守型", 2: "稳健型", 3: "平衡型", 4: "成长型", 5: "进取型"}

QUESTIONS = [
    {"id": "q1", "text": "您的年龄段是？", "options": [
        {"value": 1, "text": "60 岁以上"}, {"value": 2, "text": "46-60 岁"},
        {"value": 3, "text": "31-45 岁"}, {"value": 4, "text": "30 岁及以下"}]},
    {"id": "q2", "text": "您的投资经验是？", "options": [
        {"value": 1, "text": "几乎没有，主要是存款"}, {"value": 2, "text": "买过货币基金或债券基金"},
        {"value": 3, "text": "买过混合基金或股票基金"}, {"value": 4, "text": "有较丰富的权益类投资经验"}]},
    {"id": "q3", "text": "可用于投资的资金占您家庭可支配资产的比例是？", "options": [
        {"value": 1, "text": "50% 以上"}, {"value": 2, "text": "30%-50%"},
        {"value": 3, "text": "10%-30%"}, {"value": 4, "text": "10% 以下"}]},
    {"id": "q4", "text": "您最多能承受的本金亏损是？", "options": [
        {"value": 1, "text": "不能接受任何亏损"}, {"value": 2, "text": "10% 以内"},
        {"value": 3, "text": "10%-30%"}, {"value": 4, "text": "30% 以上"}]},
    {"id": "q5", "text": "您计划的投资期限是？", "options": [
        {"value": 1, "text": "1 年以内"}, {"value": 2, "text": "1-3 年"},
        {"value": 3, "text": "3-5 年"}, {"value": 4, "text": "5 年以上"}]},
]


def score_to_level(total: int) -> int:
    for limit, level in ((8, 1), (11, 2), (14, 3), (17, 4)):
        if total <= limit:
            return level
    return 5


def current(user: User, now) -> tuple[int | None, str]:
    """返回 (有效等级或 None, 状态 none/valid/expired)。"""
    if user.risk_level is None or user.risk_assessed_at is None:
        return None, "none"
    if now > user.risk_assessed_at + timedelta(days=config.RISK_PROFILE_VALID_DAYS):
        return None, "expired"
    return user.risk_level, "valid"


def view(user: User, now) -> dict:
    level, status = current(user, now)
    return {"status": status, "level": level if level else user.risk_level,
            "label": LABELS.get(user.risk_level) if user.risk_level else None,
            "max_product_risk": level, "assessed_at": clock.iso(user.risk_assessed_at),
            "valid_until": clock.iso(user.risk_assessed_at + timedelta(days=config.RISK_PROFILE_VALID_DAYS))
            if user.risk_assessed_at else None}


def assess(ctx: audit.Ctx, user: User, answers: dict[str, int]) -> dict:
    total = 0
    for q in QUESTIONS:
        v = answers.get(q["id"])
        if v not in {o["value"] for o in q["options"]}:
            raise LantaiError("VALIDATION_ERROR", f"请回答问题 {q['id']}", {"question": q["id"]})
        total += v
    now = clock.now()
    user.risk_level, user.risk_assessed_at = score_to_level(total), now
    audit.log(ctx, "risk_assessment", detail={"score": total, "level": user.risk_level})
    events.emit(ctx.db, user.id, "risk_profile", user.id, {"level": user.risk_level, "label": LABELS[user.risk_level]})
    return {**view(user, now), "score": total}
