<script setup>
import { computed, onMounted, ref } from "vue";
import { PhArrowRight, PhShieldWarning, PhArrowsLeftRight, PhVault } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import OpStatusTag from "../components/OpStatusTag.vue";
import { api } from "../api";
import { session } from "../stores/session";
import { CATEGORY, OP_TYPE, errorText, fmtMoney, fmtTime, greeting } from "../utils";

const accounts = ref([]);
const recent = ref([]);
const holdings = ref([]);
const ops = ref([]);
const loading = ref(true);
const error = ref("");

const total = computed(() => accounts.value.reduce((s, a) => s + Number(a.balance), 0).toFixed(2));
const pendingOps = computed(() => ops.value.filter((o) => ["PREPARED", "OTP_PENDING", "OTP_VERIFIED"].includes(o.status)));
const usedPct = (a) => {
  const limit = Number(a.daily_limit);
  return limit ? Math.min(100, Math.round((Number(a.today_transferred_out) / limit) * 100)) : 0;
};

onMounted(async () => {
  try {
    const list = await api.accounts();
    accounts.value = await Promise.all(list.map((a) => api.balance(a.id)));
    const [tx, hd, op] = await Promise.all([
      api.transactions(list[0]?.id, { limit: 6 }),
      api.holdings(),
      api.operations(),
    ]);
    recent.value = tx.items;
    holdings.value = hd.filter((h) => h.status === "holding");
    ops.value = op;
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <PageHeader eyebrow="总览" :title="`${greeting()}，${session.user?.name || ''}`" desc="您的资产与待办一览" />

  <p v-if="error" class="notice bad" role="alert">{{ error }}</p>

  <RouterLink v-if="pendingOps.length" to="/confirm" class="notice warn alert-link">
    <span class="pulse-dot" aria-hidden="true"></span>
    <span><strong>{{ pendingOps.length }} 项操作等待您确认</strong>（可能由智能助手发起）。请核对风险提示后再决定。</span>
    <PhArrowRight :size="20" class="right" aria-hidden="true" />
  </RouterLink>

  <div class="stack" style="margin-top: var(--space-5)">
    <section class="panel total scan" aria-label="资产总览">
      <span class="eyebrow">总资产（人民币）</span>
      <p class="big num">¥ {{ loading ? "—" : fmtMoney(total) }}</p>
      <p class="muted">活期 / 储蓄合计，不含定期 {{ holdings.length }} 笔在途</p>
    </section>

    <div class="grid-2">
      <section v-for="a in accounts" :key="a.id" class="panel">
        <div class="panel-title">
          <h3>{{ a.type_label }}</h3>
          <span class="mono muted">{{ a.account_no_masked }}</span>
        </div>
        <p class="bal num">¥ {{ fmtMoney(a.balance) }}</p>
        <div class="limit">
          <div class="row between"><span class="muted">今日已转出</span><span class="num">{{ fmtMoney(a.today_transferred_out) }} / {{ fmtMoney(a.daily_limit) }}</span></div>
          <div class="bar" role="progressbar" :aria-valuenow="usedPct(a)" aria-valuemin="0" aria-valuemax="100" :aria-label="`日限额已使用 ${usedPct(a)}%`">
            <span :style="{ width: usedPct(a) + '%' }"></span>
          </div>
          <p class="hint">单笔限额 {{ fmtMoney(a.single_limit) }} 元</p>
        </div>
        <div class="row" style="margin-top: var(--space-4)">
          <RouterLink class="btn small" to="/transfer"><PhArrowsLeftRight :size="16" aria-hidden="true" />转账</RouterLink>
          <RouterLink class="btn small" to="/transactions"><PhArrowRight :size="16" aria-hidden="true" />流水</RouterLink>
        </div>
      </section>
    </div>

    <div class="grid-2">
      <section class="panel">
        <div class="panel-title"><h3>最近流水</h3><RouterLink to="/transactions" class="muted">全部</RouterLink></div>
        <ul v-if="recent.length" class="list">
          <li v-for="t in recent" :key="t.id">
            <div>
              <strong>{{ t.counterparty || CATEGORY[t.category] }}</strong>
              <div class="muted small">{{ CATEGORY[t.category] }} · {{ fmtTime(t.occurred_at) }}</div>
            </div>
            <span class="num" :class="t.direction === 'in' ? 'amount-in' : 'amount-out'">{{ t.direction === "in" ? "+" : "-" }}{{ fmtMoney(t.amount) }}</span>
          </li>
        </ul>
        <p v-else class="empty">{{ loading ? "加载中…" : "暂无流水" }}</p>
      </section>

      <section class="panel">
        <div class="panel-title"><h3>近期操作</h3><RouterLink to="/confirm" class="muted">确认中心</RouterLink></div>
        <ul v-if="ops.length" class="list">
          <li v-for="o in ops.slice(0, 5)" :key="o.operation_id">
            <div>
              <RouterLink :to="`/confirm/${o.operation_id}`"><strong>{{ OP_TYPE[o.type] }}</strong></RouterLink>
              <div class="muted small">{{ o.initiator === "agent" ? "智能助手发起" : "您发起" }} · {{ fmtTime(o.created_at) }}</div>
            </div>
            <OpStatusTag :status="o.status" />
          </li>
        </ul>
        <p v-else class="empty">{{ loading ? "加载中…" : "暂无操作记录" }}</p>
      </section>
    </div>

    <section v-if="holdings.length" class="panel">
      <div class="panel-title"><h3><PhVault :size="20" aria-hidden="true" /> 在途定期</h3><RouterLink to="/deposits" class="muted">管理</RouterLink></div>
      <ul class="list">
        <li v-for="h in holdings" :key="h.id">
          <div><strong>{{ h.product }}</strong><div class="muted small">{{ h.start_date }} → {{ h.maturity_date }}</div></div>
          <span class="num">¥ {{ fmtMoney(h.principal) }}</span>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.alert-link { text-decoration: none; color: var(--c-text); align-items: center; }
.total .big { font-family: var(--font-serif); font-size: clamp(2rem, 6vw, 3rem); color: var(--c-accent); margin: 6px 0; letter-spacing: 0.04em; }
.bal { font-family: var(--font-serif); font-size: 1.9rem; margin-bottom: var(--space-4); }
.bar { height: 6px; margin: 8px 0 4px; background: var(--c-surface-3); border-radius: 3px; overflow: hidden; }
.bar span { display: block; height: 100%; background: linear-gradient(90deg, var(--c-tech), var(--c-accent)); transition: width 0.6s var(--ease); }
.list li { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px dashed var(--c-border); }
.list li:last-child { border-bottom: 0; }
.small { font-size: 0.8rem; }
.btn { text-decoration: none; }
</style>
