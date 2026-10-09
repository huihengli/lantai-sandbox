<script setup>
import { onMounted, reactive, ref, watch } from "vue";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { CATEGORY, errorText, fmtMoney, fmtTime } from "../utils";

const accounts = ref([]);
const items = ref([]);
const nextCursor = ref(null);
const loading = ref(false);
const error = ref("");
const f = reactive({ account: "", direction: "", category: "", min_amount: "", from: "", to: "" });
const PAGE = 20;

async function load(reset = true) {
  if (!f.account) return;
  loading.value = true;
  error.value = "";
  try {
    const data = await api.transactions(f.account, {
      limit: PAGE, direction: f.direction, category: f.category, min_amount: f.min_amount || undefined,
      from: f.from, to: f.to, cursor: reset ? 0 : nextCursor.value,
    });
    items.value = reset ? data.items : items.value.concat(data.items);
    nextCursor.value = data.next_cursor;
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  accounts.value = await api.accounts();
  f.account = accounts.value[0]?.id || "";
});
watch(() => [f.account, f.direction, f.category, f.from, f.to], () => load(true));
let t;
watch(() => f.min_amount, () => { clearTimeout(t); t = setTimeout(() => load(true), 400); });
</script>

<template>
  <PageHeader eyebrow="账户流水" title="交易明细" desc="按方向、类别、金额与日期筛选" />

  <section class="panel tight filters" aria-label="筛选">
    <div class="field"><label for="f-acc">账户</label>
      <select id="f-acc" v-model="f.account" class="select">
        <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.type_label }} {{ a.account_no_masked }}</option>
      </select></div>
    <div class="field"><label for="f-dir">方向</label>
      <select id="f-dir" v-model="f.direction" class="select"><option value="">全部</option><option value="in">收入</option><option value="out">支出</option></select></div>
    <div class="field"><label for="f-cat">类别</label>
      <select id="f-cat" v-model="f.category" class="select"><option value="">全部</option><option v-for="(n, k) in CATEGORY" :key="k" :value="k">{{ n }}</option></select></div>
    <div class="field"><label for="f-min">最小金额</label>
      <input id="f-min" v-model="f.min_amount" class="input" inputmode="decimal" placeholder="如 1000.00" /></div>
    <div class="field"><label for="f-from">起始日期</label><input id="f-from" v-model="f.from" class="input" type="date" /></div>
    <div class="field"><label for="f-to">截止日期</label><input id="f-to" v-model="f.to" class="input" type="date" /></div>
  </section>

  <p v-if="error" class="notice bad" role="alert" style="margin-top: var(--space-4)">{{ error }}</p>

  <section class="panel" style="margin-top: var(--space-5)">
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>时间</th><th>类别</th><th>对方 / 附言</th><th style="text-align: right">金额（元）</th><th style="text-align: right">余额（元）</th></tr></thead>
        <tbody>
          <tr v-for="t in items" :key="t.id">
            <td class="num">{{ fmtTime(t.occurred_at) }}</td>
            <td><span class="tag muted">{{ CATEGORY[t.category] || t.category }}</span></td>
            <td>{{ t.counterparty || "—" }}<div v-if="t.memo" class="muted memo">{{ t.memo }}</div></td>
            <td class="num" style="text-align: right" :class="t.direction === 'in' ? 'amount-in' : 'amount-out'">
              {{ t.direction === "in" ? "+" : "-" }}{{ fmtMoney(t.amount) }}<div v-if="Number(t.fee)" class="muted memo">手续费 {{ fmtMoney(t.fee) }}</div>
            </td>
            <td class="num muted" style="text-align: right">{{ fmtMoney(t.balance_after) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!items.length" class="empty">{{ loading ? "加载中…" : "没有符合条件的流水" }}</p>
    <div v-if="nextCursor !== null" class="row" style="justify-content: center; margin-top: var(--space-4)">
      <button class="btn" type="button" :disabled="loading" @click="load(false)">加载更多</button>
    </div>
  </section>
</template>

<style scoped>
.filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0 var(--space-4); }
.filters .field { margin-bottom: var(--space-3); }
.memo { font-size: 0.78rem; }
</style>
