<script setup>
// 远山 + 淡月 + 云雾，纯 SVG，装饰用（aria-hidden）
</script>

<template>
  <svg class="art" viewBox="0 0 800 360" preserveAspectRatio="xMidYMax slice" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="mist" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="var(--c-tech)" stop-opacity="0" />
        <stop offset="1" stop-color="var(--c-tech)" stop-opacity="0.22" />
      </linearGradient>
      <radialGradient id="moon" cx="0.5" cy="0.5" r="0.5">
        <stop offset="0" stop-color="var(--gold-300)" stop-opacity="0.95" />
        <stop offset="1" stop-color="var(--gold-400)" stop-opacity="0.15" />
      </radialGradient>
    </defs>
    <circle cx="590" cy="92" r="46" fill="url(#moon)" />
    <circle cx="590" cy="92" r="64" fill="none" stroke="var(--c-accent)" stroke-opacity="0.35" stroke-dasharray="2 6" />
    <path d="M0 250 L90 190 L150 225 L240 140 L330 220 L400 170 L500 240 L580 185 L680 235 L800 175 V360 H0Z" fill="var(--c-text)" opacity="0.07" />
    <path d="M0 290 L110 225 L190 270 L300 190 L390 265 L470 215 L580 285 L690 225 L800 270 V360 H0Z" fill="var(--c-text)" opacity="0.11" />
    <path d="M0 325 L80 290 L180 318 L290 276 L400 322 L520 284 L640 320 L740 292 L800 312 V360 H0Z" fill="var(--c-text)" opacity="0.18" />
    <rect x="0" y="200" width="800" height="160" fill="url(#mist)" />
    <g fill="none" stroke="var(--c-accent)" stroke-opacity="0.45" stroke-width="1.2">
      <path d="M40 120 q14 -16 28 0 q14 -16 28 0 q10 -10 20 0" />
      <path d="M690 190 q12 -14 24 0 q12 -14 24 0" />
    </g>
  </svg>
</template>

<style scoped>
.art { position: absolute; inset: auto 0 0 0; width: 100%; height: 100%; pointer-events: none; }
</style>
