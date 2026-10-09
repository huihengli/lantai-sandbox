<script setup>
import { fmtMoney, SUMMARY_LABEL, isMoneyKey } from "../utils";

defineProps({ summary: { type: Object, required: true } });
const show = (v) => v !== null && v !== undefined && v !== "";
</script>

<template>
  <dl class="kv">
    <template v-for="(v, k) in summary" :key="k">
      <template v-if="show(v)">
        <dt>{{ SUMMARY_LABEL[k] || k }}</dt>
        <dd class="num" :class="{ big: k === 'amount' || k === 'principal' }">
          <template v-if="isMoneyKey(k)">¥ {{ fmtMoney(v) }}</template>
          <template v-else>{{ v }}</template>
        </dd>
      </template>
    </template>
  </dl>
</template>

<style scoped>
.big { font-family: var(--font-serif); font-size: 1.35rem; color: var(--c-accent); }
</style>
