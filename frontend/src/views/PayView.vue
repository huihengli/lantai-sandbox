<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { PhStorefront, PhWarningCircle } from "@phosphor-icons/vue";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { errorText } from "../utils";

const router = useRouter();
const cards = ref([]);
const merchants = ref([]);
const form = reactive({ card_id: "", merchant_id: "", amount: "", order_ref: "", channel: "online" });
const error = ref("");
const busy = ref(false);

const usable = computed(() => cards.value.filter((c) => c.status === "active"));
const genOrder = () => `ORD-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;

onMounted(async () => {
  [cards.value, merchants.value] = await Promise.all([api.cards(), api.merchants()]);
  form.card_id = usable.value[0]?.id || cards.value[0]?.id || "";
  form.merchant_id = merchants.value[0]?.id || "";
  form.order_ref = genOrder();
});

async function submit() {
  error.value = "";
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(form.amount) || Number(form.amount) <= 0) return (error.value = "请输入有效金额，最多两位小数");
  if (!form.order_ref.trim()) return (error.value = "请填写订单号");
  busy.value = true;
  try {
    const op = await api.prepareMerchantPay({ ...form, order_ref: form.order_ref.trim() });
    toast(op.status === "BLOCKED" ? "该笔支付已被风控拦截" : "已生成待确认操作，请核对后确认", op.status === "BLOCKED" ? "bad" : "ok");
    router.push(`/confirm/${op.operation_id}`);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <PageHeader eyebrow="商户支付" title="商户支付" desc="使用借记卡向商户付款。受卡片状态、交易开关、卡片额度与商户风险约束。" />

  <form class="panel form" novalidate @submit.prevent="submit">
    <div class="field"><label for="p-card">支付卡片</label>
      <select id="p-card" v-model="form.card_id" class="select">
        <option v-for="c in cards" :key="c.id" :value="c.id">{{ c.card_no_masked }} · {{ c.status_text }}</option>
      </select></div>
    <div class="field"><label for="p-mch">商户</label>
      <select id="p-mch" v-model="form.merchant_id" class="select">
        <option v-for="m in merchants" :key="m.id" :value="m.id">{{ m.name }}（{{ m.category }}{{ m.overseas ? " · 境外" : "" }}）</option>
      </select></div>
    <div class="field">
      <span id="p-ch" class="label">支付渠道</span>
      <div class="seg" role="group" aria-labelledby="p-ch">
        <button type="button" :aria-pressed="form.channel === 'online'" @click="form.channel = 'online'">线上</button>
        <button type="button" :aria-pressed="form.channel === 'offline'" @click="form.channel = 'offline'">线下</button>
      </div>
    </div>
    <div class="field"><label for="p-amt">金额（元）</label><input id="p-amt" v-model="form.amount" class="input num" inputmode="decimal" placeholder="0.00" /></div>
    <div class="field"><label for="p-ord">订单号</label><input id="p-ord" v-model="form.order_ref" class="input mono" maxlength="60" /><span class="hint">同一商户同一订单号只能支付一次，防止重复扣款。</span></div>
    <p v-if="error" class="notice bad" role="alert"><PhWarningCircle :size="20" weight="fill" aria-hidden="true" />{{ error }}</p>
    <button class="btn primary" type="submit" :disabled="busy"><PhStorefront :size="20" aria-hidden="true" />{{ busy ? "提交中…" : "提交并前往确认" }}</button>
  </form>
</template>

<style scoped>
.form { max-width: 520px; }
</style>
