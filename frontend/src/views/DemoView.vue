<script setup>
import { onMounted, reactive, ref } from "vue";
import { PhArrowCounterClockwise, PhMoonStars, PhFastForward, PhClockClockwise, PhPlus, PhTrash } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { errorText, fmtTime } from "../utils";

const KEY = "lt_admin_key";
const adminKey = ref("dev-admin-key");
try { adminKey.value = localStorage.getItem(KEY) || adminKey.value; } catch { /* 忽略 */ }

const now = ref("");
const when = ref("");
const blacklist = ref([]);
const bl = reactive({ account_no: "", bank_code: "OTHER" });
const busy = ref(false);

const remember = () => { try { localStorage.setItem(KEY, adminKey.value); } catch { /* 忽略 */ } };

async function run(fn, okMsg) {
  busy.value = true;
  remember();
  try {
    const r = await fn();
    if (okMsg) toast(okMsg);
    return r;
  } catch (e) {
    toast(errorText(e), "bad");
  } finally {
    busy.value = false;
  }
}

async function loadBl() {
  const r = await run(() => api.admin.blacklist(adminKey.value));
  if (r) blacklist.value = r;
}
async function clock(body) {
  const r = await run(() => (body ? api.admin.setClock(adminKey.value, body) : api.admin.resetClock(adminKey.value)), "模拟时钟已更新");
  if (r) now.value = r.now;
}
const night = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return clock({ set_time: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T02:30:00` });
};
async function reset() {
  if (!window.confirm("将清空所有数据并恢复种子数据，已签发的令牌也会失效，需要重新登录。继续？")) return;
  const r = await run(() => api.admin.reset(adminKey.value), "数据已重置，请重新登录");
  if (r) setTimeout(() => { sessionStorage.clear(); window.location.href = "/login"; }, 900);
}
async function add() {
  if (!bl.account_no.trim()) return toast("请输入账号", "warn");
  if (await run(() => api.admin.addBlacklist(adminKey.value, { account_no: bl.account_no.trim(), bank_code: bl.bank_code }), "已加入黑名单")) {
    bl.account_no = "";
    loadBl();
  }
}
async function remove(item) {
  if (await run(() => api.admin.removeBlacklist(adminKey.value, item.id), "已移除")) loadBl();
}

const presets = [
  { key: "blacklist", name: "黑名单收款方", rule: "BLACKLIST_HIT", effect: "拦截" },
  { key: "single", name: "超单笔限额", rule: "SINGLE_LIMIT_EXCEEDED", effect: "拦截" },
  { key: "newpayee", name: "首次转账新收款人", rule: "NEW_PAYEE", effect: "OTP" },
  { key: "mismatch", name: "户名与账号不符", rule: "PAYEE_NAME_MISMATCH", effect: "OTP" },
  { key: "large", name: "大额转账 5 万", rule: "LARGE_AMOUNT", effect: "OTP" },
  { key: "ratio", name: "超余额 80%", rule: "HIGH_BALANCE_RATIO", effect: "OTP" },
  { key: "cross", name: "跨行转账手续费", rule: "CROSS_BANK_FEE", effect: "提示" },
  { key: "autopay", name: "影响自动扣款", rule: "AUTOPAY_AT_RISK", effect: "提示" },
];

onMounted(() => { loadBl(); });
</script>

<template>
  <PageHeader eyebrow="演示控制台" title="演示辅助" desc="仅用于本地演示：重置数据、控制模拟时钟、管理黑名单、一键触发风控规则。" />

  <div class="grid-2" style="align-items: start">
    <section class="panel">
      <div class="panel-title"><h3>管理密钥</h3></div>
      <div class="field"><label for="ak">X-Admin-Key</label><input id="ak" v-model="adminKey" class="input mono" autocomplete="off" @change="remember" /></div>
      <button class="btn danger" type="button" :disabled="busy" @click="reset"><PhArrowCounterClockwise :size="20" aria-hidden="true" />重置演示数据</button>
    </section>

    <section class="panel">
      <div class="panel-title"><h3>模拟时钟</h3></div>
      <p v-if="now" class="muted num" style="margin-bottom: var(--space-3)">当前模拟时间：{{ fmtTime(now, true) }}</p>
      <div class="row">
        <button class="btn small" type="button" :disabled="busy" @click="night"><PhMoonStars :size="18" aria-hidden="true" />调到今日 02:30（夜间规则）</button>
        <button class="btn small" type="button" :disabled="busy" @click="clock({ advance_seconds: 301 })"><PhFastForward :size="18" aria-hidden="true" />快进 5 分钟（操作过期）</button>
        <button class="btn small" type="button" :disabled="busy" @click="clock(null)"><PhClockClockwise :size="18" aria-hidden="true" />恢复真实时间</button>
      </div>
      <div class="field" style="margin-top: var(--space-4)">
        <label for="when">指定时间（澜台本地时间）</label>
        <div class="row"><input id="when" v-model="when" class="input" type="datetime-local" style="flex: 1" />
          <button class="btn small" type="button" :disabled="!when || busy" @click="clock({ set_time: when + ':00' })">设置</button></div>
      </div>
    </section>
  </div>

  <section class="panel" style="margin-top: var(--space-5)">
    <div class="panel-title"><h3>一键触发风控规则</h3><span class="hint">将跳转到转账页并预填表单（以测试1账号演示）</span></div>
    <div class="presets">
      <RouterLink v-for="p in presets" :key="p.key" :to="{ name: 'transfer', query: { preset: p.key } }" class="preset">
        <strong>{{ p.name }}</strong>
        <code class="muted">{{ p.rule }}</code>
        <span class="tag" :class="p.effect === '拦截' ? 'blocked' : p.effect === 'OTP' ? 'medium' : 'low'">{{ p.effect }}</span>
      </RouterLink>
    </div>
  </section>

  <section class="panel" style="margin-top: var(--space-5)">
    <div class="panel-title"><h3>涉诈黑名单</h3></div>
    <form class="row" style="align-items: flex-end" @submit.prevent="add">
      <div class="field" style="flex: 1; min-width: 220px; margin: 0"><label for="bl-no">账号</label><input id="bl-no" v-model="bl.account_no" class="input mono" inputmode="numeric" /></div>
      <div class="field" style="margin: 0"><label for="bl-bank">银行</label>
        <select id="bl-bank" v-model="bl.bank_code" class="select"><option value="OTHER">他行</option><option value="LANTAI">澜台</option></select></div>
      <button class="btn" type="submit" :disabled="busy"><PhPlus :size="18" aria-hidden="true" />加入</button>
    </form>
    <div class="table-wrap" style="margin-top: var(--space-4)">
      <table class="table">
        <thead><tr><th>账号</th><th>银行</th><th>原因</th><th>来源</th><th><span class="sr-only">操作</span></th></tr></thead>
        <tbody>
          <tr v-for="b in blacklist" :key="b.id">
            <td class="mono">{{ b.account_no }}</td><td>{{ b.bank_code === "LANTAI" ? "澜台" : "他行" }}</td>
            <td><code>{{ b.reason_code }}</code></td><td class="muted">{{ b.source }}</td>
            <td><button class="btn small ghost" type="button" :aria-label="`移除 ${b.account_no}`" @click="remove(b)"><PhTrash :size="18" aria-hidden="true" /></button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.presets { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
.preset { display: flex; flex-direction: column; gap: 6px; padding: 12px 14px; text-decoration: none; color: var(--c-text); border: 1px solid var(--c-border); border-radius: var(--radius-sm); transition: border-color var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease); align-items: flex-start; }
.preset:hover { border-color: var(--c-accent); transform: translateY(-2px); }
</style>
