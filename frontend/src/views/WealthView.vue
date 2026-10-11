<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { PhChartLineUp, PhClipboardText, PhWarningCircle } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { errorText, fmtMoney, fmtTime } from "../utils";

const router = useRouter();
const profile = ref(null);
const questionnaire = ref(null);
const answers = reactive({});
const showQ = ref(false);
const products = ref([]);
const holdings = ref([]);
const accounts = ref([]);
const form = reactive({ account_id: "", product_id: "", amount: "" });
const error = ref("");
const busy = ref("");

const RISK_CLS = { 1: "low", 2: "low", 3: "medium", 4: "high", 5: "blocked" };
const SUIT = {
  match: ["适合", "ok"], mismatch: ["需特别确认", "high"], forbidden: ["不适合", "blocked"], unassessed: ["未测评", "muted"],
};
const STATUS_TEXT = { valid: "有效", expired: "已过期", none: "未测评" };
const allAnswered = computed(() => questionnaire.value?.questions.every((q) => answers[q.id]));

async function load() {
  [profile.value, products.value, holdings.value] = await Promise.all([api.riskProfile(), api.wealthProducts(), api.wealthHoldings()]);
  accounts.value = await Promise.all((await api.accounts()).map((a) => api.balance(a.id)));
  form.account_id ||= accounts.value[0]?.id || "";
  form.product_id ||= products.value[0]?.id || "";
}
onMounted(load);

async function openQuestionnaire() {
  questionnaire.value ||= await api.questionnaire();
  showQ.value = true;
}

async function submitAssessment() {
  busy.value = "assess";
  try {
    const r = await api.submitRisk(Object.fromEntries(Object.entries(answers).map(([k, v]) => [k, Number(v)])));
    toast(`测评完成：${r.label}`);
    showQ.value = false;
    await load();
  } catch (e) {
    toast(errorText(e), "bad");
  } finally {
    busy.value = "";
  }
}

async function prepare(key, fn) {
  busy.value = key;
  error.value = "";
  try {
    const op = await fn();
    toast(op.status === "BLOCKED" ? "该笔操作已被风控拦截" : "已生成待确认操作，请核对后确认", op.status === "BLOCKED" ? "bad" : "ok");
    router.push(`/confirm/${op.operation_id}`);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = "";
  }
}

function subscribe() {
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(form.amount) || Number(form.amount) <= 0) return (error.value = "请输入有效金额，最多两位小数");
  prepare("sub", () => api.prepareSubscribe({ ...form }));
}

function redeem(h) {
  const v = window.prompt(`赎回「${h.product}」份额（持有 ${h.shares} 份，留空 = 全部赎回）`, "");
  if (v === null) return;
  prepare(h.id, () => api.prepareRedeem({ holding_id: h.id, shares: v.trim() || undefined }));
}

const pnlCls = (v) => (Number(v) > 0 ? "amount-in" : Number(v) < 0 ? "loss" : "");
</script>

<template>
  <PageHeader eyebrow="理财" title="理财与风险测评" desc="购买前需完成风险测评；产品风险高于您的承受能力时将被提示或拦截。净值型产品不保本。" />
  <p v-if="error" class="notice bad" role="alert" style="margin-bottom: var(--space-4)"><PhWarningCircle :size="20" weight="fill" aria-hidden="true" />{{ error }}</p>

  <div class="stack">
    <section class="panel" aria-label="风险测评">
      <div class="panel-title">
        <h3>我的风险测评</h3>
        <button class="btn small" type="button" @click="openQuestionnaire"><PhClipboardText :size="18" aria-hidden="true" />{{ profile?.status === "none" ? "开始测评" : "重新测评" }}</button>
      </div>
      <div v-if="profile" class="row" style="gap: var(--space-5)">
        <span class="level"><strong>{{ profile.label || "尚未测评" }}</strong><small v-if="profile.level" class="muted"> R{{ profile.level }}</small></span>
        <span class="tag" :class="profile.status === 'valid' ? 'ok' : 'medium'">{{ STATUS_TEXT[profile.status] }}</span>
        <span v-if="profile.assessed_at" class="muted">测评于 {{ fmtTime(profile.assessed_at) }}，有效至 {{ fmtTime(profile.valid_until) }}</span>
      </div>

      <form v-if="showQ && questionnaire" class="questions" @submit.prevent="submitAssessment">
        <fieldset v-for="q in questionnaire.questions" :key="q.id">
          <legend>{{ q.text }}</legend>
          <label v-for="o in q.options" :key="o.value" class="opt"><input v-model="answers[q.id]" type="radio" :name="q.id" :value="o.value" /> {{ o.text }}</label>
        </fieldset>
        <div class="row">
          <button class="btn primary" type="submit" :disabled="!allAnswered || !!busy">提交测评</button>
          <button class="btn" type="button" @click="showQ = false">取消</button>
          <span class="hint">测评结果由银行按您的答案计算，智能助手无法代为提交。</span>
        </div>
      </form>
    </section>

    <section aria-label="理财产品" class="grid-3">
      <article v-for="p in products" :key="p.id" class="panel prod">
        <div class="row between"><span class="eyebrow">{{ p.kind_text }}</span><span class="tag" :class="RISK_CLS[p.risk_level]">{{ p.risk_label }}</span></div>
        <h3>{{ p.name }}</h3>
        <p class="nav num">{{ p.nav }}<small>最新净值</small></p>
        <p class="muted">{{ p.description }}<br />起购 ¥ {{ fmtMoney(p.min_amount) }} · T+{{ p.redeem_days }} 赎回</p>
        <div class="row between" style="margin-top: auto">
          <span class="tag" :class="SUIT[p.suitability][1]">{{ SUIT[p.suitability][0] }}</span>
          <button class="btn small" type="button" @click="form.product_id = p.id">选择</button>
        </div>
      </article>
    </section>

    <form class="panel" novalidate @submit.prevent="subscribe">
      <div class="panel-title"><h3>申购</h3></div>
      <div class="order">
        <div class="field"><label for="w-acc">付款账户</label>
          <select id="w-acc" v-model="form.account_id" class="select"><option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.type_label }} {{ a.account_no_masked }} · 可用 ¥{{ fmtMoney(a.available) }}</option></select></div>
        <div class="field"><label for="w-prd">产品</label>
          <select id="w-prd" v-model="form.product_id" class="select"><option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}（{{ p.risk_label }}）</option></select></div>
        <div class="field"><label for="w-amt">申购金额（元）</label><input id="w-amt" v-model="form.amount" class="input num" inputmode="decimal" placeholder="0.00" /></div>
      </div>
      <button class="btn primary" type="submit" :disabled="!!busy"><PhChartLineUp :size="20" aria-hidden="true" />{{ busy === "sub" ? "提交中…" : "提交并前往确认" }}</button>
    </form>

    <section class="panel" aria-label="我的持仓">
      <div class="panel-title"><h3>我的持仓</h3></div>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>产品</th><th style="text-align: right">份额</th><th style="text-align: right">净值</th><th style="text-align: right">市值（元）</th><th style="text-align: right">成本（元）</th><th style="text-align: right">盈亏</th><th><span class="sr-only">操作</span></th></tr></thead>
          <tbody>
            <tr v-for="h in holdings" :key="h.id" :class="{ closed: h.status === 'closed' }">
              <td>{{ h.product }} <span class="tag muted">{{ h.risk_label }}</span></td>
              <td class="num" style="text-align: right">{{ h.shares }}</td>
              <td class="num" style="text-align: right">{{ h.nav }}</td>
              <td class="num" style="text-align: right">{{ fmtMoney(h.market_value) }}</td>
              <td class="num" style="text-align: right">{{ fmtMoney(h.cost) }}</td>
              <td class="num" style="text-align: right" :class="pnlCls(h.pnl)">{{ Number(h.pnl) > 0 ? "+" : "" }}{{ fmtMoney(h.pnl) }}<div class="small">{{ h.pnl_pct }}</div></td>
              <td><button v-if="h.status === 'active'" class="btn small" type="button" :disabled="!!busy" @click="redeem(h)">赎回</button><span v-else class="muted">已赎回</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!holdings.length" class="empty">暂无理财持仓</p>
    </section>
  </div>
</template>

<style scoped>
.level strong { font-family: var(--font-serif); font-size: 1.5rem; color: var(--c-accent); }
.questions { margin-top: var(--space-5); display: flex; flex-direction: column; gap: var(--space-4); }
.questions fieldset { border: 1px solid var(--c-border); border-radius: var(--radius-sm); padding: var(--space-3) var(--space-4); }
.questions legend { padding: 0 6px; font-weight: 600; }
.opt { display: flex; align-items: center; gap: 8px; min-height: 40px; cursor: pointer; }
.opt input { width: 18px; height: 18px; accent-color: var(--c-primary); }
.prod { display: flex; flex-direction: column; gap: 8px; }
.nav { font-family: var(--font-serif); font-size: 2rem; color: var(--c-accent); line-height: 1.1; }
.nav small { font-family: var(--font-sans); font-size: 0.78rem; margin-left: 8px; color: var(--c-text-muted); }
.order { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0 var(--space-5); }
.loss { color: var(--risk-blocked); }
.small { font-size: 0.78rem; }
.closed { opacity: 0.55; }
</style>
