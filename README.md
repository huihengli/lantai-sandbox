# 澜台（Lantai）模拟银行后端

```
backend/   FastAPI 服务（app/ 源码，tests/ 测试）
frontend/  Vue 3 + Vite 前端（中国风科技感：墨色夜 / 宣纸日双主题）
infra/     compose.yml（PostgreSQL + 后端服务）
```

## 启动

**方式 A：仅 SQLite，零依赖（最快）**

```bash
cd backend
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8001
```

数据文件 `backend/data/lantai.db`，首次启动自动建表并灌入种子数据。

**方式 B：Docker Compose（PostgreSQL）**

```bash
docker compose -f infra/compose.yml up -d --build      # 数据库 + 后端
docker compose -f infra/compose.yml up -d db           # 只起数据库，后端本地跑
# 本地后端连 compose 的数据库：
# DATABASE_URL=postgresql+psycopg://lantai:lantai_dev@localhost:15432/lantai
```

可用环境变量：`POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB / POSTGRES_PORT(15432) / BACKEND_PORT(8001) / ADMIN_KEY / PUBLIC_BASE_URL / TIMEZONE_OFFSET`。
生产/加固开关（后端）：`APP_ENV=prod` 时默认关闭 `/admin`、`/docs`、OTP 演示取码，并要求显式的强 `ADMIN_KEY`（≥24 位）与非默认数据库口令；可单独用 `ADMIN_ENABLED / DOCS_ENABLED / OTP_DEMO_MODE / OTP_PEPPER / SEED_PASSWORD / PASSWORD_ITERATIONS` 覆盖。前端演示控制台与登录页演示账号仅在 `pnpm dev` 或构建时设 `VITE_ENABLE_DEMO=1` 时可用。数据库端口与后端端口默认只绑定 127.0.0.1。无表结构变更，旧库无需重建；旧口令哈希会在登录成功后自动升级。

未包含 Redis：幂等、令牌、OTP、限额统计都落库，当前没有需要它的场景。

入口（后端默认端口 8001）：Swagger `/docs` · 健康检查 `/healthz`；前端构建后由后端直接托管在 `/`。

## 前端

```bash
cd frontend
pnpm install
pnpm dev        # 开发：http://localhost:5172，自动代理 /api /ui /admin 到 http://localhost:8001
pnpm build      # 产出 frontend/dist，后端检测到后自动托管（访问后端根路径即可）
```

- 开发模式下让 `prepare` 返回的 `confirm_url` 指向 5172：后端设 `FRONTEND_BASE_URL=http://localhost:5172`；后端地址不同则设 `frontend/.env.local` 的 `VITE_API_TARGET`。
- 页面：总览 · 账户流水 · 转账 · 定期存款 · **确认中心**（风险原因、OTP、确认/拒绝） · 助手授权（签发/撤销 Agent 令牌） · 审计记录 · 演示控制台（重置、模拟时钟、黑名单、一键触发风控规则）。
- 设计依据：项目内 `.agents/skills/ui-ux-pro-max` 与 `design-system`（三层令牌、对比度 ≥ 4.5:1、可见焦点、减少动效、Phosphor 图标、44px 触控目标）。令牌见 `frontend/src/styles/tokens.css`。

## 测试

```bash
cd backend && python -m pytest -q
```

测试使用内存 SQLite，每个用例重置数据并固定模拟时钟到白天 14:00。

## 演示账号（密码均为 `Lantai@2026`，仅本地）

| 用户 | 手机 | 账户 |
|---|---|---|
| 测试1（主演示） | 13800000001 | `acc_001` 活期 50,800 · `acc_002` 储蓄 120,000 |
| 测试2（归属校验） | 13900000002 | `acc_101` |
| 张三 / 李四（行内收款方） | 13600000003 / 13700000004 | `acc_201` / `acc_301` |

测试1的收款人：`pye_001` 李四（行内）、`pye_002` 王五（他行）。黑名单账户：他行 `6222000088886666`（刘某某）。
新收款人演示：账号 `6217000040003456`，户名 `张三`（写成 `张山` 触发户名不符）。定期持有 `hld_001`（2 万，已过 30 天）。

## 双通道流程

1. 用户在前端登录 → 点“签发 Agent 令牌” → 把 `agent_token` 交给 Agent。
2. Agent 用 `Authorization: Bearer <agent_token>` 调 `/api/v1/*`：查询、`prepare`、`risk/precheck`、取消。
3. `prepare` 返回 `operation_id`、预览、风险原因码和 `confirm_url`。Agent 引导用户打开页面。
4. 用户在前端“确认中心”查看风险原因，需要时输入 OTP（演示固定 `123456`，只在 `/ui` 通道可见），点击确认。
5. Agent 轮询 `GET /api/v1/operations/{id}` 得到结果。Agent 调用任何 `/ui/*` 接口都返回 `CHANNEL_NOT_ALLOWED`。
6. 可选的**确认执行器**路径：用户在 `/ui/executor-grants` 签发执行器令牌（`lt_x_*`，仅 `confirm/otp`），交给 Agent 侧独立的执行器程序；执行器弹出确认框，用户手动确认（必要时输入 OTP）后调用 `/api/exec/operations/{id}/verify-otp|confirm|reject`。执行器令牌只能访问 `/api/exec`，Agent 令牌与用户会话也不能访问 `/api/exec`。详见接口文档第 12 节。

curl 示例：

```bash
curl -s localhost:8001/ui/login -H 'content-type: application/json' \
  -d '{"phone":"13800000001","password":"Lantai@2026"}'
curl -s localhost:8001/api/v1/transfers/prepare -H "Authorization: Bearer $AGENT_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"from_account_id":"acc_001","payee_id":"pye_001","amount":"500.00","idempotency_key":"demo-1"}'
```

## 演示辅助（`X-Admin-Key: dev-admin-key`）

| 接口 | 用途 |
|---|---|
| `POST /admin/reset` | 清库并重灌种子数据 |
| `POST /admin/clock` `{"set_time":"2026-10-09T02:30:00"}` / `{"advance_seconds":301}` | 触发夜间规则、操作过期 |
| `DELETE /admin/clock` | 恢复真实时间 |
| `GET/POST/DELETE /admin/blacklist` | 黑名单管理 |
| `GET /admin/audit` | 全量审计 |

## 规则触发速查（测试1，白天）

| 规则 | 操作 |
|---|---|
| `BLACKLIST_HIT` | 转 1,000 到 `6222000088886666`（bank_code=OTHER） |
| `SINGLE_LIMIT_EXCEEDED` | `acc_002` 转李四 60,000 |
| `DAILY_LIMIT_EXCEEDED` | `acc_002` 向李四连续确认 3 笔 30,000，第 4 笔 |
| `NEW_PAYEE` | 向张三 `6217000040003456` 转 2,000 |
| `LARGE_AMOUNT` | `acc_002` 转李四 50,000 |
| `HIGH_BALANCE_RATIO` | `acc_001` 转李四 42,000 |
| `RAPID_REPEAT` | 10 分钟内向李四确认 2 笔后发第 3 笔 |
| `NIGHT_TRANSACTION` | 先把时钟设为 02:30 再转 500 |
| `AUTOPAY_AT_RISK` | `acc_001` 转 46,000 |
| `CROSS_BANK_FEE` | 转王五 5,000（手续费 5.00） |
| `PAYEE_NAME_MISMATCH` | 向 `6217000040003456` 转账但户名写“张山” |
| `EARLY_WITHDRAW_LOSS` | 对 `hld_001` 发起提前支取 |

## 能力清单（按模块，对应 `澜台基础能力边界.md`）

| 模块 | 接口 | 说明 |
|---|---|---|
| 1 流水增强 | `GET /api/v1/accounts/{id}/transactions?keyword=&counterparty=&merchant_category=` | 备注/对方关键词、商户品类检索；种子含 14 个月历史、周期性扣款、异常交易 |
| 2 收款人管理 | `GET/POST /api/v1/payees`、`PATCH/DELETE /api/v1/payees/{id}`、`GET /api/v1/payees/resolve?phone=` | 添加（行内核验户名、拦截黑名单）、备注名、软删除、搜索；手机号仅返回脱敏户名并限频；转账支持 `payee_phone` + 完整户名 |
| 3 卡片与额度 | `GET /cards`；`POST /cards/{id}/freeze`（`protect` 直接生效）；`POST /cards/{id}/report-loss/prepare`（挂失不可撤销，需用户确认）；`PUT /cards/{id}/controls`、`/limits`、`PUT /accounts/{id}/limits`（仅收紧）；`POST /cards/apply/prepare`、`/cards/{id}/unfreeze\|reissue\|controls\|limits/prepare`、`/accounts/{id}/limits/prepare`（放宽，需确认） | **收紧立即生效，放宽需确认**；新增 `protect` 令牌范围；演示用 `POST /admin/cards/{id}/lock` 模拟卡片锁定 |
| 4 代扣协议 | `GET /api/v1/mandates?status=`、`POST /api/v1/mandates/{id}/cancel/prepare` | 协议列表（商户、金额、周期、下次扣款日）与取消（需确认）；订阅识别/续费提醒归 Agent；演示用 `POST /admin/mandates/{id}/charge` 模拟商户扣款 |
| 5 资金预留 | `GET/POST /api/v1/accounts/{id}/holds`（创建需 `protect`，直接生效）、`POST /api/v1/holds/{id}/release/prepare` | 预留（锁定）一笔资金，不可转出/存入定期/代扣；余额接口新增 `held` 与 `available`；到期惰性失效；释放需用户确认 |
| 6 商户支付 | `GET /api/v1/merchants`、`POST /api/v1/payments/merchant/prepare`（card_id、merchant_id、amount、order_ref、channel） | 受卡片状态/开关/额度、商户风险（含风险商户拦截）、首次商户与境外 OTP、可用余额约束；订单号防重复支付；确认时复核 |
| 7 事件流 | `GET /api/v1/events?after_id=&limit=&types=` | 递增只读事件流（入账/扣款 `txn_in/txn_out`、操作状态 `operation`、`card`、`account`、`mandate`、`hold`），按用户隔离；Agent 记住 `next_after_id` 轮询即可做提醒、对账与定时触发 |
| 8 理财与适当性 | `GET /api/v1/risk-profile`（及 `/questionnaire`）、`PUT /ui/risk-profile`（仅用户通道）、`GET /api/v1/wealth/products\|holdings`、`POST /api/v1/wealth/subscribe\|redeem/prepare` | 5 款净值型产品（R1~R5）、风险测评（银行按答案计算，Agent 无法提交，12 个月有效）、适当性硬规则（高一级需 OTP，高两级及未测评/过期拦截）、申购/赎回含盈亏；**定期到期惰性结算**（任意鉴权请求触发，无需调度器）；演示用 `POST /admin/wealth/{id}/nav` 调整净值 |

## 升级后必读：数据库需要重建

模块 1~8 给多张旧表增加了列（如 `users.risk_level`、`payees.alias`），而 `create_all` 不会给已有表补列。**旧的 `backend/data/lantai.db`（或旧的 Postgres 数据卷）必须重建**，并且**后端进程必须重启**才会加载新接口。

- 后端启动时会自检结构：不一致则拒绝启动并提示原因。
- 重建方式：删除 `backend/data/lantai.db` 后重启；或设置 `RESET_DB_ON_START=1` 启动一次（会清空数据并重灌种子）；Postgres 执行 `docker compose -f infra/compose.yml down -v`。
- 前端遇到未处理的接口失败会弹出提示（例如 404“后端可能还是旧版本”），不再静默无反应。
