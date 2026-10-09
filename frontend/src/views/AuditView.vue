<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { PhRobot, PhUser, PhGearSix, PhQuestion } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { ACTOR, errorText, fmtTime } from "../utils";

const rows = ref([]);
const actor = ref("");
const result = ref("");
const error = ref("");
let timer;

const ICON = { agent: PhRobot, user: PhUser, system: PhGearSix, admin: PhGearSix, unknown: PhQuestion };
const RESULT = { ok: ["成功", "ok"], rejected: ["被拒绝", "bad"], blocked: ["被拦截", "blocked"], error: ["错误", "bad"] };
const ACTION = {
  login: "登录", logout: "退出", grant_agent_token: "签发 Agent 令牌", revoke_agent_token: "撤销 Agent 令牌",
  otp_verify: "验证 OTP", confirm: "确认执行", reject: "拒绝操作", cancel: "取消操作", risk_precheck: "风险预检", reset: "重置数据",
};
const actionText = (a) => {
  if (a.startsWith("access_denied")) return `越权访问：${a.replace("access_denied ", "")}`;
  const [base, type] = a.split(":");
  const t = { transfer: "转账", deposit_create: "存入定期", deposit_early_withdraw: "提前支取" }[type];
  return (ACTION[base] || { prepare: "预处理", confirm: "确认执行" }[base] || base) + (t ? ` · ${t}` : "");
};

const filtered = computed(() => rows.value.filter((r) => (!actor.value || r.actor === actor.value) && (!result.value || r.result === result.value)));

async function load() {
  try { rows.value = await api.audit(); } catch (e) { error.value = errorText(e); }
}
onMounted(() => { load(); timer = setInterval(() => !document.hidden && load(), 5000); });
onBeforeUnmount(() => clearInterval(timer));
</script>

<template>
  <PageHeader eyebrow="审计记录" title="操作留痕" desc="记录发起方、风控结果与最终状态——包括被后端拒绝的越权尝试。" />

  <section class="panel tight row" aria-label="筛选">
    <div class="seg" role="group" aria-label="按发起方">
      <button type="button" :aria-pressed="actor === ''" @click="actor = ''">全部</button>
      <button type="button" :aria-pressed="actor === 'agent'" @click="actor = 'agent'">智能助手</button>
      <button type="button" :aria-pressed="actor === 'user'" @click="actor = 'user'">用户</button>
    </div>
    <div class="seg" role="group" aria-label="按结果">
      <button type="button" :aria-pressed="result === ''" @click="result = ''">全部结果</button>
      <button type="button" :aria-pressed="result === 'rejected'" @click="result = 'rejected'">被拒绝</button>
      <button type="button" :aria-pressed="result === 'blocked'" @click="result = 'blocked'">被拦截</button>
    </div>
  </section>

  <p v-if="error" class="notice bad" role="alert" style="margin-top: var(--space-4)">{{ error }}</p>

  <section class="panel" style="margin-top: var(--space-5)">
    <ol v-if="filtered.length" class="timeline">
      <li v-for="r in filtered" :key="r.id" :class="r.result">
        <span class="node" aria-hidden="true"><component :is="ICON[r.actor] || PhQuestion" :size="16" /></span>
        <div class="body">
          <div class="row between">
            <strong>{{ actionText(r.action) }}</strong>
            <span class="num muted time">{{ fmtTime(r.ts, true) }}</span>
          </div>
          <div class="row" style="gap: 8px">
            <span class="tag" :class="r.actor === 'agent' ? 'gold' : 'muted'">{{ ACTOR[r.actor] || r.actor }}</span>
            <span class="tag" :class="RESULT[r.result]?.[1] || 'muted'">{{ RESULT[r.result]?.[0] || r.result }}</span>
            <code v-if="r.error_code" class="err">{{ r.error_code }}</code>
            <code v-if="r.operation_id" class="muted">{{ r.operation_id }}</code>
          </div>
          <p v-if="r.detail?.message" class="muted msg">{{ r.detail.message }}</p>
          <details v-if="r.risk || r.detail" class="more">
            <summary>详情</summary>
            <pre>{{ JSON.stringify({ risk: r.risk, detail: r.detail, request_id: r.request_id }, null, 2) }}</pre>
          </details>
        </div>
      </li>
    </ol>
    <p v-else class="empty">没有符合条件的记录</p>
  </section>
</template>

<style scoped>
.timeline { position: relative; display: flex; flex-direction: column; gap: 18px; padding-left: 8px; }
.timeline::before { content: ""; position: absolute; left: 19px; top: 8px; bottom: 8px; width: 1px; background: linear-gradient(var(--c-border-strong), transparent); }
.timeline li { position: relative; display: flex; gap: 14px; }
.node { flex: none; z-index: 1; width: 24px; height: 24px; display: grid; place-items: center; background: var(--c-surface); border: 1px solid var(--c-border-strong); color: var(--c-text-muted); transform: rotate(45deg); border-radius: 3px; }
.node :deep(svg) { transform: rotate(-45deg); }
.rejected .node, .error .node { border-color: var(--c-danger); color: var(--c-danger); }
.blocked .node { border-color: var(--risk-blocked); color: var(--risk-blocked); background: color-mix(in srgb, var(--risk-blocked) 14%, var(--c-surface)); }
.body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.time { font-size: 0.8rem; }
.msg { font-size: 0.86rem; }
.err { color: var(--c-danger); }
.more summary { cursor: pointer; color: var(--c-tech); font-size: 0.82rem; }
.more pre { margin: 6px 0 0; padding: 10px; background: var(--c-bg); border-radius: var(--radius-sm); overflow-x: auto; font-family: var(--font-mono); font-size: 0.78rem; white-space: pre-wrap; word-break: break-all; }
</style>
