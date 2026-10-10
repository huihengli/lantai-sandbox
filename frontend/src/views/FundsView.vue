<script setup>
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import PageHeader from "../components/PageHeader.vue";
import { api } from "../api";
import { toast } from "../stores/session";
import { errorText, fmtMoney, fmtTime } from "../utils";

const router = useRouter();
const mandates = ref([]);
const busy = ref("");

const CYCLE = { monthly: "每月", yearly: "每年", weekly: "每周" };

async function load() {
  mandates.value = await api.mandates();
}
onMounted(load);

async function cancel(m) {
  busy.value = m.id;
  try {
    const op = await api.prepareMandateCancel(m.id);
    toast("已生成待确认操作，请在确认中心核对");
    router.push(`/confirm/${op.operation_id}`);
  } catch (e) {
    toast(errorText(e), "bad");
  } finally {
    busy.value = "";
  }
}
</script>

<template>
  <PageHeader eyebrow="代扣与预留" title="代扣协议" desc="已授权商户从您账户扣款的协议。取消需您确认，取消后商户无法继续扣款。" />

  <section class="panel" aria-label="代扣协议">
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
</template>

<style scoped>
.small { font-size: 0.78rem; }
</style>
