import { reactive } from "vue";

const TOKEN_KEY = "lt_session";
const USER_KEY = "lt_user";

function read(key) {
  try { return sessionStorage.getItem(key); } catch { return null; }
}
function write(key, value) {
  try { value == null ? sessionStorage.removeItem(key) : sessionStorage.setItem(key, value); } catch { /* 隐私模式下忽略 */ }
}

export const session = reactive({
  token: read(TOKEN_KEY) || "",
  user: JSON.parse(read(USER_KEY) || "null"),
  pending: 0, // 待确认操作数（导航红点）
  theme: document.documentElement.getAttribute("data-theme") || "dark",
  toasts: [],
});

let expireHandler = () => {};
export const onSessionExpire = (fn) => { expireHandler = fn; };

export function setSession(token, user) {
  session.token = token;
  session.user = user;
  write(TOKEN_KEY, token);
  write(USER_KEY, JSON.stringify(user));
}

export function clearSession(notify = false) {
  session.token = "";
  session.user = null;
  session.pending = 0;
  write(TOKEN_KEY, null);
  write(USER_KEY, null);
  if (notify) expireHandler();
}

export function setTheme(theme) {
  session.theme = theme;
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("lt_theme", theme); } catch { /* 忽略 */ }
}

let toastId = 0;
export function toast(message, kind = "ok", ms = 4200) {
  const item = { id: ++toastId, message, kind };
  session.toasts.push(item);
  setTimeout(() => {
    const i = session.toasts.findIndex((t) => t.id === item.id);
    if (i >= 0) session.toasts.splice(i, 1);
  }, ms);
}
