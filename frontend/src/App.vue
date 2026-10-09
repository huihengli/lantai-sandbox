<script setup>
import ToastHost from "./components/ToastHost.vue";
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <RouterView />
  <ToastHost />
</template>
