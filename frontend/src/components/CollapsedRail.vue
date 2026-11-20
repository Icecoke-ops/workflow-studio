<script setup>
import { computed } from 'vue'

const props = defineProps({
  side: { type: String, required: true },
  label: { type: String, default: '' },
})

const emit = defineEmits(['expand'])

const arrow = computed(
  () => ({ left: '▶', right: '◀', bottom: '▲' }[props.side] || '▶'),
)
</script>

<template>
  <button
    class="collapsed-rail"
    :class="`rail-${side}`"
    type="button"
    :title="label ? `展开${label}` : '展开'"
    :aria-label="label ? `展开${label}` : '展开'"
    @click="emit('expand')"
  >
    <span class="rail-arrow">{{ arrow }}</span>
    <span v-if="label" class="rail-label">{{ label }}</span>
  </button>
</template>

<style scoped>
.collapsed-rail {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0;
  border: none;
  background: var(--panel);
  color: var(--muted);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.rail-left {
  width: 28px;
  height: 100%;
  flex-direction: column;
  border-right: 1px solid var(--border);
}

.rail-right {
  width: 28px;
  height: 100%;
  flex-direction: column;
  border-left: 1px solid var(--border);
}

.rail-bottom {
  width: 100%;
  height: 28px;
  border-top: 1px solid var(--border);
}

.collapsed-rail:hover {
  background: #ecf5ff;
  color: var(--primary);
}

.rail-arrow {
  font-size: 12px;
  line-height: 1;
}

.rail-label {
  font-size: 11px;
  letter-spacing: 1px;
  white-space: nowrap;
}

.rail-left .rail-label,
.rail-right .rail-label {
  writing-mode: vertical-rl;
}
</style>
