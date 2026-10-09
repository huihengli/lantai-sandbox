<script setup>
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { PhVault, PhHandCoins, PhWarningCircle } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { errorText, fmtMoney } from "../utils";

const router = useRouter();
const products = ref([]);
const holdings = ref([]);
const accounts = ref([]);
const form = reactive({ product_id: "", account_id: "", amount: "" });
const error = ref("");
const busy = ref("");

async function load() {
  [products.value, holdings.value, accounts.value] = await Promise.all([api.products(), api.holdings(), api.accounts()]);
  form.account_id ||= accounts.value[0]?.id || "";
}
onMounted(load);

function pick(p) {
  form.product_id = p.id;
  error.value = "";
  document.getElementById("d-amt")?.focus();
}

async function submit() {
  error.value = "";
  if (!form.product_id) return (error.value = "请先选择一款产品");
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(form.amount) || Number(form.amount) <= 0) return (error.value = "请输入有效金额，最多两位小数");
  busy.value = "create";
  try {
    const op = await api.prepareDeposit({ account_id: form.account_id, product_id: form.product_id, amount: form.amount });
    toast("已生成待确认操作");
    router.push(`/confirm/${op.operation_id}`);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = "";
  }
}

async function early(h) {
  busy.value = h.id;
  try {
    const op = await api.prepareEarlyWithdraw(h.id);
    router.push(`/confirm/${op.operation_id}`);
  } catch (e) {
    toast(errorText(e), "bad");
  } finally {
    busy.value = "";
  }
}
</script>

<template>
  <PageHeader eyebrow="定期存款" title="稳盈之选" desc="到期按约定利率计息；提前支取按活期利率，将损失部分利息。" />

  <section aria-label="在售产品" class="grid-3">
    <article v-for="p in products" :key="p.id" class="panel prod" :class="{ chosen: form.product_id === p.id }">
      <span class="eyebrow">{{ p.term_months >= 12 ? `${p.term_months / 12} 年期` : `${p.term_months} 个月` }}</span>
      <h3>{{ p.name }}</h3>
      <p class="rate num">{{ p.annual_rate }}<small>年化</small></p>
      <p class="muted">起存 ¥ {{ fmtMoney(p.min_amount) }} · 提前支取 {{ p.early_withdraw_rate }}</p>
      <button class="btn small" type="button" :aria-pressed="form.product_id === p.id" @click="pick(p)">
        <PhHandCoins :size="18" aria-hidden="true" />{{ form.product_id === p.id ? "已选择" : "选择" }}
      </button>
    </article>
  </section>

  <form class="panel order" novalidate @submit.prevent="submit">
    <div class="panel-title"><h3>存入定期</h3></div>
    <div class="order-grid">
      <div class="field"><label for="d-acc">资金来源账户</label>
        <select id="d-acc" v-model="form.account_id" class="select">
          <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.type_label }} {{ a.account_no_masked }} · ¥{{ fmtMoney(a.balance) }}</option>
        </select></div>
      <div class="field"><label for="d-prd">产品</label>
        <select id="d-prd" v-model="form.product_id" class="select">
          <option value="" disabled>请选择产品</option>
          <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}（{{ p.annual_rate }}）</option>
        </select></div>
      <div class="field"><label for="d-amt">存入金额（元）</label><input id="d-amt" v-model="form.amount" class="input num" inputmode="decimal" placeholder="0.00" /></div>
    </div>
    <p v-if="error" class="error-text" role="alert"><PhWarningCircle :size="16" weight="fill" aria-hidden="true" />{{ error }}</p>
    <button class="btn primary" type="submit" :disabled="!!busy"><PhVault :size="20" aria-hidden="true" />{{ busy === "create" ? "提交中…" : "提交并前往确认" }}</button>
  </form>

  <section class="panel" style="margin-top: var(--space-5)" aria-label="我的持有">
    <div class="panel-title"><h3>我的定期</h3></div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>产品</th><th style="text-align: right">本金</th><th>起止</th><th style="text-align: right">到期利息</th><th>状态</th><th><span class="sr-only">操作</span></th></tr></thead>
        <tbody>
          <tr v-for="h in holdings" :key="h.id">
            <td>{{ h.product }}</td>
            <td class="num" style="text-align: right">{{ fmtMoney(h.principal) }}</td>
            <td class="num muted">{{ h.start_date }}<br />→ {{ h.maturity_date }}</td>
            <td class="num" style="text-align: right">{{ fmtMoney(h.expected_interest_at_maturity) }}
              <div v-if="h.early_withdraw_loss" class="muted small">提前支取损失 {{ fmtMoney(h.early_withdraw_loss) }}</div></td>
            <td><span class="tag" :class="h.status === 'holding' ? 'ok' : 'muted'">{{ h.status === "holding" ? "持有中" : h.status === "withdrawn_early" ? "已提前支取" : "已到期" }}</span></td>
            <td><button v-if="h.status === 'holding'" class="btn small danger" type="button" :disabled="!!busy" @click="early(h)">提前支取</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!holdings.length" class="empty">暂无定期持有</p>
  </section>
</template>

<style scoped>
.prod { display: flex; flex-direction: column; gap: 8px; transition: border-color var(--dur-base) var(--ease), transform var(--dur-base) var(--ease); }
.prod:hover { transform: translateY(-2px); }
.prod.chosen { border-color: var(--c-primary); }
.prod.chosen::before, .prod.chosen::after { border-color: var(--c-primary); }
.rate { font-family: var(--font-serif); font-size: 2.4rem; color: var(--c-accent); line-height: 1.1; }
.rate small { font-family: var(--font-sans); font-size: 0.8rem; margin-left: 6px; color: var(--c-text-muted); letter-spacing: 0.2em; }
.prod .btn { align-self: flex-start; margin-top: auto; text-decoration: none; }
.order { margin-top: var(--space-5); }
.order-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0 var(--space-5); }
.small { font-size: 0.78rem; }
</style>
