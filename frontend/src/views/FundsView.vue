<script setup>
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { PhLockSimple, PhWarningCircle } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { errorText, fmtMoney, fmtTime } from "../utils";

const router = useRouter();
const mandates = ref([]);
const accounts = ref([]);
const holds = ref([]); // 带 account 信息的扁平列表
const busy = ref("");
const form = reactive({ account_id: "", amount: "", purpose: "", until: "" });
const formError = ref("");

const CYCLE = { monthly: "每月", yearly: "每年", weekly: "每周" };
const HOLD_STATUS = { active: ["生效中", "ok"], released: ["已释放", "muted"], expired: ["已到期", "muted"] };

async function load() {
  mandates.value = await api.mandates();
  accounts.value = await Promise.all((await api.accounts()).map((a) => api.balance(a.id)));
  form.account_id ||= accounts.value[0]?.id || "";
  const lists = await Promise.all(accounts.value.map(async (a) => (await api.holds(a.id)).map((h) => ({ ...h, account: a }))));
  holds.value = lists.flat().sort((x, y) => (x.created_at < y.created_at ? 1 : -1));
}
onMounted(load);

async function goPrepare(key, fn) {
  busy.value = key;
  try {
    const op = await fn();
    toast("已生成待确认操作，请在确认中心核对");
    router.push(`/confirm/${op.operation_id}`);
  } catch (e) {
    toast(errorText(e), "bad");
  } finally {
    busy.value = "";
  }
}
const cancel = (m) => goPrepare(m.id, () => api.prepareMandateCancel(m.id));
const release = (h) => goPrepare(h.id, () => api.prepareHoldRelease(h.id));

async function createHold() {
  formError.value = "";
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(form.amount) || Number(form.amount) <= 0) return (formError.value = "请输入有效金额，最多两位小数");
  busy.value = "hold";
  try {
    await api.createHold(form.account_id, { amount: form.amount, purpose: form.purpose || undefined, until: form.until || undefined });
    toast("已预留，该笔资金暂不可转出或支付");
    Object.assign(form, { amount: "", purpose: "", until: "" });
    await load();
  } catch (e) {
    formError.value = errorText(e);
  } finally {
    busy.value = "";
  }
}
</script>

<template>
  <PageHeader eyebrow="代扣与预留" title="代扣与资金预留" desc="预留立即生效；释放预留与取消代扣需您确认。" />

  <div class="stack">
    <section class="panel" aria-label="资金预留">
      <div class="panel-title"><h3>资金预留</h3></div>
      <p class="muted" style="margin-bottom: var(--space-4)">预留的资金仍在账户内，但不可被转出、存入定期、支付或代扣，直至到期或您确认释放。</p>
      <div class="avail">
        <div v-for="a in accounts" :key="a.id" class="avail-item">
          <span class="muted">{{ a.type_label }} {{ a.account_no_masked }}</span>
          <strong class="num">可用 ¥ {{ fmtMoney(a.available) }}</strong>
          <span class="muted num small">余额 {{ fmtMoney(a.balance) }} · 已预留 {{ fmtMoney(a.held) }}</span>
        </div>
      </div>

      <form class="create" novalidate @submit.prevent="createHold">
        <div class="field"><label for="h-acc">账户</label>
          <select id="h-acc" v-model="form.account_id" class="select"><option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.type_label }} {{ a.account_no_masked }}</option></select></div>
        <div class="field"><label for="h-amt">金额（元）</label><input id="h-amt" v-model="form.amount" class="input num" inputmode="decimal" placeholder="0.00" /></div>
        <div class="field"><label for="h-pur">用途</label><input id="h-pur" v-model="form.purpose" class="input" maxlength="60" placeholder="如：爱人生日礼物" /></div>
        <div class="field"><label for="h-until">到期日（选填）</label><input id="h-until" v-model="form.until" class="input" type="date" /></div>
        <button class="btn primary" type="submit" :disabled="!!busy"><PhLockSimple :size="20" aria-hidden="true" />预留</button>
      </form>
      <p v-if="formError" class="error-text" role="alert"><PhWarningCircle :size="16" weight="fill" aria-hidden="true" />{{ formError }}</p>

      <div class="table-wrap" style="margin-top: var(--space-4)">
        <table class="table">
          <thead><tr><th>账户</th><th>用途</th><th style="text-align: right">金额（元）</th><th>到期</th><th>状态</th><th><span class="sr-only">操作</span></th></tr></thead>
          <tbody>
            <tr v-for="h in holds" :key="h.id">
              <td>{{ h.account.type_label }} {{ h.account.account_no_masked }}</td>
              <td>{{ h.purpose }}<div class="muted small">{{ h.created_by === "agent" ? "智能助手创建" : "您创建" }} · {{ fmtTime(h.created_at) }}</div></td>
              <td class="num" style="text-align: right">{{ fmtMoney(h.amount) }}</td>
              <td class="num">{{ h.expires_at ? fmtTime(h.expires_at) : "直到释放" }}</td>
              <td><span class="tag" :class="HOLD_STATUS[h.status]?.[1]">{{ HOLD_STATUS[h.status]?.[0] || h.status }}</span></td>
              <td><button v-if="h.status === 'active'" class="btn small" type="button" :disabled="!!busy" @click="release(h)">释放</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!holds.length" class="empty">暂无预留</p>
    </section>

    <section class="panel" aria-label="代扣协议">
      <div class="panel-title"><h3>代扣协议</h3></div>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>商户</th><th>品类</th><th style="text-align: right">金额（元）</th><th>周期</th><th>下次扣款</th><th>状态</th><th><span class="sr-only">操作</span></th></tr></thead>
          <tbody>
            <tr v-for="m in mandates" :key="m.id">
              <td>{{ m.merchant }}</td>
              <td><span class="tag muted">{{ m.merchant_category || "—" }}</span></td>
              <td class="num" style="text-align: right">{{ fmtMoney(m.amount) }}</td>
              <td>{{ CYCLE[m.cycle] || m.cycle }}</td>
              <td class="num">{{ m.next_debit_date }}</td>
              <td><span class="tag" :class="m.status === 'active' ? 'ok' : 'muted'">{{ m.status === "active" ? "生效中" : "已取消" }}</span>
                <div v-if="m.cancelled_at" class="muted small">{{ fmtTime(m.cancelled_at) }}</div></td>
              <td><button v-if="m.status === 'active'" class="btn small danger" type="button" :disabled="!!busy" @click="cancel(m)">取消代扣</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!mandates.length" class="empty">暂无代扣协议</p>
    </section>
  </div>
</template>

<style scoped>
.small { font-size: 0.78rem; }
.avail { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: var(--space-4); margin-bottom: var(--space-4); }
.avail-item { display: flex; flex-direction: column; gap: 2px; padding: 10px 14px; border: 1px solid var(--c-border); border-radius: var(--radius-sm); }
.avail-item strong { font-family: var(--font-serif); font-size: 1.3rem; color: var(--c-accent); }
.create { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0 var(--space-4); align-items: end; }
.create .btn { margin-bottom: var(--space-4); }
</style>
