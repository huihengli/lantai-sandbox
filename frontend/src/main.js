import { createApp } from "vue";
import "@fontsource/noto-serif-sc/700.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import App from "./App.vue";
import router from "./router";
import { onSessionExpire, toast } from "./stores/session";

onSessionExpire(() => {
  toast("登录已失效，请重新登录", "warn");
  router.replace({ name: "login", query: { redirect: router.currentRoute.value.fullPath } });
});

// 兜底：页面里没处理的接口失败（如后端版本过旧、网络断开）至少要让用户看到原因，而不是点了没反应
window.addEventListener("unhandledrejection", (event) => {
  const err = event.reason;
  if (err?.code?.startsWith?.("AUTH_")) return; // 登录失效已有统一提示
  toast(err?.message || "操作失败，请稍后重试", "bad", 7000);
});

createApp(App).use(router).mount("#app");
