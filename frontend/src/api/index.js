import { request, uuid } from "./client";

const adminHeaders = (key) => ({ "X-Admin-Key": key });

export const api = {
  // ---- 用户通道 /ui ----
  login: (phone, password) => request("POST", "/ui/login", { body: { phone, password }, auth: false }),
  logout: () => request("POST", "/ui/logout"),
  grants: () => request("GET", "/ui/agent-grants"),
  createGrant: (ttl_seconds) => request("POST", "/ui/agent-grants", { body: { scopes: ["read", "prepare"], ttl_seconds } }),
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
  payees: () => request("GET", "/api/v1/payees"),
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
