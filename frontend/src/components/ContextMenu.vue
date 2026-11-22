<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  x: { type: Number, required: true },
  y: { type: Number, required: true },
})

const emit = defineEmits(['select', 'close'])

const root = ref(null)
const position = ref({ left: props.x, top: props.y })

// 先按落点摆，挂载后按实际尺寸收进视口，贴边时不会越出屏幕。
onMounted(() => {
  const rect = root.value?.getBoundingClientRect()
  if (rect) {
    const margin = 6
    position.value = {
      left: Math.max(margin, Math.min(props.x, window.innerWidth - rect.width - margin)),
      top: Math.max(margin, Math.min(props.y, window.innerHeight - rect.height - margin)),
    }
  }
  window.addEventListener('pointerdown', onPointerDown, true)
  window.addEventListener('contextmenu', close, true)
  window.addEventListener('wheel', close, { passive: true })
  window.addEventListener('resize', close)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', onPointerDown, true)
  window.removeEventListener('contextmenu', close, true)
  window.removeEventListener('wheel', close)
  window.removeEventListener('resize', close)
  window.removeEventListener('keydown', onKeydown)
})

function onPointerDown(event) {
  if (root.value?.contains(event.target)) return
  emit('close')
}

const close = () => emit('close')

function onKeydown(event) {
  if (event.key === 'Escape') emit('close')
}

function choose(item) {
  if (item.disabled) return
  emit('select', item)
}
</script>

<template>
  <Teleport to="body">
    <div
      ref="root"
      class="ctx-menu"
      :style="{ left: `${position.left}px`, top: `${position.top}px` }"
      @contextmenu.prevent
    >
      <button
        v-for="(item, index) in items"
        :key="index"
        class="ctx-item"
        :class="{ danger: item.danger }"
        type="button"
        :disabled="item.disabled"
        @click="choose(item)"
      >
        {{ item.label }}
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.ctx-menu {
  position: fixed;
  z-index: 3000;
  display: flex;
  flex-direction: column;
  min-width: 132px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.12);
}

.ctx-item {
  padding: 6px 10px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
  line-height: 18px;
  text-align: left;
  cursor: pointer;
}

.ctx-item:hover:not(:disabled) {
  background: #f0f5ff;
  color: var(--primary);
}

.ctx-item.danger:hover:not(:disabled) {
  background: #fef2f2;
  color: var(--danger);
}

.ctx-item:disabled {
  color: var(--muted);
  cursor: default;
}
</style>
