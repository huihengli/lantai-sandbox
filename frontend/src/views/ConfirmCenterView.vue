<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { PhRobot, PhUser, PhTimer, PhSealCheck, PhProhibit, PhChatText, PhArrowLeft, PhCheckCircle, PhXCircle } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import RiskBadge from "../components/RiskBadge.vue";
import OpStatusTag from "../components/OpStatusTag.vue";
import ReasonList from "../components/ReasonList.vue";
import SummaryList from "../components/SummaryList.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { ACTIVE_STATUS, OP_TYPE, errorText, fmtMoney, fmtTime } from "../utils";

const route = useRoute();
const router = useRouter();
const ops = ref([]);
const detail = ref(null);
const hint = ref(null);
const otp = ref("");
const filter = ref("active");
const busy = ref("");
const error = ref("");
const now = ref(Date.now());
let poll, tick;

const selectedId = computed(() => route.params.id || "");
const shown = computed(() => (filter.value === "active" ? ops.value.filter((o) => ACTIVE_STATUS.includes(o.status)) : ops.value));
const isActive = computed(() => detail.value && ACTIVE_STATUS.includes(detail.value.status));
const canConfirm = computed(() => detail.value && ["PREPARED", "OTP_VERIFIED"].includes(detail.value.status));
const remaining = computed(() => {
  if (!detail.value || !isActive.value) return 0;
  return Math.max(0, Math.floor((new Date(detail.value.expires_at).getTime() - now.value) / 1000));
});
const countdown = computed(() => `${String(Math.floor(remaining.value / 60)).padStart(2, "0")}:${String(remaining.value % 60).padStart(2, "0")}`);

async function loadList() {
  try { ops.value = await api.operations(); } catch (e) { error.value = errorText(e); }
}

async function loadDetail() {
  if (!selectedId.value) { detail.value = null; return; }
  try {
    detail.value = await api.operation(selectedId.value);
    if (detail.value.status === "OTP_PENDING") hint.value = await api.otpHint(selectedId.value);
    else hint.value = null;
  } catch (e) {
    detail.value = null;
    error.value = errorText(e);
  }
}

async function refresh() { await Promise.all([loadList(), loadDetail()]); }

async function act(name, fn, okMsg) {
  busy.value = name;
  error.value = "";
  try {
    await fn();
    if (okMsg) toast(okMsg);
  } catch (e) {
    error.value = errorText(e);
    toast(errorText(e), "bad");
  } finally {
    busy.value = "";
    await refresh();
  }
}

const verify = () => act("otp", async () => { await api.verifyOtp(selectedId.value, otp.value.trim()); otp.value = ""; }, "验证码正确");
const confirm = () => act("confirm", () => api.confirm(selectedId.value), "操作已执行");
const reject = () => act("reject", () => api.reject(selectedId.value), "已拒绝该操作");

watch(selectedId, () => { error.value = ""; otp.value = ""; loadDetail(); });
watch(remaining, (r) => { if (r === 0 && isActive.value) refresh(); });

onMounted(() => {
  refresh();
  poll = setInterval(() => { if (!document.hidden && !busy.value) refresh(); }, 3000);
  tick = setInterval(() => (now.value = Date.now()), 1000);
});
onBeforeUnmount(() => { clearInterval(poll); clearInterval(tick); });
</script>

<template>
  <PageHeader eyebrow="确认中心" title="交易确认" desc="智能助手只能“预处理”，最终是否执行由您在此决定。" />

  <div class="split" :class="{ 'has-detail': selectedId }">
    <!-- 列表 -->
    <section class="panel list-panel" aria-label="操作列表">
      <div class="seg" role="group" aria-label="筛选">
        <button type="button" :aria-pressed="filter === 'active'" @click="filter = 'active'">待处理</button>
        <button type="button" :aria-pressed="filter === 'all'" @click="filter = 'all'">全部</button>
      </div>
      <ul class="ops">
        <li v-for="o in shown" :key="o.operation_id">
          <RouterLink :to="`/confirm/${o.operation_id}`" class="op" :class="{ on: o.operation_id === selectedId }">
            <div class="row between">
              <strong>{{ OP_TYPE[o.type] }}</strong>
              <OpStatusTag :status="o.status" />
            </div>
            <div class="num amt">¥ {{ fmtMoney(o.summary.amount || o.summary.principal) }}</div>
            <div class="row between muted meta">
              <span class="row" style="gap: 4px">
                <component :is="o.initiator === 'agent' ? PhRobot : PhUser" :size="14" aria-hidden="true" />{{ o.initiator === "agent" ? "智能助手" : "您" }}
              </span>
              <span>{{ fmtTime(o.created_at) }}</span>
            </div>
          </RouterLink>
        </li>
      </ul>
      <p v-if="!shown.length" class="empty">{{ filter === "active" ? "没有待处理的操作" : "暂无操作记录" }}</p>
    </section>

    <!-- 详情 -->
    <section class="detail" aria-label="操作详情" aria-live="polite">
      <RouterLink to="/confirm" class="back btn small"><PhArrowLeft :size="16" aria-hidden="true" />返回列表</RouterLink>

      <div v-if="!detail" class="panel empty"><PhSealCheck :size="40" aria-hidden="true" /><p>请选择左侧的一项操作查看详情。</p></div>

      <div v-else class="stack">
        <div class="panel">
          <div class="panel-title">
            <h2>{{ OP_TYPE[detail.type] }}</h2>
            <OpStatusTag :status="detail.status" />
          </div>
          <div class="row meta-row muted">
            <span class="row" style="gap: 6px"><component :is="detail.initiator === 'agent' ? PhRobot : PhUser" :size="18" aria-hidden="true" />{{ detail.initiator === "agent" ? "由智能助手发起" : "由您发起" }}</span>
            <span class="mono">{{ detail.operation_id }}</span>
            <span v-if="isActive" class="row timer" :class="{ urgent: remaining < 60 }" style="gap: 6px"><PhTimer :size="18" aria-hidden="true" /><span class="num">剩余 {{ countdown }}</span></span>
          </div>
          <hr class="divider" />
          <SummaryList :summary="detail.summary" />
        </div>

        <div class="panel">
          <div class="panel-title"><h3>风险评估</h3><RiskBadge :level="detail.risk.level" /></div>
          <ReasonList :reasons="detail.risk.reasons" />
          <p v-if="detail.risk.required_action === 'otp' && detail.status !== 'EXECUTED'" class="hint" style="margin-top: var(--space-3)">该操作需要输入短信验证码后才可确认。</p>
        </div>

        <div v-if="detail.status === 'BLOCKED'" class="notice bad" role="alert">
          <PhProhibit :size="22" weight="fill" aria-hidden="true" />
          <div><strong>该操作已被风控拦截，无法执行。</strong><br />若有疑问，请勿向对方继续转账，并联系澜台客服或拨打反诈热线 96110。</div>
        </div>
        <div v-else-if="detail.status === 'OTP_LOCKED'" class="notice bad" role="alert"><PhProhibit :size="22" weight="fill" aria-hidden="true" /><div>验证码错误次数过多，操作已锁定，请重新发起。</div></div>
        <div v-else-if="detail.status === 'EXPIRED'" class="notice warn"><PhTimer :size="22" aria-hidden="true" /><div>操作已超过 5 分钟有效期，请重新发起。</div></div>
        <div v-else-if="detail.status === 'FAILED'" class="notice bad" role="alert"><PhXCircle :size="22" weight="fill" aria-hidden="true" /><div>执行失败：{{ detail.result?.message || "请稍后重试" }}</div></div>
        <div v-else-if="detail.status === 'CANCELLED'" class="notice"><PhXCircle :size="22" aria-hidden="true" /><div>该操作已取消，未产生任何扣款。</div></div>

        <!-- OTP -->
        <form v-if="detail.status === 'OTP_PENDING' && hint" class="panel" @submit.prevent="verify">
          <div class="panel-title"><h3>短信验证</h3></div>
          <div class="sms"><PhChatText :size="22" aria-hidden="true" /><div><div class="muted small">模拟短信 · 仅展示于用户通道</div><div>{{ hint.sms }}</div></div></div>
          <div class="field" style="margin-top: var(--space-4)">
            <label for="otp">验证码（剩余 {{ hint.attempts_left }} 次机会）</label>
            <input id="otp" v-model="otp" class="input otp mono" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••" />
          </div>
          <button class="btn primary" type="submit" :disabled="otp.length !== 6 || !!busy">{{ busy === "otp" ? "验证中…" : "验证" }}</button>
        </form>

        <p v-if="error" class="notice bad" role="alert">{{ error }}</p>

        <div v-if="isActive" class="row actions">
          <button class="btn primary" type="button" :disabled="!canConfirm || !!busy" @click="confirm">
            <PhCheckCircle :size="20" aria-hidden="true" />{{ busy === "confirm" ? "执行中…" : "确认并执行" }}
          </button>
          <button class="btn danger" type="button" :disabled="!!busy" @click="reject"><PhXCircle :size="20" aria-hidden="true" />拒绝</button>
          <span v-if="!canConfirm" class="hint">请先完成短信验证。</span>
        </div>

        <div v-if="detail.status === 'EXECUTED' && detail.result" class="panel success">
          <div class="panel-title"><PhSealCheck :size="26" weight="fill" aria-hidden="true" /><h3>已完成</h3></div>
          <dl class="kv">
            <template v-if="detail.result.transaction_id"><dt>流水号</dt><dd class="mono">{{ detail.result.transaction_id }}</dd></template>
            <template v-if="detail.result.holding_id"><dt>持有编号</dt><dd class="mono">{{ detail.result.holding_id }}</dd></template>
            <dt>账户余额</dt><dd class="num">¥ {{ fmtMoney(detail.result.balance_after) }}</dd>
            <dt>执行时间</dt><dd class="num">{{ fmtTime(detail.result.executed_at, true) }}</dd>
          </dl>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.split { display: grid; grid-template-columns: 340px minmax(0, 1fr); gap: var(--space-5); align-items: start; }
.list-panel { padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-4); }
.ops { display: flex; flex-direction: column; gap: 8px; }
.op { display: block; padding: 10px 12px; text-decoration: none; color: var(--c-text); border: 1px solid var(--c-border); border-radius: var(--radius-sm); transition: border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease); }
.op:hover { border-color: var(--c-border-strong); }
.op.on { border-color: var(--c-primary); background: color-mix(in srgb, var(--c-primary) 9%, transparent); }
.amt { font-family: var(--font-serif); font-size: 1.3rem; margin: 2px 0; color: var(--c-accent); }
.meta { font-size: 0.8rem; }
.back { display: none; text-decoration: none; margin-bottom: var(--space-4); }
.meta-row { gap: var(--space-5); font-size: 0.86rem; }
.timer.urgent { color: var(--risk-blocked); }
.sms { display: flex; gap: 12px; padding: 12px 14px; background: var(--c-surface-2); border: 1px dashed var(--c-border-strong); border-radius: var(--radius-sm); }
.small { font-size: 0.78rem; }
.otp { font-size: 1.5rem; letter-spacing: 0.6em; text-align: center; max-width: 260px; }
.actions { padding: 4px 0 var(--space-4); }
.success { border-color: var(--c-success); }
.success :deep(h3) { color: var(--c-success); }
@media (max-width: 900px) {
  .split { grid-template-columns: minmax(0, 1fr); }
  .split.has-detail .list-panel { display: none; }
  .split:not(.has-detail) .detail { display: none; }
  .back { display: inline-flex; }
}
</style>
