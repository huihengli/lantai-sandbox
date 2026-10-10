<script setup>
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { PhCreditCard, PhSnowflake, PhWarningOctagon, PhLockKeyOpen, PhPlus, PhArrowClockwise, PhWarningCircle } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { errorText, fmtMoney } from "../utils";

const router = useRouter();
const cards = ref([]);
const accounts = ref([]);
const limitForm = reactive({}); // key: card_xxx / account_xxx → { single, daily }
const busy = ref("");
const error = ref("");

const CONTROLS = [["online", "线上支付"], ["overseas", "境外交易"], ["atm", "ATM 取现"]];
const STATUS_CLS = { active: "ok", frozen: "medium", locked: "high", lost: "blocked" };

async function load() {
  cards.value = await api.cards();
  accounts.value = await Promise.all((await api.accounts()).map((a) => api.balance(a.id)));
  for (const c of cards.value) limitForm[c.id] = { single: c.limits.single, daily: c.limits.daily };
  for (const a of accounts.value) limitForm[a.id] = { single: a.single_limit, daily: a.daily_limit };
}
onMounted(load);

const goConfirm = (op) => router.push(`/confirm/${op.operation_id}`);

async function run(key, fn, okMsg) {
  busy.value = key;
  error.value = "";
  try {
    const r = await fn();
    if (r?.operation_id) {
      toast("已生成待确认操作，请在确认中心核对");
      return goConfirm(r);
    }
    if (okMsg) toast(okMsg);
    await load();
  } catch (e) {
    error.value = errorText(e);
    toast(errorText(e), "bad");
  } finally {
    busy.value = "";
  }
}

const freeze = (c) => run(c.id, () => api.freezeCard(c.id), "卡片已冻结");
const unfreeze = (c) => run(c.id, () => api.prepareUnfreeze(c.id));
const reissue = (c) => run(c.id, () => api.prepareReissue(c.id));
const apply = (a) => run(a.id, () => api.prepareCardApply(a.id));

function reportLoss(c) {
  if (!window.confirm(`挂失卡片 ${c.card_no_masked}？挂失后不可撤销，需补发新卡。`)) return;
  run(c.id, () => api.reportLoss(c.id), "已挂失");
}

// 关闭开关立即生效；打开开关需要确认流程
function toggle(c, key, value) {
  run(c.id + key, () => (value ? api.prepareControls(c.id, { [key]: true }) : api.setControls(c.id, { [key]: false })), "已更新开关");
}

// 调低立即生效；调高走确认流程
function saveLimits(kind, id, current) {
  const f = limitForm[id];
  const raise = Number(f.single) > Number(current.single) || Number(f.daily) > Number(current.daily);
  const body = { single_limit: f.single, daily_limit: f.daily };
  const direct = kind === "card" ? api.setCardLimits : api.setAccountLimits;
  const prepare = kind === "card" ? api.prepareCardLimits : api.prepareAccountLimits;
  run(id + "lim", () => (raise ? prepare(id, body) : direct(id, body)), "额度已更新");
}
</script>

<template>
  <PageHeader eyebrow="卡片与额度" title="卡片管理" desc="收紧立即生效；放宽（解冻、补发、提额、开境外）需您确认并验证。" />
  <p v-if="error" class="notice bad" role="alert" style="margin-bottom: var(--space-4)"><PhWarningCircle :size="20" weight="fill" aria-hidden="true" />{{ error }}</p>

  <div class="stack">
    <section v-for="c in cards" :key="c.id" class="panel card-panel" :class="{ dim: c.status === 'lost' }">
      <div class="plastic" :class="c.status" aria-hidden="true">
        <span class="brand">澜台 · 借记卡</span>
        <PhCreditCard :size="30" />
        <span class="no mono">**** **** **** {{ c.card_no_masked.slice(-4) }}</span>
        <span class="st">{{ c.status_text }}</span>
      </div>

      <div class="body">
        <div class="row between">
          <h3>{{ c.card_no_masked }} <span class="tag" :class="STATUS_CLS[c.status]">{{ c.status_text }}</span></h3>
          <span class="muted mono">{{ c.id }}</span>
        </div>

        <fieldset class="controls" :disabled="c.status === 'lost'">
          <legend class="label muted">交易开关</legend>
          <label v-for="[k, name] in CONTROLS" :key="k" class="switch">
            <input type="checkbox" :checked="c.controls[k]" :disabled="!!busy" @change="toggle(c, k, $event.target.checked)" />
            <span>{{ name }}</span>
            <small class="muted">{{ c.controls[k] ? "已开启" : "已关闭" }}</small>
          </label>
        </fieldset>

        <div class="limits">
          <div class="field"><label :for="`s-${c.id}`">单笔额度（元）</label><input :id="`s-${c.id}`" v-model="limitForm[c.id].single" class="input num" inputmode="decimal" :disabled="c.status === 'lost'" /></div>
          <div class="field"><label :for="`d-${c.id}`">单日额度（元）</label><input :id="`d-${c.id}`" v-model="limitForm[c.id].daily" class="input num" inputmode="decimal" :disabled="c.status === 'lost'" /></div>
          <button class="btn small" type="button" :disabled="!!busy || c.status === 'lost'" @click="saveLimits('card', c.id, c.limits)">保存额度</button>
        </div>

        <div class="row actions">
          <button v-if="c.status === 'active'" class="btn small" type="button" :disabled="!!busy" @click="freeze(c)"><PhSnowflake :size="18" aria-hidden="true" />冻结</button>
          <button v-if="c.status === 'frozen' || c.status === 'locked'" class="btn small" type="button" :disabled="!!busy" @click="unfreeze(c)"><PhLockKeyOpen :size="18" aria-hidden="true" />{{ c.status === "locked" ? "解锁" : "解冻" }}</button>
          <button v-if="c.status !== 'lost'" class="btn small danger" type="button" :disabled="!!busy" @click="reportLoss(c)"><PhWarningOctagon :size="18" aria-hidden="true" />挂失</button>
          <button v-if="c.status === 'lost' && !c.replaced_by" class="btn small" type="button" :disabled="!!busy" @click="reissue(c)"><PhArrowClockwise :size="18" aria-hidden="true" />补发新卡</button>
          <span v-if="c.replaced_by" class="muted">已补发：{{ c.replaced_by }}</span>
        </div>
      </div>
    </section>
    <p v-if="!cards.length" class="empty panel">暂无卡片</p>

    <section class="panel">
      <div class="panel-title"><h3>账户转账额度与开卡</h3></div>
      <p class="muted" style="margin-bottom: var(--space-4)">账户额度限制转账；调低立即生效，调高需确认。</p>
      <div class="grid-2">
        <div v-for="a in accounts" :key="a.id" class="acct">
          <strong>{{ a.type_label }} {{ a.account_no_masked }}</strong>
          <div class="limits">
            <div class="field"><label :for="`as-${a.id}`">单笔（元）</label><input :id="`as-${a.id}`" v-model="limitForm[a.id].single" class="input num" inputmode="decimal" /></div>
            <div class="field"><label :for="`ad-${a.id}`">单日（元）</label><input :id="`ad-${a.id}`" v-model="limitForm[a.id].daily" class="input num" inputmode="decimal" /></div>
          </div>
          <div class="row">
            <button class="btn small" type="button" :disabled="!!busy" @click="saveLimits('account', a.id, { single: a.single_limit, daily: a.daily_limit })">保存额度</button>
            <button class="btn small" type="button" :disabled="!!busy" @click="apply(a)"><PhPlus :size="18" aria-hidden="true" />申请新卡</button>
            <span class="hint num">当前 {{ fmtMoney(a.single_limit) }} / {{ fmtMoney(a.daily_limit) }}</span>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.card-panel { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: var(--space-5); }
.card-panel.dim { opacity: 0.7; }
.plastic {
  position: relative; aspect-ratio: 1.586; border-radius: 12px; padding: 16px; color: #ece8dc; display: flex; flex-direction: column; justify-content: space-between;
  background: linear-gradient(135deg, #17252a, #0d1518 60%), radial-gradient(circle at 80% 0, rgba(214, 179, 106, 0.4), transparent 50%);
  border: 1px solid var(--c-border-strong); box-shadow: inset 0 0 0 4px rgba(214, 179, 106, 0.08);
}
.plastic::after { content: ""; position: absolute; right: -30px; top: -30px; width: 130px; height: 130px; border: 1px solid rgba(214, 179, 106, 0.35); border-radius: 50%; }
.plastic.frozen { filter: saturate(0.5) hue-rotate(160deg); }
.plastic.lost, .plastic.locked { filter: grayscale(0.8); }
.plastic .brand { font-family: var(--font-serif); letter-spacing: 0.2em; color: var(--gold-300); font-size: 0.82rem; }
.plastic svg { color: var(--gold-400); }
.plastic .no { letter-spacing: 0.12em; font-size: 1rem; }
.plastic .st { position: absolute; right: 14px; bottom: 14px; font-size: 0.74rem; letter-spacing: 0.2em; color: var(--gold-300); }
.body { display: flex; flex-direction: column; gap: var(--space-4); min-width: 0; }
.controls { display: flex; gap: var(--space-5); flex-wrap: wrap; border: 0; padding: 0; margin: 0; }
.controls legend { padding: 0; margin-bottom: 6px; }
.switch { display: flex; align-items: center; gap: 8px; min-height: 44px; cursor: pointer; }
.switch input { width: 20px; height: 20px; accent-color: var(--c-primary); }
.limits { display: flex; gap: var(--space-4); align-items: flex-end; flex-wrap: wrap; }
.limits .field { margin-bottom: 0; min-width: 130px; flex: 1; }
.acct { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--c-border); border-radius: var(--radius-sm); }
@media (max-width: 760px) { .card-panel { grid-template-columns: minmax(0, 1fr); } .plastic { max-width: 320px; } }
</style>
