<script setup>
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { PhSignIn, PhWarningCircle, PhEye, PhEyeSlash, PhLockKey } from "@phosphor-icons/vue";
import SealLogo from "../components/SealLogo.vue";
import MountainArt from "../components/MountainArt.vue";
import { api } from "../api";
import { setSession } from "../stores/session";
import { errorText } from "../utils";

const route = useRoute();
const router = useRouter();
const phone = ref("");
const password = ref("");
const showPwd = ref(false);
const loading = ref(false);
const error = ref("");

const demos = [
  { name: "测试1", phone: "13800000001", note: "主演示账户" },
  { name: "测试2", phone: "13900000002", note: "越权校验演示" },
];

function fillDemo(d) {
  phone.value = d.phone;
  password.value = "Lantai@2026";
  error.value = "";
}

async function submit() {
  error.value = "";
  if (!phone.value || !password.value) {
    error.value = "请输入手机号和密码";
    return;
  }
  loading.value = true;
  try {
    const data = await api.login(phone.value.trim(), password.value);
    setSession(data.session_token, data.user);
    router.replace(typeof route.query.redirect === "string" ? route.query.redirect : "/");
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main id="main" class="login">
    <section class="hero" aria-label="品牌介绍">
      <MountainArt />
      <div class="hero-inner">
        <SealLogo :size="64" />
        <h1>澜台</h1>
        <p class="slogan">澜涌千重，台筑一方<br />稳健守护每一笔流转</p>
        <ul class="points">
          <li><span class="dia" aria-hidden="true"></span>后端硬规则：限额、黑名单、归属校验</li>
          <li><span class="dia" aria-hidden="true"></span>智能助手只读与预处理，确认权在您手中</li>
          <li><span class="dia" aria-hidden="true"></span>每一次操作留痕，可追溯可解释</li>
        </ul>
      </div>
    </section>

    <section class="form-side">
      <form class="panel form" novalidate @submit.prevent="submit">
        <span class="eyebrow">欢迎回来</span>
        <h2>登录澜台</h2>

        <div class="field">
          <label for="phone">手机号</label>
          <input id="phone" v-model="phone" class="input" :class="{ invalid: error }" type="tel" inputmode="numeric" autocomplete="username" placeholder="请输入 11 位手机号" />
        </div>
        <div class="field">
          <label for="pwd">密码</label>
          <div class="pwd">
            <input id="pwd" v-model="password" class="input" :class="{ invalid: error }" :type="showPwd ? 'text' : 'password'" autocomplete="current-password" placeholder="请输入密码" />
            <button type="button" class="btn ghost icon eye" :aria-label="showPwd ? '隐藏密码' : '显示密码'" :aria-pressed="showPwd" @click="showPwd = !showPwd">
              <component :is="showPwd ? PhEyeSlash : PhEye" :size="20" aria-hidden="true" />
            </button>
          </div>
        </div>

        <p v-if="error" class="error-text" role="alert"><PhWarningCircle :size="18" weight="fill" aria-hidden="true" />{{ error }}</p>

        <button class="btn primary block" type="submit" :disabled="loading">
          <PhSignIn :size="20" aria-hidden="true" />{{ loading ? "登录中…" : "登 录" }}
        </button>

        <hr class="divider" />
        <div class="demo">
          <span class="label muted"><PhLockKey :size="16" aria-hidden="true" /> 演示账号（本地环境，密码 Lantai@2026）</span>
          <div class="row">
            <button v-for="d in demos" :key="d.phone" type="button" class="btn small" @click="fillDemo(d)">
              {{ d.name }} <span class="muted">· {{ d.note }}</span>
            </button>
          </div>
        </div>
      </form>
      <p class="sim muted">澜台为模拟银行平台，不涉及真实资金</p>
    </section>
  </main>
</template>

<style scoped>
.login { min-height: 100vh; display: grid; grid-template-columns: 1.1fr 1fr; }
.hero { position: relative; overflow: hidden; display: flex; align-items: center; padding: var(--space-7) var(--space-6); border-right: 1px solid var(--c-border); }
.hero-inner { position: relative; z-index: 1; max-width: 460px; display: flex; flex-direction: column; gap: var(--space-4); }
.hero h1 { font-size: 3.2rem; letter-spacing: 0.5em; margin-right: -0.5em; color: var(--c-accent); }
.slogan { font-family: var(--font-serif); font-size: 1.25rem; line-height: 1.9; letter-spacing: 0.12em; }
.points { display: flex; flex-direction: column; gap: 10px; color: var(--c-text-muted); margin-top: var(--space-3); }
.points li { display: flex; align-items: center; gap: 12px; }
.dia { flex: none; width: 7px; height: 7px; background: var(--c-primary); transform: rotate(45deg); }
.form-side { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-4); padding: var(--space-6) 16px; }
.form { width: 100%; max-width: 400px; }
.form h2 { margin: 6px 0 var(--space-5); font-size: 1.6rem; }
.pwd { position: relative; }
.pwd .input { padding-right: 52px; }
.eye { position: absolute; right: 2px; top: 0; }
.demo { display: flex; flex-direction: column; gap: 10px; }
.demo .label { display: flex; align-items: center; gap: 6px; font-size: 0.82rem; }
.error-text { margin-bottom: var(--space-4); }
.sim { font-size: 0.78rem; letter-spacing: 0.1em; }
@media (max-width: 900px) {
  .login { grid-template-columns: 1fr; }
  .hero { padding: var(--space-6) 16px; border-right: 0; border-bottom: 1px solid var(--c-border); min-height: 260px; }
  .hero h1 { font-size: 2.2rem; }
  .points { display: none; }
}
</style>
