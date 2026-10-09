<script setup>
defineProps({ eyebrow: String, title: { type: String, required: true }, desc: String });
</script>

<template>
  <header class="page-header">
    <div>
      <span v-if="eyebrow" class="eyebrow">{{ eyebrow }}</span>
      <h1>{{ title }}</h1>
      <p v-if="desc" class="muted">{{ desc }}</p>
    </div>
    <div class="actions"><slot /></div>
  </header>
</template>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; margin-bottom: var(--space-5); }
.page-header h1 { margin-top: 6px; }
.actions { display: flex; gap: 10px; flex-wrap: wrap; }
</style>
