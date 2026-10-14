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
    "NIGHT_TRANSACTION": ("low", "当前为夜间时段（0~6 点）", "提示用户确认是否本人操作"),
    "AUTOPAY_AT_RISK": ("low", "转出后余额可能不足以覆盖 {days} 天内的自动扣款（{items}）",
                        "告知具体扣款项与日期"),
    "CROSS_BANK_FEE": ("low", "跨行转账将收取手续费 {fee} 元", "向用户说明手续费"),
    "CARD_APPLY": ("low", "将为该账户新增一张借记卡", "提醒用户新卡需妥善保管"),
    "CARD_UNFREEZE": ("medium", "解冻/解锁卡片后，卡片渠道的交易将恢复", "确认是用户本人要求解冻，且已排除盗刷风险"),
    "AGENT_STEP_UP": ("medium", "智能助手判定本次操作风险较高，要求加强验证（短信验证码）",
                      "已按你的要求升级为短信验证；不要替用户输入或索要验证码"),
    "CARD_REPORT_LOSS": ("low", "挂失后原卡立即作废且不可撤销，需补发新卡才能继续使用",
                         "如需立即止损，可先冻结卡片（立即生效），再请用户确认挂失"),
    "CARD_REISSUE": ("medium", "补发新卡，原卡号将作废", "确认用户已挂失原卡"),
    "CONTROL_LOOSEN": ("medium", "将打开以下交易开关：{items}", "确认用户确有使用需求"),
    "CONTROL_OVERSEAS_ON": ("high", "将打开境外交易，存在被盗刷风险", "提醒仅在出境期间开启，用完及时关闭"),
    "LIMIT_RAISE": ("high", "单日额度将由 {old} 元提高到 {new} 元，被盗刷或诈骗时的潜在损失同步扩大", "询问提额原因，建议按需、临时提额"),
    "MANDATE_CANCEL": ("low", "取消后「{merchant}」将无法继续从该账户扣款，下次扣款日 {date} 前如仍需要服务，可能导致中断或逾期",
                       "提醒用户确认是否已在商户侧处理（如房租、信用卡还款需另行安排）"),
    "HOLD_RELEASE": ("low", "将释放预留的 {amount} 元（用途：{purpose}），释放后这笔资金可被转出或支付",
                     "确认用户是有意提前动用这笔预留，而非被诱导"),
    "CARD_NOT_USABLE": ("blocked", "卡片当前为{status}，无法支付", "引导用户先处理卡片状态（解冻/补发），不要换卡重试以绕过风控"),
    "CONTROL_DISABLED": ("blocked", "该卡片的「{name}」开关已关闭，无法完成本次支付", "如确需支付，可引导用户在确认中心打开对应开关（需验证）"),
    "CARD_LIMIT_EXCEEDED": ("blocked", "超过卡片额度：单笔 {single} 元 / 单日 {daily} 元（今日已用 {used} 元）", "告知额度，建议分日或提额（需验证）"),
    "MERCHANT_RISKY": ("blocked", "该商户已被列入风险名单，支付被拦截", "提醒用户核实商户身份，谨防返利、刷单类诈骗"),
    "NEW_MERCHANT": ("medium", "首次向该商户支付", "提醒用户核实商户与订单"),
    "OVERSEAS_PAYMENT": ("medium", "该商户位于境外", "确认用户知晓境外交易的汇率与风险"),
    "RISK_PROFILE_MISSING": ("blocked", "{status}，请先完成风险测评后再购买理财产品", "引导用户到界面完成风险测评（测评只能由用户本人提交）"),
    "RISK_LEVEL_FORBIDDEN": ("blocked", "产品风险等级 {product} 超出您的风险承受能力 {user} 两级及以上，不适合购买", "不要劝说用户绕过；可推荐风险等级不高于其承受能力的产品"),
    "RISK_LEVEL_MISMATCH": ("high", "产品风险等级 {product} 高于您的风险承受能力 {user}，属于不匹配购买，需特别确认", "明确告知风险，确认用户理解并自愿购买"),
    "NAV_RISK_NOTICE": ("low", "净值型产品不保本，净值会波动，可能出现本金亏损", "向用户说明过往业绩不代表未来表现"),
    "REDEEM_LOSS": ("low", "按当前净值赎回将实现亏损 {loss} 元", "提示用户可考虑继续持有，由其自行决定"),
    "EARLY_WITHDRAW_LOSS": ("low", "提前支取将损失利息 {loss} 元（到期可得 {full} 元，现仅 {early} 元）",
                            "对比到期日期，建议用户权衡"),
}


def reason(code: str, **params: str) -> dict:
    severity, message, hint = CATALOG[code]
    return {"code": code, "severity": severity, "message": message.format(**params),
            "agent_hint": hint, "params": params}
