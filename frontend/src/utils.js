const money = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** "50800.00" → "50,800.00"（后端金额为字符串，仅展示时格式化） */
export function fmtMoney(value) {
  const n = Number(value);
  return Number.isFinite(n) ? money.format(n) : String(value ?? "--");
}

export function fmtTime(iso, withSeconds = false) {
  if (!iso) return "--";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined, hour12: false,
  });
}

export function greeting(date = new Date()) {
  const h = date.getHours();
  if (h < 5) return "夜深了";
  if (h < 11) return "早上好";
  if (h < 13) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
}

export const OP_TYPE = { transfer: "转账", deposit_create: "存入定期", deposit_early_withdraw: "提前支取定期" };

export const OP_STATUS = {
  PREPARED: { text: "待确认", cls: "gold" },
  OTP_PENDING: { text: "待验证", cls: "medium" },
  OTP_VERIFIED: { text: "待确认", cls: "gold" },
  EXECUTED: { text: "已完成", cls: "ok" },
  BLOCKED: { text: "已拦截", cls: "blocked" },
  EXPIRED: { text: "已过期", cls: "muted" },
  CANCELLED: { text: "已取消", cls: "muted" },
  OTP_LOCKED: { text: "已锁定", cls: "blocked" },
  FAILED: { text: "执行失败", cls: "bad" },
};

export const ACTIVE_STATUS = ["PREPARED", "OTP_PENDING", "OTP_VERIFIED"];

export const RISK_LEVEL = {
  low: "低风险", medium: "中风险", high: "高风险", blocked: "已拦截",
};

export const CATEGORY = {
  transfer: "转账", deposit_out: "定期存入", deposit_in: "定期支取", interest: "利息",
  autopay: "自动扣款", salary: "工资", fee: "手续费", other: "消费",
};

export const ACTOR = { agent: "智能助手", user: "用户", system: "系统", admin: "管理", unknown: "未知" };

/** 把后端 summary 的英文键翻成中文标签 */
export const SUMMARY_LABEL = {
  from: "付款账户", to: "收款方", bank: "收款银行", amount: "金额", fee: "手续费", total_debit: "合计扣款",
  balance_after: "操作后余额", memo: "附言", product: "产品", term_months: "期限（月）", annual_rate: "年化利率",
  expected_interest: "到期利息", maturity_date: "到期日", principal: "本金", interest: "提前支取利息",
  interest_loss: "损失利息", total_credit: "到账合计",
};
const MONEY_KEYS = new Set(["amount", "fee", "total_debit", "balance_after", "expected_interest", "principal", "interest", "interest_loss", "total_credit"]);
export const isMoneyKey = (k) => MONEY_KEYS.has(k);

export function errorText(e) {
  return e?.message || "操作失败";
}
