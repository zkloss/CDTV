<script setup>
defineProps({ create: Boolean, tone: { type: Number, default: 0 } })
</script>

<template>
  <div class="workflow-cover" :class="['workflow-tone-'+tone, { 'workflow-create': create }]" aria-hidden="true">
    <svg v-if="create" viewBox="0 0 300 168" focusable="false">
      <g transform="rotate(-4 102 84)"><rect class="paper" x="60" y="40" width="70" height="90" rx="9"/><path class="accent-line" d="M75 58h19"/><path class="copy-line" d="M75 77h39M75 88h33M75 99h24"/></g>
      <g transform="rotate(3 184 87)"><rect class="paper" x="147" y="56" width="89" height="63" rx="9"/><rect class="image" x="154" y="63" width="75" height="49" rx="5"/><path class="landscape" d="m154 104 27-24 48 32h-75z"/><circle class="sun" cx="216" cy="76" r="5"/></g>
      <circle class="plus-disc" cx="147" cy="87" r="24"/><path class="plus" d="M147 76v22M136 87h22"/>
    </svg>
    <svg v-else viewBox="0 0 300 168" focusable="false">
      <path class="flow" d="M113 85c35 0 28-38 70-38M113 85c35 0 28 38 70 38"/>
      <g transform="rotate(-2 79 86)"><rect class="paper" x="41" y="40" width="74" height="92" rx="8"/><path class="accent-line" d="M53 56h29"/><path class="copy-line" d="M53 75h47M53 87h39M53 99h29"/></g>
      <rect class="paper frame" x="179" y="21" width="84" height="55" rx="8"/><rect class="image" x="186" y="28" width="70" height="41" rx="4"/><path class="landscape" d="m186 61 24-23 46 31h-70z"/><circle class="sun" cx="244" cy="38" r="5"/>
      <rect class="paper frame secondary" x="179" y="96" width="84" height="55" rx="8"/><rect class="image" x="186" y="103" width="70" height="41" rx="4"/><path class="landscape secondary" d="m186 144 44-34 26 25v9z"/><circle class="sun secondary" cx="199" cy="114" r="5"/>
      <circle class="play-disc" cx="220" cy="86" r="15"/><path class="play" d="m217 80 9 6-9 6z"/>
    </svg>
  </div>
</template>

<style scoped>
.workflow-cover{--cover-accent:#41c9ee;--cover-second:#ef9fca;width:100%;height:100%;background:radial-gradient(ellipse at 65% 50%,var(--theme-accent-soft),transparent 75%),var(--theme-bg-elevated)}
.workflow-tone-1{--cover-accent:#e9bf53;--cover-second:#62bfe5}.workflow-tone-2{--cover-accent:#a497e9;--cover-second:#e9a9b9}
.workflow-cover svg{display:block;width:100%;height:100%;overflow:visible}.paper{fill:var(--theme-bg-card);stroke:color-mix(in srgb,var(--cover-accent) 45%,var(--theme-border-subtle));stroke-width:1}.copy-line{fill:none;stroke:var(--theme-border-subtle);stroke-width:4;stroke-linecap:round}.accent-line{fill:none;stroke:var(--cover-accent);stroke-width:4;stroke-linecap:round}.image{fill:var(--theme-bg-elevated)}.landscape{fill:color-mix(in srgb,var(--cover-accent) 25%,var(--theme-bg-card))}.sun{fill:color-mix(in srgb,var(--cover-accent) 70%,var(--theme-bg-card))}.secondary.paper{stroke:color-mix(in srgb,var(--cover-second) 45%,var(--theme-border-subtle))}.secondary.landscape{fill:color-mix(in srgb,var(--cover-second) 25%,var(--theme-bg-card))}.secondary.sun{fill:var(--cover-second)}.flow{fill:none;stroke:color-mix(in srgb,var(--cover-accent) 55%,var(--theme-text-secondary));stroke-width:1.5}.play-disc,.plus-disc{fill:var(--theme-bg-card);stroke:var(--theme-border-subtle);stroke-width:1.5}.play{fill:var(--theme-text-secondary)}.plus{fill:none;stroke:var(--theme-text-primary);stroke-width:2;stroke-linecap:round}.workflow-create{--cover-accent:var(--theme-accent);background:radial-gradient(ellipse at 50% 50%,var(--theme-accent-soft),transparent 70%),var(--theme-bg-card)}
</style>
