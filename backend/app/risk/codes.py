"""风控原因码：级别、给用户的文案、给 Agent 的解释方向（agent_hint 仅为建议，非指令）。"""
SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "blocked": 3}

# code: (severity, message 模板, agent_hint)
CATALOG: dict[str, tuple[str, str, str]] = {
    "BLACKLIST_HIT": ("blocked", "该收款账户已被列入涉诈风险名单，交易被拦截",
                      "不要尝试换渠道或拆分金额；建议用户核实对方身份并联系反诈热线 96110"),
    "SINGLE_LIMIT_EXCEEDED": ("blocked", "超过账户单笔转出限额 {limit} 元",
                              "告知用户单笔限额，可建议分笔或线下办理"),
    "DAILY_LIMIT_EXCEEDED": ("blocked", "超过账户单日累计转出限额 {limit} 元（今日已转出 {used} 元）",
                             "告知用户今日剩余额度，建议明日再试"),
    "NEW_PAYEE": ("medium", "首次向该收款人转账", "向用户说明并提醒核实对方身份"),
    "LARGE_AMOUNT": ("high", "金额达到大额交易标准（{threshold} 元）", "提醒用户再次确认金额"),
    "HIGH_BALANCE_RATIO": ("high", "本次转出超过账户余额的 {ratio}", "询问资金用途，留意是否被诱导清空账户"),
    "RAPID_REPEAT": ("medium", "{window} 分钟内已发生多笔转出", "询问是否被人催促连续转账"),
    "PAYEE_NAME_MISMATCH": ("high", "填写的收款人户名与该账户实际户名不一致", "提示用户核对对方姓名与账号"),
    "NIGHT_TRANSACTION": ("low", "当前为夜间时段（0~6 点）", "提示用户确认是否本人操作"),
    "AUTOPAY_AT_RISK": ("low", "转出后余额可能不足以覆盖 {days} 天内的自动扣款（{items}）",
                        "告知具体扣款项与日期"),
    "CROSS_BANK_FEE": ("low", "跨行转账将收取手续费 {fee} 元", "向用户说明手续费"),
    "CARD_APPLY": ("low", "将为该账户新增一张借记卡", "提醒用户新卡需妥善保管"),
    "CARD_UNFREEZE": ("medium", "解冻/解锁卡片后，卡片渠道的交易将恢复", "确认是用户本人要求解冻，且已排除盗刷风险"),
    "CARD_REISSUE": ("medium", "补发新卡，原卡号将作废", "确认用户已挂失原卡"),
    "CONTROL_LOOSEN": ("medium", "将打开以下交易开关：{items}", "确认用户确有使用需求"),
    "CONTROL_OVERSEAS_ON": ("high", "将打开境外交易，存在被盗刷风险", "提醒仅在出境期间开启，用完及时关闭"),
    "LIMIT_RAISE": ("high", "单日额度将由 {old} 元提高到 {new} 元，被盗刷或诈骗时的潜在损失同步扩大", "询问提额原因，建议按需、临时提额"),
    "MANDATE_CANCEL": ("low", "取消后「{merchant}」将无法继续从该账户扣款，下次扣款日 {date} 前如仍需要服务，可能导致中断或逾期",
                       "提醒用户确认是否已在商户侧处理（如房租、信用卡还款需另行安排）"),
    "EARLY_WITHDRAW_LOSS": ("low", "提前支取将损失利息 {loss} 元（到期可得 {full} 元，现仅 {early} 元）",
                            "对比到期日期，建议用户权衡"),
}


def reason(code: str, **params: str) -> dict:
    severity, message, hint = CATALOG[code]
    return {"code": code, "severity": severity, "message": message.format(**params),
            "agent_hint": hint, "params": params}
