<script setup>
import { PhInfo } from "@phosphor-icons/vue";

defineProps({ reasons: { type: Array, default: () => [] } });
</script>

<template>
  <ul v-if="reasons.length" class="reasons" aria-label="风控提示">
    <li v-for="r in reasons" :key="r.code">
      <span class="tag" :class="r.severity">
        <PhInfo :size="13" weight="bold" aria-hidden="true" />{{ r.severity === "blocked" ? "拦截" : r.severity === "low" ? "提示" : "验证" }}
      </span>
      <div>
        <div>{{ r.message }}</div>
        <code class="muted">{{ r.code }}</code>
      </div>
    </li>
  </ul>
  <p v-else class="muted">未命中任何风控规则。</p>
</template>

<style scoped>
.reasons { display: flex; flex-direction: column; gap: 10px; }
.reasons li { display: flex; gap: 12px; align-items: flex-start; padding: 10px 12px; border: 1px solid var(--c-border); border-radius: var(--radius-sm); background: var(--c-surface-2); }
.reasons .tag { flex: none; margin-top: 2px; }
</style>
