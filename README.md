# 澜台（Lantai）模拟银行后端

设计依据：[架构建议.md](架构建议.md)、[澜台后端方案.md](澜台后端方案.md)。

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
未包含 Redis：幂等、令牌、OTP、限额统计都落库，当前没有需要它的场景。

入口（后端默认端口 8001）：Swagger `/docs` · 健康检查 `/healthz`；前端构建后由后端直接托管在 `/`。

## 前端

```bash
cd frontend
pnpm install
pnpm dev        # 开发：http://localhost:5173，自动代理 /api /ui /admin 到 http://localhost:8001
pnpm build      # 产出 frontend/dist，后端检测到后自动托管（访问后端根路径即可）
```

- 开发模式下让 `prepare` 返回的 `confirm_url` 指向 5173：后端设 `FRONTEND_BASE_URL=http://localhost:5173`；后端地址不同则设 `frontend/.env.local` 的 `VITE_API_TARGET`。
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
| 林清（主演示） | 13800000001 | `acc_001` 活期 50,800 · `acc_002` 储蓄 120,000 |
| 周敏（归属校验） | 13900000002 | `acc_101` |
| 张三 / 李四（行内收款方） | 13600000003 / 13700000004 | `acc_201` / `acc_301` |

林清的收款人：`pye_001` 李四（行内）、`pye_002` 王五（他行）。黑名单账户：他行 `6222000088886666`（刘某某）。
新收款人演示：账号 `6217000040003456`，户名 `张三`（写成 `张山` 触发户名不符）。定期持有 `hld_001`（2 万，已过 30 天）。

## 双通道流程

1. 用户在前端登录 → 点“签发 Agent 令牌” → 把 `agent_token` 交给 Agent。
2. Agent 用 `Authorization: Bearer <agent_token>` 调 `/api/v1/*`：查询、`prepare`、`risk/precheck`、取消。
3. `prepare` 返回 `operation_id`、预览、风险原因码和 `confirm_url`。Agent 引导用户打开页面。
4. 用户在前端“确认中心”查看风险原因，需要时输入 OTP（演示固定 `123456`，只在 `/ui` 通道可见），点击确认。
5. Agent 轮询 `GET /api/v1/operations/{id}` 得到结果。Agent 调用任何 `/ui/*` 接口都返回 `CHANNEL_NOT_ALLOWED`。

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

## 规则触发速查（林清，白天）

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
