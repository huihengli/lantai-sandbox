<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { PhPaperPlaneTilt, PhScan, PhWarningCircle } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import RiskBadge from "../components/RiskBadge.vue";
import ReasonList from "../components/ReasonList.vue";
import SummaryList from "../components/SummaryList.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { errorText, fmtMoney } from "../utils";

const route = useRoute();
const router = useRouter();
const accounts = ref([]);
const payees = ref([]);
const form = reactive({ account: "", mode: "saved", payee_id: "", account_no: "", name: "", bank: "LANTAI", amount: "", memo: "" });
const errors = reactive({ amount: "", payee: "", server: "" });
const check = ref(null);
const busy = ref("");

// 演示预设：/transfer?preset=xxx 一键填入，便于触发各条风控规则
const PRESETS = {
  blacklist: { mode: "new", account_no: "6222000088886666", name: "刘某某", bank: "OTHER", amount: "1000.00" },
  newpayee: { mode: "new", account_no: "6217000040003456", name: "张三", bank: "LANTAI", amount: "2000.00" },
  mismatch: { mode: "new", account_no: "6217000040003456", name: "张山", bank: "LANTAI", amount: "1000.00" },
  large: { account: "acc_002", mode: "saved", payee_id: "pye_001", amount: "50000.00" },
  ratio: { mode: "saved", payee_id: "pye_001", amount: "42000.00" },
  cross: { mode: "saved", payee_id: "pye_002", amount: "5000.00" },
  single: { account: "acc_002", mode: "saved", payee_id: "pye_001", amount: "60000.00" },
  autopay: { mode: "saved", payee_id: "pye_001", amount: "46000.00" },
};

const selectedAccount = computed(() => accounts.value.find((a) => a.id === form.account));
const amountOk = computed(() => /^\d{1,12}(\.\d{1,2})?$/.test(form.amount) && Number(form.amount) > 0);

function body() {
  const base = { from_account_id: form.account, amount: form.amount, memo: form.memo || undefined };
  if (form.mode === "saved") return { ...base, payee_id: form.payee_id };
  return { ...base, payee_account_no: form.account_no.trim(), payee_name: form.name.trim(), bank_code: form.bank };
}

function validate() {
  errors.amount = errors.payee = errors.server = "";
  if (!amountOk.value) errors.amount = "请输入大于 0 的金额，最多两位小数";
  if (form.mode === "saved" && !form.payee_id) errors.payee = "请选择收款人";
  if (form.mode === "new" && (!form.account_no.trim() || !form.name.trim())) errors.payee = "请填写收款账号与户名";
  return !errors.amount && !errors.payee;
}

async function runCheck() {
  if (!validate()) return;
  busy.value = "check";
  try {
    check.value = await api.precheck(body());
  } catch (e) {
    check.value = null;
    errors.server = errorText(e);
  } finally {
    busy.value = "";
  }
}

async function submit() {
  if (!validate()) return;
  busy.value = "submit";
  try {
    const op = await api.prepareTransfer(body());
    toast(op.status === "BLOCKED" ? "该笔交易已被风控拦截" : "已生成待确认操作，请核对后确认", op.status === "BLOCKED" ? "bad" : "ok");
    router.push(`/confirm/${op.operation_id}`);
  } catch (e) {
    errors.server = errorText(e);
  } finally {
    busy.value = "";
  }
}

watch(() => [form.account, form.mode, form.payee_id, form.account_no, form.name, form.bank, form.amount], () => { check.value = null; });

onMounted(async () => {
  [accounts.value, payees.value] = await Promise.all([api.accounts(), api.payees()]);
  form.account = accounts.value[0]?.id || "";
  const p = PRESETS[route.query.preset];
  if (p) Object.assign(form, p);
});
</script>

<template>
  <PageHeader eyebrow="转账" title="发起转账" desc="提交后将生成待确认操作，由您在确认中心核对风险并确认。" />

  <div class="grid-2 layout">
    <form class="panel" novalidate @submit.prevent="submit">
      <div class="field">
        <label for="t-acc">付款账户</label>
        <select id="t-acc" v-model="form.account" class="select">
          <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.type_label }} {{ a.account_no_masked }}</option>
        </select>
        <span v-if="selectedAccount" class="hint num">可用余额 ¥ {{ fmtMoney(selectedAccount.balance) }}</span>
      </div>

      <div class="field">
        <span class="label" id="t-mode">收款方式</span>
        <div class="seg" role="group" aria-labelledby="t-mode">
          <button type="button" :aria-pressed="form.mode === 'saved'" @click="form.mode = 'saved'">已保存收款人</button>
          <button type="button" :aria-pressed="form.mode === 'new'" @click="form.mode = 'new'">新收款人</button>
        </div>
      </div>

      <div v-if="form.mode === 'saved'" class="field">
        <label for="t-payee">收款人</label>
        <select id="t-payee" v-model="form.payee_id" class="select" :class="{ invalid: errors.payee }">
          <option value="" disabled>请选择</option>
          <option v-for="p in payees" :key="p.id" :value="p.id">{{ p.name }} {{ p.account_no_masked }} · {{ p.bank }}</option>
        </select>
      </div>
      <template v-else>
        <div class="field"><label for="t-no">收款账号</label><input id="t-no" v-model="form.account_no" class="input mono" :class="{ invalid: errors.payee }" inputmode="numeric" placeholder="16 位卡号" /></div>
        <div class="field"><label for="t-name">收款人户名</label><input id="t-name" v-model="form.name" class="input" :class="{ invalid: errors.payee }" placeholder="与账户实名一致" /></div>
        <div class="field">
          <span class="label" id="t-bank">收款银行</span>
          <div class="seg" role="group" aria-labelledby="t-bank">
            <button type="button" :aria-pressed="form.bank === 'LANTAI'" @click="form.bank = 'LANTAI'">澜台（行内，免费）</button>
            <button type="button" :aria-pressed="form.bank === 'OTHER'" @click="form.bank = 'OTHER'">他行（收手续费）</button>
          </div>
        </div>
      </template>
      <p v-if="errors.payee" class="error-text" role="alert"><PhWarningCircle :size="16" weight="fill" aria-hidden="true" />{{ errors.payee }}</p>

      <div class="field">
        <label for="t-amt">转账金额（元）</label>
        <input id="t-amt" v-model="form.amount" class="input amt num" :class="{ invalid: errors.amount }" inputmode="decimal" placeholder="0.00" aria-describedby="t-amt-err" />
        <p v-if="errors.amount" id="t-amt-err" class="error-text" role="alert"><PhWarningCircle :size="16" weight="fill" aria-hidden="true" />{{ errors.amount }}</p>
      </div>
      <div class="field"><label for="t-memo">附言（选填）</label><input id="t-memo" v-model="form.memo" class="input" maxlength="200" placeholder="如：房租、还款" /></div>

      <p v-if="errors.server" class="notice bad" role="alert"><PhWarningCircle :size="20" weight="fill" aria-hidden="true" />{{ errors.server }}</p>

      <div class="row" style="margin-top: var(--space-4)">
        <button type="button" class="btn" :disabled="!!busy" @click="runCheck"><PhScan :size="20" aria-hidden="true" />{{ busy === "check" ? "预检中…" : "风险预检" }}</button>
        <button type="submit" class="btn primary" :disabled="!!busy"><PhPaperPlaneTilt :size="20" aria-hidden="true" />{{ busy === "submit" ? "提交中…" : "提交并前往确认" }}</button>
      </div>
    </form>

    <aside class="stack" aria-live="polite">
      <section class="panel">
        <div class="panel-title"><h3>风险预检结果</h3><RiskBadge v-if="check" :level="check.risk.level" /></div>
        <template v-if="check">
          <SummaryList :summary="check.summary" />
          <hr class="divider" />
          <ReasonList :reasons="check.risk.reasons" />
          <p class="hint" style="margin-top: var(--space-3)">预检仅评估风险，不会创建操作，也不会扣款。</p>
        </template>
        <p v-else class="empty">填写表单后点击「风险预检」，提前了解是否需要验证码或会被拦截。</p>
      </section>
      <section class="panel tight">
        <h3>安全提示</h3>
        <ul class="tips muted">
          <li>澜台与公安机关不会要求您转入“安全账户”。</li>
          <li>陌生人催促、要求保密的转账，请先停止并核实。</li>
          <li>智能助手只能发起预处理，最终确认只能由您完成。</li>
        </ul>
      </section>
    </aside>
  </div>
</template>

<style scoped>
.layout { align-items: start; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); }
@media (max-width: 860px) { .layout { grid-template-columns: minmax(0, 1fr); } }
.amt { font-family: var(--font-serif); font-size: 1.4rem; min-height: 52px; }
.tips { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; padding-left: 1em; list-style: disc; }
</style>
