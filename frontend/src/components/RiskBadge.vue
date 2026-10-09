<script setup>
import { PhShieldCheck, PhWarning, PhWarningOctagon, PhProhibit } from "@phosphor-icons/vue";
import { RISK_LEVEL } from "../utils";

defineProps({ level: { type: String, required: true } });
const ICONS = { low: PhShieldCheck, medium: PhWarning, high: PhWarningOctagon, blocked: PhProhibit };
</script>

<template>
  <span class="tag" :class="level">
    <component :is="ICONS[level] || PhShieldCheck" :size="14" weight="bold" aria-hidden="true" />
    {{ RISK_LEVEL[level] || level }}
  </span>
</template>
