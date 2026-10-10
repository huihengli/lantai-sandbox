import { request, uuid } from "./client";

const adminHeaders = (key) => ({ "X-Admin-Key": key });

export const api = {
  // ---- 用户通道 /ui ----
  login: (phone, password) => request("POST", "/ui/login", { body: { phone, password }, auth: false }),
  logout: () => request("POST", "/ui/logout"),
  grants: () => request("GET", "/ui/agent-grants"),
  createGrant: (ttl_seconds) => request("POST", "/ui/agent-grants", { body: { scopes: ["read", "prepare", "protect"], ttl_seconds } }),
  revokeGrant: (id) => request("DELETE", `/ui/agent-grants/${id}`),
  operations: (status) => request("GET", "/ui/operations", { query: { status } }),
  operation: (id) => request("GET", `/ui/operations/${id}`),
  otpHint: (id) => request("GET", `/ui/operations/${id}/otp-hint`),
  verifyOtp: (id, code) => request("POST", `/ui/operations/${id}/verify-otp`, { body: { code } }),
  confirm: (id) => request("POST", `/ui/operations/${id}/confirm`),
  reject: (id) => request("POST", `/ui/operations/${id}/reject`),
  audit: () => request("GET", "/ui/audit"),

  // ---- 业务通道 /api/v1（用户会话同样可用） ----
  me: () => request("GET", "/api/v1/me"),
  accounts: () => request("GET", "/api/v1/accounts"),
  balance: (id) => request("GET", `/api/v1/accounts/${id}/balance`),
  transactions: (id, query) => request("GET", `/api/v1/accounts/${id}/transactions`, { query }),
  payees: (q) => request("GET", "/api/v1/payees", { query: { q } }),
  addPayee: (body) => request("POST", "/api/v1/payees", { body }),
  updatePayee: (id, alias) => request("PATCH", `/api/v1/payees/${id}`, { body: { alias } }),
  removePayee: (id) => request("DELETE", `/api/v1/payees/${id}`),
  resolvePhone: (phone) => request("GET", "/api/v1/payees/resolve", { query: { phone } }),
  cards: () => request("GET", "/api/v1/cards"),
  freezeCard: (id) => request("POST", `/api/v1/cards/${id}/freeze`),
  reportLoss: (id) => request("POST", `/api/v1/cards/${id}/report-loss`),
  setControls: (id, body) => request("PUT", `/api/v1/cards/${id}/controls`, { body }),
  prepareControls: (id, body) => request("POST", `/api/v1/cards/${id}/controls/prepare`, { body: { idempotency_key: uuid(), ...body } }),
  setCardLimits: (id, body) => request("PUT", `/api/v1/cards/${id}/limits`, { body }),
  prepareCardLimits: (id, body) => request("POST", `/api/v1/cards/${id}/limits/prepare`, { body: { idempotency_key: uuid(), ...body } }),
  setAccountLimits: (id, body) => request("PUT", `/api/v1/accounts/${id}/limits`, { body }),
  prepareAccountLimits: (id, body) => request("POST", `/api/v1/accounts/${id}/limits/prepare`, { body: { idempotency_key: uuid(), ...body } }),
  prepareUnfreeze: (id) => request("POST", `/api/v1/cards/${id}/unfreeze/prepare`, { body: { idempotency_key: uuid() } }),
  prepareReissue: (id) => request("POST", `/api/v1/cards/${id}/reissue/prepare`, { body: { idempotency_key: uuid() } }),
  prepareCardApply: (account_id) => request("POST", "/api/v1/cards/apply/prepare", { body: { idempotency_key: uuid(), account_id } }),
  mandates: (status) => request("GET", "/api/v1/mandates", { query: { status } }),
  prepareMandateCancel: (id) => request("POST", `/api/v1/mandates/${id}/cancel/prepare`, { body: { idempotency_key: uuid() } }),
  products: () => request("GET", "/api/v1/deposit/products"),
  holdings: () => request("GET", "/api/v1/deposit/holdings"),
  precheck: (body) => request("POST", "/api/v1/risk/precheck", { body }),
  prepareTransfer: (body) => request("POST", "/api/v1/transfers/prepare", { body: { idempotency_key: uuid(), ...body } }),
  prepareDeposit: (body) => request("POST", "/api/v1/deposits/prepare", { body: { idempotency_key: uuid(), ...body } }),
  prepareEarlyWithdraw: (holdingId) =>
    request("POST", `/api/v1/deposits/${holdingId}/early-withdraw/prepare`, { body: { idempotency_key: uuid() } }),

  // ---- 演示管理 /admin ----
  admin: {
    reset: (key) => request("POST", "/admin/reset", { headers: adminHeaders(key), auth: false }),
    setClock: (key, body) => request("POST", "/admin/clock", { body, headers: adminHeaders(key), auth: false }),
    resetClock: (key) => request("DELETE", "/admin/clock", { headers: adminHeaders(key), auth: false }),
    blacklist: (key) => request("GET", "/admin/blacklist", { headers: adminHeaders(key), auth: false }),
    addBlacklist: (key, body) => request("POST", "/admin/blacklist", { body, headers: adminHeaders(key), auth: false }),
    removeBlacklist: (key, id) => request("DELETE", `/admin/blacklist/${id}`, { headers: adminHeaders(key), auth: false }),
  },
};
