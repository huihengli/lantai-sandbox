<script setup>
import { computed } from "vue";
import { OP_STATUS } from "../utils";

const props = defineProps({ status: { type: String, required: true } });
const meta = computed(() => OP_STATUS[props.status] || { text: props.status, cls: "muted" });
</script>

<template>
  <span class="tag" :class="meta.cls">{{ meta.text }}</span>
</template>
