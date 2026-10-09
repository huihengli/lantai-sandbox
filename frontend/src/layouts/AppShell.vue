<script setup>
import { onBeforeUnmount, onMounted } from "vue";
import { useRouter } from "vue-router";
import {
  PhHouse, PhArrowsLeftRight, PhVault, PhShieldCheck, PhKey, PhClockCounterClockwise,
  PhSlidersHorizontal, PhSun, PhMoon, PhSignOut, PhListBullets,
} from "@phosphor-icons/vue";
import SealLogo from "../components/SealLogo.vue";
import { api } from "../api";
import { clearSession, session, setTheme } from "../stores/session";
import { ACTIVE_STATUS } from "../utils";

const router = useRouter();
const nav = [
  { to: "/", label: "总览", icon: PhHouse, exact: true },
  { to: "/transactions", label: "账户流水", icon: PhListBullets },
  { to: "/transfer", label: "转账", icon: PhArrowsLeftRight },
  { to: "/deposits", label: "定期存款", icon: PhVault },
  { to: "/confirm", label: "确认中心", icon: PhShieldCheck, badge: true },
  { to: "/grants", label: "助手授权", icon: PhKey },
  { to: "/audit", label: "审计记录", icon: PhClockCounterClockwise },
  { to: "/demo", label: "演示控制台", icon: PhSlidersHorizontal },
];

let timer;
async function refreshPending() {
  if (document.hidden || !session.token) return;
  try {
    session.pending = (await api.operations(ACTIVE_STATUS.join(","))).length;
  } catch { /* 轮询失败不打扰用户；鉴权失效由 client 统一处理 */ }
}
onMounted(() => { refreshPending(); timer = setInterval(refreshPending, 4000); });
onBeforeUnmount(() => clearInterval(timer));

async function logout() {
  try { await api.logout(); } catch { /* 即使服务端失败也清本地会话 */ }
  clearSession();
  router.replace({ name: "login" });
}
const toggleTheme = () => setTheme(session.theme === "dark" ? "light" : "dark");
</script>

<template>
  <div class="shell">
    <aside class="side">
      <RouterLink to="/" class="brand" aria-label="澜台首页">
        <SealLogo :size="42" />
        <span>
          <strong>澜台</strong>
          <small>LANTAI · 数字金融</small>
        </span>
      </RouterLink>

      <nav aria-label="主导航" class="nav">
        <RouterLink
          v-for="item in nav"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          :exact-active-class="item.exact ? 'active' : ''"
          :active-class="item.exact ? '' : 'active'"
        >
          <component :is="item.icon" :size="20" aria-hidden="true" />
          <span>{{ item.label }}</span>
          <span v-if="item.badge && session.pending" class="badge" :aria-label="`${session.pending} 项待处理`">{{ session.pending }}</span>
        </RouterLink>
      </nav>

      <div class="foot">
        <div class="who">
          <span class="avatar" aria-hidden="true">{{ session.user?.name?.slice(0, 1) }}</span>
          <span>
            <strong>{{ session.user?.name }}</strong>
            <small class="muted">{{ session.user?.phone_masked }}</small>
          </span>
        </div>
        <div class="row">
          <button
            class="btn small icon"
            type="button"
            :aria-label="session.theme === 'dark' ? '切换为宣纸日间主题' : '切换为墨色夜间主题'"
            @click="toggleTheme"
          >
            <component :is="session.theme === 'dark' ? PhSun : PhMoon" :size="18" aria-hidden="true" />
          </button>
          <button class="btn small" type="button" @click="logout"><PhSignOut :size="18" aria-hidden="true" />退出</button>
        </div>
        <p class="sim muted">模拟环境 · 仅供演示</p>
      </div>
    </aside>

    <main id="main" class="main" tabindex="-1">
      <div class="page-enter"><RouterView :key="$route.path.split('/')[1]" /></div>
    </main>
  </div>
</template>

<style scoped>
.shell { display: grid; grid-template-columns: var(--sidebar-w) minmax(0, 1fr); min-height: 100vh; }
.shell > * { min-width: 0; }
.side {
  position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; gap: var(--space-5);
  padding: var(--space-5) var(--space-4); background: color-mix(in srgb, var(--c-surface) 92%, transparent);
  border-right: 1px solid var(--c-border); backdrop-filter: blur(6px);
}
.side::after { content: ""; position: absolute; top: 0; right: -1px; width: 1px; height: 96px; background: linear-gradient(var(--c-accent), transparent); }
.brand { display: flex; align-items: center; gap: 12px; text-decoration: none; color: var(--c-text); }
.brand strong { display: block; font-family: var(--font-serif); font-size: 1.5rem; letter-spacing: 0.3em; line-height: 1.1; }
.brand small { color: var(--c-accent); font-size: 0.68rem; letter-spacing: 0.18em; }
.nav { display: flex; flex-direction: column; gap: 4px; flex: 1; overflow-y: auto; }
.nav-item {
  display: flex; align-items: center; gap: 12px; min-height: var(--tap-min); padding: 0 var(--space-3);
  color: var(--c-text-muted); text-decoration: none; border-left: 2px solid transparent; border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  transition: color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
}
.nav-item:hover { color: var(--c-text); background: color-mix(in srgb, var(--c-accent) 8%, transparent); }
.nav-item.active { color: var(--c-accent); border-left-color: var(--c-primary); background: linear-gradient(90deg, color-mix(in srgb, var(--c-accent) 16%, transparent), transparent); font-weight: 600; }
.badge { margin-left: auto; min-width: 22px; padding: 0 6px; text-align: center; border-radius: 999px; background: var(--c-primary); color: #fff; font-size: 0.75rem; line-height: 22px; }
.foot { display: flex; flex-direction: column; gap: var(--space-3); border-top: 1px solid var(--c-border); padding-top: var(--space-4); }
.who { display: flex; align-items: center; gap: 10px; }
.who strong { display: block; line-height: 1.2; }
.avatar { width: 38px; height: 38px; display: grid; place-items: center; border: 1px solid var(--c-accent); border-radius: 4px; color: var(--c-accent); font-family: var(--font-serif); font-size: 1.1rem; }
.sim { font-size: 0.72rem; letter-spacing: 0.12em; }
.main { padding: var(--space-6) var(--space-6) var(--space-7); max-width: 1180px; width: 100%; margin: 0 auto; outline: none; }

@media (max-width: 900px) {
  .shell { grid-template-columns: minmax(0, 1fr); }
  .side { position: sticky; z-index: 20; height: auto; flex-direction: row; flex-wrap: wrap; align-items: center; gap: var(--space-3); padding: 10px 16px; border-right: 0; border-bottom: 1px solid var(--c-border); }
  .side::after { display: none; }
  .brand small { display: none; }
  .brand strong { font-size: 1.2rem; }
  .brand :deep(svg) { width: 34px; height: 34px; }
  .nav { order: 3; flex: 1 0 100%; scrollbar-width: thin; flex-direction: row; overflow-x: auto; gap: 2px; padding-bottom: 2px; }
  .nav-item { flex: none; border-left: 0; border-bottom: 2px solid transparent; border-radius: 0; padding: 0 12px; }
  .nav-item.active { border-bottom-color: var(--c-primary); background: none; }
  .nav-item span:not(.badge) { white-space: nowrap; }
  .foot { order: 2; margin-left: auto; flex-direction: row; align-items: center; border: 0; padding: 0; }
  .who, .sim { display: none; }
  .main { padding: var(--space-5) 16px var(--space-7); }
}
</style>
