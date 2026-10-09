<script setup>
// 印章式标识：朱砂方章 + 双线回框，「澜台」竖排两行
defineProps({ size: { type: Number, default: 44 } });
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 64 64" role="img" aria-label="澜台">
    <rect x="3" y="3" width="58" height="58" rx="5" fill="var(--zhusha-600)" />
    <rect x="8" y="8" width="48" height="48" rx="2" fill="none" stroke="#f6dcd6" stroke-width="1.6" />
    <text x="32" y="30" text-anchor="middle" font-size="19" font-weight="700" fill="#fff" font-family="var(--font-serif)">澜</text>
    <text x="32" y="51" text-anchor="middle" font-size="19" font-weight="700" fill="#fff" font-family="var(--font-serif)">台</text>
  </svg>
</template>
