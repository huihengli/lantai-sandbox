import { session, clearSession } from "../stores/session";

export class ApiError extends Error {
  constructor(error, status) {
    super(error?.message || "请求失败");
    this.code = error?.code || "NETWORK_ERROR";
    this.details = error?.details || {};
    this.status = status;
  }
}

const AUTH_CODES = new Set(["AUTH_INVALID", "AUTH_EXPIRED", "AUTH_REVOKED"]);

export async function request(method, path, { body, query, headers = {}, auth = true } = {}) {
  const url = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(query || {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  }
  const h = { Accept: "application/json", ...headers };
  if (body !== undefined) h["Content-Type"] = "application/json";
  if (auth && session.token) h.Authorization = `Bearer ${session.token}`;

  let res;
  try {
    res = await fetch(url, { method, headers: h, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError({ code: "NETWORK_ERROR", message: "无法连接澜台服务，请确认后端已启动" }, 0);
  }
  let json;
  try { json = await res.json(); } catch { json = null; }
  if (!json || json.ok !== true) {
    const err = new ApiError(json?.error || { code: "BAD_RESPONSE", message: `服务返回异常（${res.status}）` }, res.status);
    if (auth && AUTH_CODES.has(err.code)) clearSession(true);
    throw err;
  }
  return json.data;
}

export const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(16).slice(2)}`);
