# 澜台 Agent 接口文档（MCP 服务器接入用）

> 更新日期：2026-10-14　版本：与后端 1.0.0 同步（共 44 个 Agent 通道接口），已包含安全加固后的对外行为
> 本文由脚本从运行中的 FastAPI 应用提取接口与请求结构，并补充手写说明生成。开发环境可对照 `GET /openapi.json`；生产模式该接口默认关闭，以本文为准。本文用于指导 MCP 工具的设计。

## 目录

- 0. 相对上一版（2026-10-12）的变更
- 1. 定位与硬性约束
- 2. 接入与认证
- 3. 统一响应与错误码
- 4. 核心流程：prepare → 用户确认 → 查询结果
- 5. 风控结果与原因码
- 6. 事件流
- 7. 接口参考
- 8. MCP 工具设计建议
- 9. Agent 行为守则
- 10. 演示数据速查
- 11. 不属于 Agent 的接口

## 0. 相对上一版（2026-10-12）的变更

以下变更来自安全加固（并发修复、最小披露、限频、输入校验）。**接口路径、请求结构、scope 均未变**，但响应内容与错误行为有变化，MCP 实现需要对应调整。

| 类别 | 变化 | 对 Agent / MCP 的影响 |
|---|---|---|
| 最小披露 | `INSUFFICIENT_BALANCE` 不再带 `balance/available`，文案不再区分“可用余额不足/余额不足” | 需要余额时调用 `get_balance`；不要从错误里解析数字 |
| 最小披露 | Agent 视图的 `summary`、`result` 不含 `balance_after`；事件流不含余额；`create_hold` 不再返回 `available_after` | 对账改用 `get_balance` 与事件里的金额/流水号 |
| 最小披露 | `DAILY_LIMIT_EXCEEDED`、`CARD_LIMIT_EXCEEDED`、`AUTOPAY_AT_RISK` 对 Agent 只给中性文案，`params` 为空 | 不要依赖这三个原因里的具体金额；需要时查询余额/代扣协议 |
| 防探测 | 添加收款人：账户不存在、户名不符、命中黑名单统一返回 `PAYEE_NOT_FOUND` | 不要据此判断具体原因；`PAYEE_NAME_MISMATCH` 不再由添加收款人返回 |
| 限频与上限 | 新增：每令牌每分钟 300 次、转账预处理/预检每用户 10 分钟 60 次、添加收款人 10 分钟 20 次、同时待处理操作 20 笔、请求体 64 KB | 处理 `RATE_LIMITED`（读 `details.retry_after_seconds`）、`TOO_MANY_PENDING`、HTTP 413 `PAYLOAD_TOO_LARGE` |
| 输入校验 | 所有字符串字段增加最大长度（见各接口参数表）；`Idempotency-Key` ≤100 字符；LIKE 类过滤（`keyword`/`counterparty`/`q`）中的 `%` `_` 按字面匹配 | 超长返回 `VALIDATION_ERROR` |
| 风控口径 | 单日转出额度统计纳入卡片/商户支付；黑名单匹配不再限定银行 | `DAILY_LIMIT_EXCEEDED` 可能比以前更早出现 |
| 并发 | 同一操作并发确认只会执行一次；定期到期与理财赎回并发不再重复入账 | 重复确认返回首次结果，无需额外处理 |
| 事件 | 事件保留 30 天，过期惰性清理 | 长时间离线后恢复需自行对账 |
| 环境 | 生产模式（`APP_ENV=prod`）下 `/admin/*`、`/docs`、`/openapi.json`、`/ui/.../otp-hint` 默认关闭，返回 `NOT_FOUND` | 以本文为准，不要依赖在线 OpenAPI |

## 1. 定位与硬性约束

澜台是**模拟银行**，只提供银行基础能力与硬规则；调度、识别、分析、编排都归 Agent。

| 约束 | 说明 |
|---|---|
| 后端不信任 Agent | 限额、黑名单、余额、归属、适当性全部由后端校验；Agent 的意图摘要只写入审计，不参与判定 |
| Agent 没有确认权 | 所有会动钱或放宽权限的操作只能 `prepare`，确认与 OTP 只能由用户在前端界面完成 |
| 收紧立即生效，放宽需确认 | 冻结/挂失/关开关/调低额度/创建预留可由 Agent 直接执行；解冻/补发/调高额度/开境外/释放预留必须经用户确认 |
| 最小披露 | 错误、摘要、结果、事件都不返回调用方未请求的数据；**余额、可用额度、限额只能通过 `get_balance` 读取**（受 `read` 控制） |
| 只调 `/api/v1/*` | `/ui/*` 与 `/admin/*` 不属于 Agent；Agent 令牌调用 `/ui/*` 会收到 `CHANNEL_NOT_ALLOWED` 并记入审计 |

## 2. 接入与认证

- **Base URL**：开发环境默认 `http://localhost:8001`（以部署为准）。
- **认证**：`Authorization: Bearer <agent_token>`。令牌由**用户**在前端“助手授权”页签发，明文只显示一次。
- **有效期**：默认 30 分钟，最长 60 分钟；用户可随时撤销（撤销后返回 `AUTH_REVOKED`）。到期需让用户重新授权。
- **scopes**（Agent 令牌只可能包含以下三种，永远没有 `confirm` / `otp`）：

| scope | 含义 |
|---|---|
| `read` | 只读查询 |
| `prepare` | 发起预处理、取消操作、管理收款人 |
| `protect` | 仅限“收紧”类直接操作（冻结/挂失、关开关、调低额度、创建预留） |

- **数据隔离**：所有资源按令牌所属用户过滤；访问他人资源统一返回 `RESOURCE_NOT_OWNED`（404），不区分“不存在”。
- **限频与上限**（进程内计数，超限返回 `RATE_LIMITED`，`details.retry_after_seconds` 为建议等待秒数）：

| 范围 | 额度 |
|---|---|
| 每令牌所有请求 | 300 次 / 分钟 |
| 转账预处理 + 风险预检（每用户） | 60 次 / 10 分钟 |
| 添加收款人（每用户） | 20 次 / 10 分钟 |
| 手机号解析（每用户） | 10 次 / 10 分钟 |
| 同时待处理操作（每用户） | 20 笔，超限 `TOO_MANY_PENDING`（HTTP 429） |
| 请求体大小 | 64 KB，超限 HTTP 413 `PAYLOAD_TOO_LARGE` |
| 字符串字段 / `Idempotency-Key` | 各接口参数表中的最大长度；`Idempotency-Key` ≤ 100 字符 |

- **令牌撤销**：除用户在“助手授权”页撤销外，用户退出登录时也可选择同时撤销全部 Agent 令牌（`POST /ui/logout?revoke_grants=true`）。
- **幂等**：所有 `prepare` 接口支持请求头 `Idempotency-Key`（或 body 的 `idempotency_key`）。同键同内容返回**首次响应**，同键不同内容返回 `IDEMPOTENCY_CONFLICT`。MCP 工具应为每次用户意图生成稳定的键，网络重试时复用。
- **约定**：金额与份额一律用**字符串**（`"20000.00"`，最多两位小数）；时间为带时区偏移的 ISO8601；账号只返回脱敏形式。

## 3. 统一响应与错误码

```json
// 成功
{ "ok": true,  "request_id": "req_71c2", "data": { ... } }
// 失败（HTTP 状态码见下表）。余额不足：details 为空，不返回任何余额数字
{ "ok": false, "request_id": "req_71c2", "error": { "code": "INSUFFICIENT_BALANCE", "message": "余额不足", "details": {} } }
// 失败时 details 只可能携带调用方需要的少量信息，例如限频
{ "ok": false, "request_id": "req_a08c", "error": { "code": "RATE_LIMITED", "message": "操作过于频繁，请稍后再试", "details": { "retry_after_seconds": 600 } } }
```

**业务风控拦截不用 4xx**：`prepare` 被风控拦截时仍返回 HTTP 200，`data.status = "BLOCKED"`，且没有 `confirm_url`；原因在 `data.risk.reasons`。Agent 不需要区分“HTTP 错误”与“业务拦截”，统一读 `status` 与 `reasons`。

| 错误码 | HTTP | 含义 |
|---|---|---|
| `OTP_EXPIRED` | 400 | OTP 已过期 |
| `OTP_INVALID` | 400 | OTP 错误 |
| `AUTH_EXPIRED` | 401 | 令牌已过期 |
| `AUTH_INVALID` | 401 | 令牌缺失或无效 |
| `AUTH_REVOKED` | 401 | 令牌已被用户撤销 |
| `ACCOUNT_CLOSED` | 403 | 账户已销户 |
| `ACCOUNT_FROZEN` | 403 | 账户被冻结 |
| `CHANNEL_NOT_ALLOWED` | 403 | 该接口仅限用户界面通道（Agent 调用 `/ui/*` 时出现） |
| `OTP_LOCKED` | 403 | OTP 错误次数过多，操作已锁定 |
| `OTP_REQUIRED` | 403 | 需要先通过 OTP（用户通道） |
| `SCOPE_INSUFFICIENT` | 403 | 令牌缺少所需 scope（如未授予 `protect` 却调用冻结卡片） |
| `USER_FROZEN` | 403 | 用户被冻结 |
| `MERCHANT_NOT_FOUND` | 404 | 商户不存在 |
| `NOT_FOUND` | 404 | 接口不存在（含生产模式下被关闭的演示接口） |
| `OPERATION_NOT_FOUND` | 404 | 操作不存在 |
| `PAYEE_NOT_FOUND` | 404 | 收款人/收款账户/手机号不存在，或缺少户名；**添加收款人失败时统一返回**，不区分账户不存在/户名不符/黑名单 |
| `RESOURCE_NOT_OWNED` | 404 | 资源不存在或不属于当前用户（对外不区分，防止枚举） |
| `CARD_QUOTA_REACHED` | 409 | 卡片数量已达上限 |
| `CARD_STATE_INVALID` | 409 | 卡片当前状态不允许该操作 |
| `CONFIRM_REQUIRED` | 409 | 该变更属于放宽权限，须走 prepare 由用户确认（`details.use` 给出应调用的接口） |
| `HOLDING_NOT_ACTIVE` | 409 | 持仓已结束 |
| `HOLD_LIMIT_REACHED` | 409 | 有效预留数量已达上限 |
| `HOLD_NOT_ACTIVE` | 409 | 预留已释放或到期 |
| `IDEMPOTENCY_CONFLICT` | 409 | 同一幂等键对应的请求内容不一致 |
| `MANDATE_NOT_ACTIVE` | 409 | 代扣协议已取消 |
| `OPERATION_EXPIRED` | 409 | 操作超过 5 分钟有效期 |
| `OPERATION_STATE_INVALID` | 409 | 操作当前状态不允许该动作（如取消已执行的操作） |
| `ORDER_ALREADY_PAID` | 409 | 同一商户同一订单号已支付过 |
| `PARAMS_TAMPERED` | 409 | 操作参数与预处理时不一致 |
| `RISK_BLOCKED` | 409 | 确认时风控复核未通过（prepare 阶段的拦截以 `status=BLOCKED` 表示，不用此码） |
| `PAYLOAD_TOO_LARGE` | 413 | 请求体超过 64 KB |
| `AMOUNT_ABOVE_MAX` | 422 | 超过上限（额度上限、可赎回份额等） |
| `AMOUNT_BELOW_MIN` | 422 | 低于起存/起购额 |
| `AMOUNT_INVALID` | 422 | 金额或份额格式不合法（须为字符串，最多两位小数，大于 0） |
| `CURRENCY_UNSUPPORTED` | 422 | 仅支持 CNY |
| `INSUFFICIENT_BALANCE` | 422 | 可用余额（余额 − 资金预留）不足。`message` 固定为“余额不足”（创建预留时为“余额不足以预留该金额”），`details` 为空，**不返回任何余额数字**；需要时调用 `get_balance` |
| `PAYEE_NAME_MISMATCH` | 422 | 保留码：目前添加收款人不再返回它（统一为 `PAYEE_NOT_FOUND`）；转账时户名不符体现为风控原因 `PAYEE_NAME_MISMATCH` |
| `PRODUCT_NOT_AVAILABLE` | 422 | 产品不存在或已下架 |
| `SAME_ACCOUNT` | 422 | 转给同一账户 / 本人账户无需添加为收款人 |
| `VALIDATION_ERROR` | 422 | 参数校验失败（缺字段、格式不对、取值非法、字段超长、`Idempotency-Key` 超过 100 字符） |
| `RATE_LIMITED` | 429 | 请求过于频繁；`details.retry_after_seconds` 给出建议等待时间 |
| `TOO_MANY_PENDING` | 429 | 同时待处理的操作过多（上限 20 笔），先确认、取消或等待过期 |
| `EXECUTION_FAILED` | 500 | 执行失败 |
| `INTERNAL_ERROR` | 500 | 服务内部错误 |

另有 FastAPI 参数校验失败：HTTP 422，`error.code = VALIDATION_ERROR`，`details.errors` 列出字段与原因。

**`error.details` 遵循最小披露**：不再包含余额、可用额度、内部阈值等数据；常见的只有 `retry_after_seconds`、`attempts_left`、`use`（`CONFIRM_REQUIRED` 时应改调的接口）、`order_ref` 等调用方自己提供过的信息。

## 4. 核心流程：prepare → 用户确认 → 查询结果

```
Agent                         澜台后端                         用户（前端界面）
 │ prepare_xxx ─────────────▶ │ 校验 + 风控 → 创建操作(op_...)    │
 │ ◀── operation_id, summary,  │                                  │
 │     risk.reasons, confirm_url                                   │
 │ 向用户解释原因，并给出链接 ───────────────────────────────────▶ │ 打开 confirm_url
 │                            │ ◀──── 需要 OTP 则输入验证码 ───── │
 │                            │ ◀──── 点击“确认并执行” ────────── │
 │ get_operation(轮询) ─────▶ │ status = EXECUTED, result{...}    │
```

### 4.1 操作状态

| status | 含义 | 终态 |
|---|---|---|
| `PREPARED` | 已创建，等待用户确认（仅需确认，无需 OTP） | 否 |
| `OTP_PENDING` | 已创建，需要用户先验证短信码 | 否 |
| `OTP_VERIFIED` | OTP 已通过，等待确认 | 否 |
| `EXECUTED` | 已执行，`result` 含流水号/余额等 | 是 |
| `BLOCKED` | 被风控拦截（prepare 时或确认时复核） | 是 |
| `EXPIRED` | 超过 5 分钟有效期 | 是 |
| `CANCELLED` | 被取消或被用户拒绝 | 是 |
| `OTP_LOCKED` | OTP 错误 3 次，已锁定 | 是 |
| `FAILED` | 确认时执行失败（如余额已不足） | 是 |

### 4.2 prepare 返回（所有 prepare 接口结构一致）

```json
{
  "ok": true,
  "request_id": "req_71c2",
  "data": {
    "operation_id": "op_8f3a2c1d9e",
    "type": "transfer",
    "status": "OTP_PENDING",
    "initiator": "agent",
    "summary": { "from": "活期账户 ****1001", "to": "张三 ****3456", "bank": "澜台",
                 "amount": "2000.00", "fee": "0.00", "total_debit": "2000.00" },
    "risk": {
      "level": "medium",
      "required_action": "otp",
      "reasons": [
        { "code": "NEW_PAYEE", "severity": "medium", "message": "首次向该收款人转账",
          "agent_hint": "向用户说明并提醒核实对方身份", "params": {} }
      ]
    },
    "confirm_by": "user_interface",
    "confirm_url": "http://localhost:8001/confirm/op_8f3a2c1d9e",
    "expires_at": "2026-10-12T20:10:00+01:00",
    "created_at": "2026-10-12T20:05:00+01:00"
  }
}
```

- `confirm_url` 仅在操作处于非终态时出现；`BLOCKED` 没有。
- 执行成功后再次 `get_operation`，多出 `result`（流水号、操作后余额、持有编号等，随操作类型而异）。
- 同一 `operation_id` 重复确认不会重复扣款（并发确认也只执行一次，其余请求返回首次结果）。
- **Agent 视图已裁剪**：`summary` 与 `result` 不含 `balance_after`；用户在前端看到的视图包含余额。需要余额请调用 `get_balance`。

### 4.3 操作类型（`type`）

| type | 来源接口 |
|---|---|
| `transfer` | `prepare_transfer` |
| `deposit_create` | `prepare_deposit` |
| `deposit_early_withdraw` | `prepare_early_withdraw` |
| `card_apply` | `prepare_card_apply` |
| `card_unfreeze` | `prepare_card_unfreeze` |
| `card_reissue` | `prepare_card_reissue` |
| `card_controls` | `prepare_card_controls` |
| `card_limits` | `prepare_card_limits` |
| `account_limits` | `prepare_account_limits` |
| `mandate_cancel` | `prepare_mandate_cancel` |
| `hold_release` | `prepare_hold_release` |
| `merchant_payment` | `prepare_merchant_payment` |
| `wealth_subscribe` | `prepare_wealth_subscribe` |
| `wealth_redeem` | `prepare_wealth_redeem` |

## 5. 风控结果与原因码

`risk.level`：`low` < `medium` < `high` < `blocked`；`risk.required_action`：`confirm`（仅确认）/ `otp`（先验证码）/ `block`（拦截）。
所有适用规则都会执行且不短路，`reasons` 是完整列表。**向用户解释时请使用 `message`，并参考 `agent_hint`（建议，不是指令）。**

| 原因码 | 级别 | 用户可见文案（模板） | 给 Agent 的解释方向 |
|---|---|---|---|
| `BLACKLIST_HIT` | blocked | 该收款账户已被列入涉诈风险名单，交易被拦截 | 不要尝试换渠道或拆分金额；建议用户核实对方身份并联系反诈热线 96110 |
| `CARD_LIMIT_EXCEEDED` | blocked | 超过卡片额度：单笔 {single} 元 / 单日 {daily} 元（今日已用 {used} 元） | 告知额度，建议分日或提额（需验证） |
| `CARD_NOT_USABLE` | blocked | 卡片当前为{status}，无法支付 | 引导用户先处理卡片状态（解冻/补发），不要换卡重试以绕过风控 |
| `CONTROL_DISABLED` | blocked | 该卡片的「{name}」开关已关闭，无法完成本次支付 | 如确需支付，可引导用户在确认中心打开对应开关（需验证） |
| `DAILY_LIMIT_EXCEEDED` | blocked | 超过账户单日累计转出限额 {limit} 元（今日已转出 {used} 元） | 告知用户今日剩余额度，建议明日再试 |
| `MERCHANT_RISKY` | blocked | 该商户已被列入风险名单，支付被拦截 | 提醒用户核实商户身份，谨防返利、刷单类诈骗 |
| `RISK_LEVEL_FORBIDDEN` | blocked | 产品风险等级 {product} 超出您的风险承受能力 {user} 两级及以上，不适合购买 | 不要劝说用户绕过；可推荐风险等级不高于其承受能力的产品 |
| `RISK_PROFILE_MISSING` | blocked | {status}，请先完成风险测评后再购买理财产品 | 引导用户到界面完成风险测评（测评只能由用户本人提交） |
| `SINGLE_LIMIT_EXCEEDED` | blocked | 超过账户单笔转出限额 {limit} 元 | 告知用户单笔限额，可建议分笔或线下办理 |
| `CONTROL_OVERSEAS_ON` | high | 将打开境外交易，存在被盗刷风险 | 提醒仅在出境期间开启，用完及时关闭 |
| `HIGH_BALANCE_RATIO` | high | 本次转出超过账户余额的 {ratio} | 询问资金用途，留意是否被诱导清空账户 |
| `LARGE_AMOUNT` | high | 金额达到大额交易标准（{threshold} 元） | 提醒用户再次确认金额 |
| `LIMIT_RAISE` | high | 单日额度将由 {old} 元提高到 {new} 元，被盗刷或诈骗时的潜在损失同步扩大 | 询问提额原因，建议按需、临时提额 |
| `PAYEE_NAME_MISMATCH` | high | 填写的收款人户名与该账户实际户名不一致 | 提示用户核对对方姓名与账号 |
| `RISK_LEVEL_MISMATCH` | high | 产品风险等级 {product} 高于您的风险承受能力 {user}，属于不匹配购买，需特别确认 | 明确告知风险，确认用户理解并自愿购买 |
| `CARD_REISSUE` | medium | 补发新卡，原卡号将作废 | 确认用户已挂失原卡 |
| `CARD_UNFREEZE` | medium | 解冻/解锁卡片后，卡片渠道的交易将恢复 | 确认是用户本人要求解冻，且已排除盗刷风险 |
| `CONTROL_LOOSEN` | medium | 将打开以下交易开关：{items} | 确认用户确有使用需求 |
| `NEW_MERCHANT` | medium | 首次向该商户支付 | 提醒用户核实商户与订单 |
| `NEW_PAYEE` | medium | 首次向该收款人转账 | 向用户说明并提醒核实对方身份 |
| `OVERSEAS_PAYMENT` | medium | 该商户位于境外 | 确认用户知晓境外交易的汇率与风险 |
| `RAPID_REPEAT` | medium | {window} 分钟内已发生多笔转出 | 询问是否被人催促连续转账 |
| `AUTOPAY_AT_RISK` | low | 转出后余额可能不足以覆盖 {days} 天内的自动扣款（{items}） | 告知具体扣款项与日期 |
| `CARD_APPLY` | low | 将为该账户新增一张借记卡 | 提醒用户新卡需妥善保管 |
| `CROSS_BANK_FEE` | low | 跨行转账将收取手续费 {fee} 元 | 向用户说明手续费 |
| `EARLY_WITHDRAW_LOSS` | low | 提前支取将损失利息 {loss} 元（到期可得 {full} 元，现仅 {early} 元） | 对比到期日期，建议用户权衡 |
| `HOLD_RELEASE` | low | 将释放预留的 {amount} 元（用途：{purpose}），释放后这笔资金可被转出或支付 | 确认用户是有意提前动用这笔预留，而非被诱导 |
| `MANDATE_CANCEL` | low | 取消后「{merchant}」将无法继续从该账户扣款，下次扣款日 {date} 前如仍需要服务，可能导致中断或逾期 | 提醒用户确认是否已在商户侧处理（如房租、信用卡还款需另行安排） |
| `NAV_RISK_NOTICE` | low | 净值型产品不保本，净值会波动，可能出现本金亏损 | 向用户说明过往业绩不代表未来表现 |
| `NIGHT_TRANSACTION` | low | 当前为夜间时段（0~6 点） | 提示用户确认是否本人操作 |
| `REDEEM_LOSS` | low | 按当前净值赎回将实现亏损 {loss} 元 | 提示用户可考虑继续持有，由其自行决定 |

`{xxx}` 为占位符，实际值在响应的 `params` 与已渲染的 `message` 中。**例外**：`DAILY_LIMIT_EXCEEDED`、`CARD_LIMIT_EXCEEDED`、`AUTOPAY_AT_RISK` 在 Agent 通道只返回中性文案（如“超过账户单日累计转出限额”），`params` 为空，不含金额、今日已用额与扣款明细；用户在前端确认页可看到完整文案。

## 6. 事件流

`get_events` 是 Agent 实现**提醒、对账、定时触发**的基础：

1. 首次调用 `after_id=0`（或先取 `latest_id` 作为起点，只关心之后的事件）。
2. 处理 `items`（按 `id` 严格递增），把 `next_after_id` 持久化。
3. 周期性轮询；`has_more=true` 时立刻继续取。

| type | 触发 | `data` 主要字段 |
|---|---|---|
| `txn_out / txn_in` | 任一账户扣款/入账（含他人转入） | account_id, category, amount, counterparty, memo, merchant_category, operation_id（不含余额） |
| `operation` | 操作状态变化（含 OTP 通过/锁定、过期、取消、拦截、失败） | operation_id, op_type, status |
| `card` | 卡片冻结/挂失/解冻/补发/开关/额度变化 | card_id, change, status |
| `account` | 账户转账额度变化 | account_id, change |
| `mandate` | 代扣协议取消 | mandate_id, merchant, status |
| `hold` | 预留创建/释放/到期 | hold_id, status, amount |
| `deposit` | 定期到期自动兑付 | holding_id, status=matured, principal, interest |
| `risk_profile` | 用户完成风险测评 | level, label |

**保留期**：事件保留 30 天，过期事件会在登录时惰性清理；离线较久后恢复，请先 `get_balance` / `list_transactions` 对账，再从 `latest_id` 继续。

典型用法：用户说“收到 AA 款提醒我”→ Agent 记录目标，轮询时匹配 `txn_in` 的 `memo`/`amount`；“用户确认了吗”→ 匹配 `operation` 事件而不是盲目轮询。

## 7. 接口参考

图例：**类别** — `查询`（只读）/ `直接生效`（保护性或低风险写操作，立即生效，会记审计）/ `预处理`（创建待确认操作，必须由用户确认）。

### 7.1 账户与流水

#### `GET /api/v1/me`

- **MCP 工具名**：`get_me`　**类别**：查询　**所需 scope**：`read`
- **说明**：当前用户概要与令牌的权限范围、过期时间。
- **注意**：接入后第一个调用，用来确认令牌类型与 scopes。

#### `GET /api/v1/accounts`

- **MCP 工具名**：`list_accounts`　**类别**：查询　**所需 scope**：`read`
- **说明**：账户列表（卡号脱敏）与余额。

#### `GET /api/v1/accounts/{account_id}/balance`

- **MCP 工具名**：`get_balance`　**类别**：查询　**所需 scope**：`read`
- **说明**：账户余额、已预留金额、可用余额、单笔/单日限额、今日已转出与剩余额度。
- **注意**：**余额类数据只在本接口返回**（其它接口的错误、摘要、结果、事件均不再带余额）。转账前用 `available` 判断，不要用 `balance`。`today_transferred_out` 仅统计转账类别；风控的单日限额口径还包含卡片/商户支付，`daily_remaining` 仅供参考，以 prepare 的风控结果为准。
- **路径参数**：`account_id`

#### `GET /api/v1/accounts/{account_id}/transactions`

- **MCP 工具名**：`list_transactions`　**类别**：查询　**所需 scope**：`read`
- **说明**：交易流水，支持时间、方向、类别、金额下限、关键词、对方、商户品类过滤与游标分页。
- **注意**：分页：把响应里的 `next_cursor` 原样传回 `cursor`，为 null 表示没有更多。`from/to` 为纯日期时，`to` 含当天。
- **路径参数**：`account_id`

| 查询参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `from` | string | 否 | 起始时间：ISO 日期或时间（无时区视为澜台本地时间） |
| `to` | string | 否 | 截止时间：纯日期含当天 |
| `direction` | string（^(in\|out)$） | 否 | in 收入 / out 支出 |
| `category` | string | 否 | 类别：transfer / deposit_out / deposit_in / interest / autopay / salary / fee / wealth_out / wealth_in / other |
| `min_amount` | string | 否 | 金额下限（含），字符串 |
| `keyword` | string（≤50） | 否 | 备注或对方名称包含的关键词 |
| `counterparty` | string（≤50） | 否 | 对方名称包含的文本 |
| `merchant_category` | string（≤20） | 否 | 商户品类：餐饮 / 交通 / 购物 / 日用 / 医疗 / 娱乐 / 居住 / 生活缴费 / 订阅 / 还款 / 收入 / 礼品 / 理财 |
| `limit` | integer | 否 | 每页条数（默认 20，范围 1~100） |
| `cursor` | integer | 否 | 分页游标：上一页返回的 next_cursor（默认 0，范围 0~） |

### 7.2 收款人

#### `GET /api/v1/payees`

- **MCP 工具名**：`list_payees`　**类别**：查询　**所需 scope**：`read`
- **说明**：已保存收款人，可用 `q` 按户名/备注名/账号尾号搜索。
- **注意**：重名时应向用户追问，不要自行挑选。`ever_paid=false` 的收款人首次转账需要 OTP。

| 查询参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `q` | string（≤30） | 否 | 搜索词：匹配户名、备注名或账号尾号 |

#### `GET /api/v1/payees/resolve`

- **MCP 工具名**：`resolve_payee_by_phone`　**类别**：查询　**所需 scope**：`read`
- **说明**：按手机号查询澜台行内收款人，只返回脱敏户名。
- **注意**：有频率限制（每用户 10 分钟 10 次，超限 `RATE_LIMITED`）。转账时仍须向用户索取收款人完整户名。

| 查询参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `phone` | string（^\d{11}$） | 是 | 11 位手机号 |

#### `POST /api/v1/payees`

- **MCP 工具名**：`add_payee`　**类别**：直接生效　**所需 scope**：`prepare`
- **说明**：添加收款人。行内账户会核验户名，黑名单账户会被拒绝。
- **注意**：添加不等于放行：首次转账仍触发 `NEW_PAYEE`。已存在时返回 `already_exists=true`。账户不存在、户名不符、命中黑名单**统一返回** `PAYEE_NOT_FOUND`（不区分原因，防探测）；每用户 10 分钟最多 20 次，超限 `RATE_LIMITED`。

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `account_no` | string（≤32） | 是 |  | 账号 |
| `name` | string（≤64） | 是 |  | 户名 |
| `bank_code` | string（≤20） | 否 | `LANTAI` | LANTAI（行内，默认）/ OTHER（他行） |
| `bank_name` | string（≤40） | 否 |  | 他行名称，缺省“他行” |
| `alias` | string（≤32） | 否 |  | 备注名，≤32 字；传 null 清除 |

#### `PATCH /api/v1/payees/{payee_id}`

- **MCP 工具名**：`update_payee_alias`　**类别**：直接生效　**所需 scope**：`prepare`
- **说明**：修改收款人备注名。
- **路径参数**：`payee_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `alias` | string（≤32） | 否 |  | 备注名，≤32 字；传 null 清除 |

#### `DELETE /api/v1/payees/{payee_id}`

- **MCP 工具名**：`remove_payee`　**类别**：直接生效　**所需 scope**：`prepare`
- **说明**：删除收款人（软删除，历史转账不受影响）。
- **注意**：删除前应让用户确认。
- **路径参数**：`payee_id`

### 7.3 转账与风险预检

#### `POST /api/v1/transfers/prepare`

- **MCP 工具名**：`prepare_transfer`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：转账预处理：校验、风控评估并创建待确认操作。收款方三选一：`payee_id` / `payee_account_no`+`payee_name` / `payee_phone`+`payee_name`。
- **注意**：返回后必须引导用户到 `confirm_url` 确认；Agent 无法确认。风控拦截时仍返回 200，`status=BLOCKED`。Agent 视图的 `summary` 不含 `balance_after`；余额不足只返回 `INSUFFICIENT_BALANCE`，不带具体余额。每用户 10 分钟最多 60 次转账预处理/预检，同时待处理操作最多 20 笔（超限 `TOO_MANY_PENDING`）。

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `from_account_id` | string（≤40） | 是 |  | 付款账户 id，如 acc_001 |
| `payee_id` | string（≤40） | 否 |  | 已保存收款人 id |
| `payee_account_no` | string（≤32） | 否 |  | 收款账号（16 位） |
| `payee_name` | string（≤64） | 否 |  | 收款人完整户名，用于核验 |
| `payee_phone` | string（≤20） | 否 |  | 收款人手机号（11 位，仅澜台用户）并需同时提供 payee_name |
| `bank_code` | string（≤20） | 否 |  | LANTAI（行内，默认）/ OTHER（他行） |
| `bank_name` | string（≤40） | 否 |  | 他行名称，缺省“他行” |
| `amount` | string（≤24） | 是 |  | 金额，字符串，最多两位小数，大于 0 |
| `currency` | string（≤8） | 否 | `CNY` | 仅支持 CNY |
| `memo` | string（≤200） | 否 |  | 附言，≤200 字 |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

#### `GET /api/v1/operations/{op_id}`

- **MCP 工具名**：`get_operation`　**类别**：查询　**所需 scope**：`read`
- **说明**：查询操作的当前状态、风控结果与执行结果。
- **注意**：prepare 之后用它轮询用户是否已确认；建议间隔 2~3 秒，到终态即停。**Agent 视图已裁剪**：`summary`/`result` 不含 `balance_after`；`DAILY_LIMIT_EXCEEDED`、`CARD_LIMIT_EXCEEDED`、`AUTOPAY_AT_RISK` 三条风控原因只给中性文案、`params` 为空。
- **路径参数**：`op_id`

#### `POST /api/v1/operations/{op_id}/cancel`

- **MCP 工具名**：`cancel_operation`　**类别**：直接生效　**所需 scope**：`prepare`
- **说明**：取消尚未终态的操作。
- **注意**：已执行的操作不能取消。
- **路径参数**：`op_id`

#### `POST /api/v1/risk/precheck`

- **MCP 工具名**：`precheck_transfer_risk`　**类别**：查询　**所需 scope**：`read`
- **说明**：只评估转账风险，不创建操作、不扣款。
- **注意**：用户还在犹豫或信息不全时先探路，例如提前发现黑名单收款方。请求体与 `prepare_transfer` 相同；与 prepare 共用每用户 10 分钟 60 次的探测额度。

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `from_account_id` | string（≤40） | 是 |  | 付款账户 id，如 acc_001 |
| `payee_id` | string（≤40） | 否 |  | 已保存收款人 id |
| `payee_account_no` | string（≤32） | 否 |  | 收款账号（16 位） |
| `payee_name` | string（≤64） | 否 |  | 收款人完整户名，用于核验 |
| `payee_phone` | string（≤20） | 否 |  | 收款人手机号（11 位，仅澜台用户）并需同时提供 payee_name |
| `bank_code` | string（≤20） | 否 |  | LANTAI（行内，默认）/ OTHER（他行） |
| `bank_name` | string（≤40） | 否 |  | 他行名称，缺省“他行” |
| `amount` | string（≤24） | 是 |  | 金额，字符串，最多两位小数，大于 0 |
| `currency` | string（≤8） | 否 | `CNY` | 仅支持 CNY |
| `memo` | string（≤200） | 否 |  | 附言，≤200 字 |

### 7.4 定期存款

#### `GET /api/v1/deposit/products`

- **MCP 工具名**：`list_deposit_products`　**类别**：查询　**所需 scope**：`read`
- **说明**：在售定期产品（期限、年化、起存额、提前支取利率）。

#### `GET /api/v1/deposit/holdings`

- **MCP 工具名**：`list_deposit_holdings`　**类别**：查询　**所需 scope**：`read`
- **说明**：定期持有，含到期利息与提前支取的损失试算。
- **注意**：到期的定期会在任意鉴权请求时自动兑付入账。

#### `POST /api/v1/deposits/prepare`

- **MCP 工具名**：`prepare_deposit`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：存入定期预处理。
- **注意**：资金来源按可用余额校验。

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `account_id` | string（≤40） | 是 |  | 账户 id |
| `product_id` | string（≤40） | 是 |  | 产品 id |
| `amount` | string（≤24） | 是 |  | 金额，字符串，最多两位小数，大于 0 |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

#### `POST /api/v1/deposits/{holding_id}/early-withdraw/prepare`

- **MCP 工具名**：`prepare_early_withdraw`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：提前支取定期预处理，风险提示中包含利息损失金额。
- **注意**：请求体可为空对象。需向用户说明损失后再引导确认。
- **路径参数**：`holding_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `holding_id` | string（≤40） | 否 |  | 定期/理财持仓 id |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

### 7.5 卡片与额度

#### `GET /api/v1/cards`

- **MCP 工具名**：`list_cards`　**类别**：查询　**所需 scope**：`read`
- **说明**：借记卡列表：状态、交易开关、卡片额度。

#### `GET /api/v1/cards/{card_id}`

- **MCP 工具名**：`get_card`　**类别**：查询　**所需 scope**：`read`
- **说明**：单张卡片详情。
- **路径参数**：`card_id`

#### `POST /api/v1/cards/{card_id}/freeze`

- **MCP 工具名**：`freeze_card`　**类别**：直接生效　**所需 scope**：`protect`
- **说明**：冻结卡片（保护性，立即生效）。
- **注意**：用户说“卡被盗/不见了先冻一下”时使用。已冻结则 `changed=false`。
- **路径参数**：`card_id`

#### `POST /api/v1/cards/{card_id}/report-loss`

- **MCP 工具名**：`report_card_lost`　**类别**：直接生效　**所需 scope**：`protect`
- **说明**：挂失卡片（保护性，立即生效，不可撤销）。
- **注意**：执行前应向用户确认；挂失后需 `prepare_card_reissue` 补发。
- **路径参数**：`card_id`

#### `PUT /api/v1/cards/{card_id}/controls`

- **MCP 工具名**：`close_card_controls`　**类别**：直接生效　**所需 scope**：`protect`
- **说明**：关闭交易开关（线上/境外/ATM）。
- **注意**：只能关闭。传 `true` 会返回 `CONFIRM_REQUIRED`，改用 `prepare_card_controls`。
- **路径参数**：`card_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `card_id` | string（≤40） | 否 |  | 卡片 id |
| `online` | boolean | 否 |  | 线上支付开关：true 开启 / false 关闭 |
| `overseas` | boolean | 否 |  | 境外交易开关：true 开启 / false 关闭 |
| `atm` | boolean | 否 |  | ATM 取现开关：true 开启 / false 关闭 |

#### `PUT /api/v1/cards/{card_id}/limits`

- **MCP 工具名**：`lower_card_limits`　**类别**：直接生效　**所需 scope**：`protect`
- **说明**：调低卡片单笔/单日额度。
- **注意**：调高会返回 `CONFIRM_REQUIRED`，改用 `prepare_card_limits`。金额为字符串。
- **路径参数**：`card_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `card_id` | string（≤40） | 否 |  | 卡片 id |
| `single_limit` | string（≤24） | 否 |  | 单笔额度（元，字符串） |
| `daily_limit` | string（≤24） | 否 |  | 单日额度（元，字符串） |

#### `PUT /api/v1/accounts/{account_id}/limits`

- **MCP 工具名**：`lower_account_limits`　**类别**：直接生效　**所需 scope**：`protect`
- **说明**：调低账户转账额度。
- **注意**：调高会返回 `CONFIRM_REQUIRED`，改用 `prepare_account_limits`。
- **路径参数**：`account_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `account_id` | string（≤40） | 否 |  | 账户 id |
| `single_limit` | string（≤24） | 否 |  | 单笔额度（元，字符串） |
| `daily_limit` | string（≤24） | 否 |  | 单日额度（元，字符串） |

#### `POST /api/v1/cards/apply/prepare`

- **MCP 工具名**：`prepare_card_apply`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：申请新借记卡预处理（每账户最多 3 张有效卡）。
- **注意**：超限返回 `CARD_QUOTA_REACHED`。

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `account_id` | string（≤40） | 是 |  | 账户 id |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

#### `POST /api/v1/cards/{card_id}/unfreeze/prepare`

- **MCP 工具名**：`prepare_card_unfreeze`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：解冻/解锁卡片预处理（需 OTP）。
- **注意**：放宽类操作，Agent 不能直接执行。
- **路径参数**：`card_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `card_id` | string（≤40） | 否 |  | 卡片 id |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

#### `POST /api/v1/cards/{card_id}/reissue/prepare`

- **MCP 工具名**：`prepare_card_reissue`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：已挂失卡片补发预处理（需 OTP）。
- **注意**：仅已挂失且未补发过的卡可补发。
- **路径参数**：`card_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `card_id` | string（≤40） | 否 |  | 卡片 id |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

#### `POST /api/v1/cards/{card_id}/controls/prepare`

- **MCP 工具名**：`prepare_card_controls`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：调整交易开关预处理；打开开关需要 OTP，开境外为高风险。
- **路径参数**：`card_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `card_id` | string（≤40） | 否 |  | 卡片 id |
| `online` | boolean | 否 |  | 线上支付开关：true 开启 / false 关闭 |
| `overseas` | boolean | 否 |  | 境外交易开关：true 开启 / false 关闭 |
| `atm` | boolean | 否 |  | ATM 取现开关：true 开启 / false 关闭 |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

#### `POST /api/v1/cards/{card_id}/limits/prepare`

- **MCP 工具名**：`prepare_card_limits`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：调整卡片额度预处理；调高需 OTP。
- **注意**：上限：单笔 200,000，单日 500,000。
- **路径参数**：`card_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `card_id` | string（≤40） | 否 |  | 卡片 id |
| `single_limit` | string（≤24） | 否 |  | 单笔额度（元，字符串） |
| `daily_limit` | string（≤24） | 否 |  | 单日额度（元，字符串） |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

#### `POST /api/v1/accounts/{account_id}/limits/prepare`

- **MCP 工具名**：`prepare_account_limits`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：调整账户转账额度预处理；调高需 OTP。
- **注意**：调高额度会同步放大被诈骗时的潜在损失，建议询问原因。
- **路径参数**：`account_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `account_id` | string（≤40） | 否 |  | 账户 id |
| `single_limit` | string（≤24） | 否 |  | 单笔额度（元，字符串） |
| `daily_limit` | string（≤24） | 否 |  | 单日额度（元，字符串） |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

### 7.6 代扣协议

#### `GET /api/v1/mandates`

- **MCP 工具名**：`list_mandates`　**类别**：查询　**所需 scope**：`read`
- **说明**：代扣协议：商户、品类、金额、周期、下次扣款日、状态。
- **注意**：订阅识别与续费提醒由 Agent 基于本接口与流水自行完成。

| 查询参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `status` | string（^(active\|cancelled)$） | 否 | 状态过滤：mandates 为 active / cancelled；holds 为 active / released / expired |

#### `POST /api/v1/mandates/{mandate_id}/cancel/prepare`

- **MCP 工具名**：`prepare_mandate_cancel`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：取消代扣协议预处理。
- **注意**：取消后商户无法继续扣款，房租、信用卡还款等应提醒用户另行安排。
- **路径参数**：`mandate_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `mandate_id` | string（≤40） | 否 |  |  |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

### 7.7 资金预留

#### `GET /api/v1/accounts/{account_id}/holds`

- **MCP 工具名**：`list_holds`　**类别**：查询　**所需 scope**：`read`
- **说明**：账户的资金预留列表；到期的预留会被标记为 expired。
- **路径参数**：`account_id`

| 查询参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `status` | string（^(active\|released\|expired)$） | 否 | 状态过滤：mandates 为 active / cancelled；holds 为 active / released / expired |

#### `POST /api/v1/accounts/{account_id}/holds`

- **MCP 工具名**：`create_hold`　**类别**：直接生效　**所需 scope**：`protect`
- **说明**：预留（锁定）一笔资金，立即生效。预留部分不可转出、存定期、支付或代扣。
- **注意**：`until` 可选，最长 366 天，每账户最多 10 笔有效预留。释放需 `prepare_hold_release`。响应只含预留本身，不再返回预留后的可用余额；余额不足返回 `INSUFFICIENT_BALANCE`。
- **路径参数**：`account_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `amount` | string（≤24） | 是 |  | 金额，字符串，最多两位小数，大于 0 |
| `purpose` | string（≤60） | 否 |  | 用途说明，≤60 字 |
| `until` | string（≤40） | 否 |  | 到期日：ISO 日期（含当天）或带/不带时区的时间；缺省=直到释放，最长 366 天 |

#### `POST /api/v1/holds/{hold_id}/release/prepare`

- **MCP 工具名**：`prepare_hold_release`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：释放预留预处理。
- **注意**：放宽类操作，需用户确认。
- **路径参数**：`hold_id`

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `hold_id` | string（≤40） | 否 |  |  |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

### 7.8 商户支付

#### `GET /api/v1/merchants`

- **MCP 工具名**：`list_merchants`　**类别**：查询　**所需 scope**：`read`
- **说明**：商户目录（鲜花、蛋糕、会员、超市、境外礼品等）。

#### `POST /api/v1/payments/merchant/prepare`

- **MCP 工具名**：`prepare_merchant_payment`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：用借记卡向商户付款预处理。
- **注意**：`order_ref` 同一商户内唯一，重复支付返回 `ORDER_ALREADY_PAID`。受卡片状态、开关、额度、可用余额与商户风险约束。

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `card_id` | string（≤40） | 是 |  | 卡片 id |
| `merchant_id` | string（≤40） | 是 |  | 商户 id |
| `amount` | string（≤24） | 是 |  | 金额，字符串，最多两位小数，大于 0 |
| `order_ref` | string（≤60） | 是 |  | 订单号，≤60 字；同一商户内唯一 |
| `channel` | `online` \| `offline` | 否 | `online` | 支付渠道：online（默认）/ offline |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

### 7.9 风险测评与理财

#### `GET /api/v1/risk-profile`

- **MCP 工具名**：`get_risk_profile`　**类别**：查询　**所需 scope**：`read`
- **说明**：客户风险测评等级与有效性（none / valid / expired）。
- **注意**：测评只能由用户在界面完成；Agent 只读。

#### `GET /api/v1/risk-profile/questionnaire`

- **MCP 工具名**：`get_risk_questionnaire`　**类别**：查询　**所需 scope**：`read`
- **说明**：风险测评问卷题目，便于向用户说明测评内容。
- **注意**：Agent 不能代答或提交。

#### `GET /api/v1/wealth/products`

- **MCP 工具名**：`list_wealth_products`　**类别**：查询　**所需 scope**：`read`
- **说明**：理财产品：风险等级 R1~R5、净值、起购额，以及相对当前用户的适合度 `suitability`。
- **注意**：`suitability`：match / mismatch（高一级，需 OTP）/ forbidden（高两级，拦截）/ unassessed。推荐与对比由 Agent 完成。

#### `GET /api/v1/wealth/holdings`

- **MCP 工具名**：`list_wealth_holdings`　**类别**：查询　**所需 scope**：`read`
- **说明**：理财持仓：份额、净值、市值、成本、盈亏。

#### `POST /api/v1/wealth/subscribe/prepare`

- **MCP 工具名**：`prepare_wealth_subscribe`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：理财申购预处理，含适当性校验。
- **注意**：未测评或测评过期会被拦截（`RISK_PROFILE_MISSING`），应引导用户先在界面完成测评。

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `account_id` | string（≤40） | 是 |  | 账户 id |
| `product_id` | string（≤40） | 是 |  | 产品 id |
| `amount` | string（≤24） | 是 |  | 金额，字符串，最多两位小数，大于 0 |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

#### `POST /api/v1/wealth/redeem/prepare`

- **MCP 工具名**：`prepare_wealth_redeem`　**类别**：预处理　**所需 scope**：`prepare`
- **说明**：理财赎回预处理；不传 `shares` 为全部赎回。
- **注意**：亏损赎回会有 `REDEEM_LOSS` 提示。

| 请求体字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `holding_id` | string（≤40） | 是 |  | 定期/理财持仓 id |
| `shares` | string（≤16） | 否 |  | 赎回份额，字符串，最多两位小数；缺省=全部赎回 |
| `account_id` | string（≤40） | 否 |  | 账户 id |

> prepare 接口可额外携带 `idempotency_key`（或请求头 `Idempotency-Key`）与 `agent_context: {intent_summary, user_utterance_excerpt}`；后者只写入审计，不参与判定。

### 7.10 事件流

#### `GET /api/v1/events`

- **MCP 工具名**：`get_events`　**类别**：查询　**所需 scope**：`read`
- **说明**：递增事件流：入账/扣款、操作状态变化、卡片/协议/预留变化、定期到期、风险测评。
- **注意**：Agent 自行保存 `next_after_id` 并轮询，用于提醒、对账与定时触发。银行不推送。事件**不含余额**；保留 30 天，过期事件会被惰性清理，游标过旧则取不到更早事件。

| 查询参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `after_id` | integer | 否 | 只返回 id 大于此值的事件（默认 0，范围 0~） |
| `limit` | integer | 否 | 每页条数（默认 50，范围 1~200） |
| `types` | string | 否 | 逗号分隔：txn_in,txn_out,operation,card,account,mandate,hold |

## 8. MCP 工具设计建议

### 8.1 工具清单

一个 Agent 接口对应一个 MCP 工具，工具名即上文的“MCP 工具名”。**不要暴露任何确认类工具**（澜台本身也不会接受 Agent 的确认）。

| 工具名 | 方法与路径 | 类别 | scope |
|---|---|---|---|
| `get_me` | `GET /api/v1/me` | 查询 | `read` |
| `list_accounts` | `GET /api/v1/accounts` | 查询 | `read` |
| `get_balance` | `GET /api/v1/accounts/{account_id}/balance` | 查询 | `read` |
| `list_transactions` | `GET /api/v1/accounts/{account_id}/transactions` | 查询 | `read` |
| `list_payees` | `GET /api/v1/payees` | 查询 | `read` |
| `resolve_payee_by_phone` | `GET /api/v1/payees/resolve` | 查询 | `read` |
| `add_payee` | `POST /api/v1/payees` | 直接生效 | `prepare` |
| `update_payee_alias` | `PATCH /api/v1/payees/{payee_id}` | 直接生效 | `prepare` |
| `remove_payee` | `DELETE /api/v1/payees/{payee_id}` | 直接生效 | `prepare` |
| `list_deposit_products` | `GET /api/v1/deposit/products` | 查询 | `read` |
| `list_deposit_holdings` | `GET /api/v1/deposit/holdings` | 查询 | `read` |
| `prepare_transfer` | `POST /api/v1/transfers/prepare` | 预处理 | `prepare` |
| `prepare_deposit` | `POST /api/v1/deposits/prepare` | 预处理 | `prepare` |
| `prepare_early_withdraw` | `POST /api/v1/deposits/{holding_id}/early-withdraw/prepare` | 预处理 | `prepare` |
| `get_operation` | `GET /api/v1/operations/{op_id}` | 查询 | `read` |
| `cancel_operation` | `POST /api/v1/operations/{op_id}/cancel` | 直接生效 | `prepare` |
| `precheck_transfer_risk` | `POST /api/v1/risk/precheck` | 查询 | `read` |
| `list_cards` | `GET /api/v1/cards` | 查询 | `read` |
| `get_card` | `GET /api/v1/cards/{card_id}` | 查询 | `read` |
| `freeze_card` | `POST /api/v1/cards/{card_id}/freeze` | 直接生效 | `protect` |
| `report_card_lost` | `POST /api/v1/cards/{card_id}/report-loss` | 直接生效 | `protect` |
| `close_card_controls` | `PUT /api/v1/cards/{card_id}/controls` | 直接生效 | `protect` |
| `lower_card_limits` | `PUT /api/v1/cards/{card_id}/limits` | 直接生效 | `protect` |
| `lower_account_limits` | `PUT /api/v1/accounts/{account_id}/limits` | 直接生效 | `protect` |
| `prepare_card_apply` | `POST /api/v1/cards/apply/prepare` | 预处理 | `prepare` |
| `prepare_card_unfreeze` | `POST /api/v1/cards/{card_id}/unfreeze/prepare` | 预处理 | `prepare` |
| `prepare_card_reissue` | `POST /api/v1/cards/{card_id}/reissue/prepare` | 预处理 | `prepare` |
| `prepare_card_controls` | `POST /api/v1/cards/{card_id}/controls/prepare` | 预处理 | `prepare` |
| `prepare_card_limits` | `POST /api/v1/cards/{card_id}/limits/prepare` | 预处理 | `prepare` |
| `prepare_account_limits` | `POST /api/v1/accounts/{account_id}/limits/prepare` | 预处理 | `prepare` |
| `list_mandates` | `GET /api/v1/mandates` | 查询 | `read` |
| `prepare_mandate_cancel` | `POST /api/v1/mandates/{mandate_id}/cancel/prepare` | 预处理 | `prepare` |
| `list_holds` | `GET /api/v1/accounts/{account_id}/holds` | 查询 | `read` |
| `create_hold` | `POST /api/v1/accounts/{account_id}/holds` | 直接生效 | `protect` |
| `prepare_hold_release` | `POST /api/v1/holds/{hold_id}/release/prepare` | 预处理 | `prepare` |
| `list_merchants` | `GET /api/v1/merchants` | 查询 | `read` |
| `prepare_merchant_payment` | `POST /api/v1/payments/merchant/prepare` | 预处理 | `prepare` |
| `get_events` | `GET /api/v1/events` | 查询 | `read` |
| `get_risk_profile` | `GET /api/v1/risk-profile` | 查询 | `read` |
| `get_risk_questionnaire` | `GET /api/v1/risk-profile/questionnaire` | 查询 | `read` |
| `list_wealth_products` | `GET /api/v1/wealth/products` | 查询 | `read` |
| `list_wealth_holdings` | `GET /api/v1/wealth/holdings` | 查询 | `read` |
| `prepare_wealth_subscribe` | `POST /api/v1/wealth/subscribe/prepare` | 预处理 | `prepare` |
| `prepare_wealth_redeem` | `POST /api/v1/wealth/redeem/prepare` | 预处理 | `prepare` |

### 8.2 工具定义示例（MCP `tools/list` 片段）

```json
{
  "name": "prepare_transfer",
  "description": "转账预处理：校验并做风控评估，创建待确认操作。不会扣款。返回 operation_id、预览、风险原因码和 confirm_url；必须引导用户打开 confirm_url 确认。收款方三选一：payee_id / (payee_account_no+payee_name) / (payee_phone+payee_name)。",
  "inputSchema": {
    "type": "object",
    "required": ["from_account_id", "amount"],
    "properties": {
      "from_account_id": { "type": "string", "description": "付款账户 id，如 acc_001" },
      "payee_id": { "type": "string", "description": "已保存收款人 id" },
      "payee_account_no": { "type": "string" },
      "payee_name": { "type": "string", "maxLength": 64, "description": "收款人完整户名，用于核验" },
      "payee_phone": { "type": "string", "description": "11 位手机号（澜台用户）" },
      "bank_code": { "type": "string", "description": "LANTAI（默认，行内）或 OTHER（他行）" },
      "amount": { "type": "string", "maxLength": 24, "pattern": "^\\d{1,12}(\\.\\d{1,2})?$", "description": "金额，字符串，最多两位小数" },
      "memo": { "type": "string", "maxLength": 200 },
      "idempotency_key": { "type": "string", "description": "同一次用户意图复用同一个键" },
      "agent_context": { "type": "object", "properties": { "intent_summary": { "type": "string" }, "user_utterance_excerpt": { "type": "string" } } }
    }
  }
}
```

### 8.3 实现建议

- **鉴权**：MCP 服务器启动时读取用户授予的 `agent_token`（环境变量或会话参数）；收到 `AUTH_EXPIRED` / `AUTH_REVOKED` 时返回明确提示，让 Agent 请用户重新授权，**不要自动重试**。
- **幂等键**：在 MCP 层为每个“用户意图”生成并缓存键（如对话轮次 id + 工具名 + 参数哈希），重试时复用。
- **限频**：遇到 `RATE_LIMITED` 读取 `details.retry_after_seconds` 后退避，不要立即重试；`TOO_MANY_PENDING` 时先提醒用户处理或取消已有待确认操作。
- **余额**：错误与摘要里不再有余额，需要时显式调用 `get_balance`，并仅在用户需要时展示。
- **错误透传**：把 `error.code` / `error.message` / `error.details` 原样返回给模型，不要吞掉；`CONFIRM_REQUIRED` 的 `details.use` 直接告诉了应改调的接口。
- **结果裁剪**：`list_transactions` 默认 `limit=20`，需要更多再翻页；避免一次性塞入上百条流水撑爆上下文。
- **`get_operation` 轮询**：由 MCP 工具内部或 Agent 控制，建议 2~3 秒一次，遇终态或超过 5 分钟停止；也可改用 `get_events` 的 `operation` 事件。
- **时间**：服务端时区由 `TIMEZONE_OFFSET` 决定（默认 +01:00），夜间规则按该时区的 0~6 点。

## 9. Agent 行为守则

1. **先解释再引导**：prepare 之后向用户复述收款方/金额/手续费，说明每条 `reasons[].message`，再给出 `confirm_url`。不要说“已转账”，只有 `status=EXECUTED` 才算完成。
2. **不替用户确认、不索要 OTP**：验证码只会出现在用户界面；用户如果把验证码发给你，也无法用它完成确认。
3. **被拦截就停**：`BLOCKED` 不要换收款账户、拆分金额或换卡重试来绕过风控；向用户说明原因并建议核实/联系反诈热线。
4. **识别软风险**：用户提到“公安/客服让转到安全账户”“催促、保密”等话术时，在调用任何转账接口前先劝阻（这是 Agent 层的职责，后端只做硬规则）。
5. **收紧可先做，放宽要问**：用户说卡丢了可立即冻结或挂失；解冻、提额、开境外必须走 prepare 并让用户确认。挂失不可撤销，执行前再确认一次。
6. **信息不全不要猜**：重名收款人、缺少户名、金额含糊时先追问；可先用 `precheck_transfer_risk` 探路。
7. **隐私**：只向用户展示脱敏账号；`resolve_payee_by_phone` 的结果不要外泄给第三方。

## 10. 演示数据速查

重置后（`POST /admin/reset`，管理接口）的种子数据，便于联调：

| 类别 | 内容 |
|---|---|
| 用户（演示口令默认 `Lantai@2026`，可由 `SEED_PASSWORD` 覆盖，仅限本地） | 测试1 `13800000001`（主演示，风险等级 R3 平衡型）、测试2 `13900000002`（未测评）、张三 `13600000003`、李四 `13700000004` |
| 测试1 的账户 | `acc_001` 活期 50,800.00；`acc_002` 储蓄 120,000.00；单笔限额 50,000，单日 100,000 |
| 测试1 的卡 | `crd_001`（acc_001）、`crd_002`（acc_002）；单笔 20,000 / 单日 50,000；线上、ATM 开，境外关 |
| 收款人 | `pye_001` 李四（行内，已转过）、`pye_002` 王五（他行，已转过） |
| 新收款人演示 | 账号 `6217000040003456`，户名 `张三`（写成“张山”触发户名不符） |
| 黑名单 | 他行账号 `6222000088886666`（刘某某），`bank_code=OTHER` |
| 定期 | 产品 `prd_3m / prd_6m / prd_12m / prd_36m`；持有 `hld_001`（2 万，已过 30 天） |
| 代扣协议 | `apy_001` 房东 3500、`apy_002` 信用卡中心 2000、`apy_003` 澜视频会员 25、`apy_004` 澜云盘 9、`apy_005` 澜音乐 15 |
| 商户 | `mch_flower` 澜花坊、`mch_cake` 甜时光蛋糕、`mch_video` 澜视频会员、`mch_mart` 澜选超市、`mch_global` 境外礼品商城；`mch_risky` 为风险商户（不在目录，支付会被拦截） |
| 理财 | `wp_money`(R1) `wp_bond`(R2) `wp_mix`(R3) `wp_growth`(R4) `wp_tech`(R5)；测试1 买 R4 需 OTP，买 R5 被拦截 |
| 流水 | `acc_001` 近 14 个月历史，含周期性订阅扣款、一笔大额消费、一笔凌晨境外消费 |

## 11. 不属于 Agent 的接口

以下接口由用户界面或演示管理使用，**不应做成 MCP 工具**；Agent 令牌调用 `/ui/*` 会被拒绝并记入审计。

| 前缀 | 用途 | 说明 |
|---|---|---|
| `/ui/*` | 登录（含防暴破限频）、退出（可同时撤销全部 Agent 令牌）、签发/撤销 Agent 令牌、查看待确认操作、OTP 提示与验证、**确认/拒绝**、提交风险测评、审计 | 仅 `user_session`；确认权的唯一入口；生产模式下 `otp-hint` 关闭 |
| `/admin/*` | 重置数据、模拟时钟、黑名单、模拟商户扣款、调整净值、锁定卡片 | 需 `X-Admin-Key`，仅演示；生产模式默认关闭（`NOT_FOUND`），启用时要求强随机密钥 |

---

*附：开发环境可从 `GET /openapi.json` 获取接口权威描述（含 `/ui`、`/admin`），Swagger 为 `/docs`；生产模式（`APP_ENV=prod`）默认关闭，以本文为准。*
