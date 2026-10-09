<script setup>
import { PhCheckCircle, PhWarningCircle } from "@phosphor-icons/vue";
import { session } from "../stores/session";
</script>

<template>
  <div class="toasts" aria-live="polite" role="status">
    <div v-for="t in session.toasts" :key="t.id" class="toast" :class="t.kind">
      <component :is="t.kind === 'ok' ? PhCheckCircle : PhWarningCircle" :size="20" weight="fill" aria-hidden="true" />
      <span>{{ t.message }}</span>
    </div>
  </div>
</template>

<style scoped>
.toasts { position: fixed; right: 16px; bottom: 16px; z-index: 60; display: flex; flex-direction: column; gap: 8px; max-width: calc(100vw - 32px); }
.toast { display: flex; gap: 10px; align-items: flex-start; padding: 12px 16px; min-width: 240px; background: var(--c-surface-3); border: 1px solid var(--c-border-strong); border-left: 3px solid var(--c-success); border-radius: var(--radius-sm); box-shadow: var(--c-shadow); animation: rise 0.3s var(--ease) both; }
.toast.bad { border-left-color: var(--risk-blocked); }
.toast.warn { border-left-color: var(--c-warn); }
</style>
