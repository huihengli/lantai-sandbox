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

createApp(App).use(router).mount("#app");
