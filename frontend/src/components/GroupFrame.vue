<script setup>
import { computed } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import { frameItems, unionBox } from '../groups.js'

const props = defineProps({
  id: { type: String, default: '' },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const { findNode } = useVueFlow()

// findNode 里的节点是响应式的：成员被拖动时这里自动重算，不写 watcher、不回写位置
const box = computed(() => {
  const boxes = []
  for (const unitId of frameItems(props.data.groups || [], props.data.groupId)) {
    const node = findNode(unitId)
    if (!node) continue
    boxes.push({
      x: node.computedPosition?.x ?? node.position?.x ?? 0,
      y: node.computedPosition?.y ?? node.position?.y ?? 0,
      width: node.dimensions?.width || 280,
      height: node.dimensions?.height || 200,
    })
  }
  return unionBox(boxes)
})
</script>

<template>
  <div class="gframe-root">
    <div
      v-if="box"
      class="gframe"
      :style="{
        left: box.x + 'px',
        top: box.y + 'px',
        width: box.width + 'px',
        height: box.height + 'px',
      }"
    >
      <div class="gframe-bar nodrag nopan" @pointerdown.stop>
        <span class="gframe-title" :title="data.title">{{ data.title }}</span>
        <button
          class="gframe-btn nodrag nopan"
          type="button"
          title="折叠子图"
          aria-label="折叠子图"
          @pointerdown.stop
          @click.stop="data.onToggleCollapse?.(data.groupId, true)"
        >
          ▾ 折叠
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gframe-root {
  position: absolute;
  left: 0;
  top: 0;
  width: 0;
  height: 0;
  overflow: visible;
}

.gframe {
  position: absolute;
  pointer-events: none;
  border: 1.5px dashed #9b7ede;
  border-radius: 10px;
  background: rgba(124, 77, 255, 0.045);
}

.gframe-bar {
  position: absolute;
  left: 0;
  top: -26px;
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  padding: 2px 8px;
  border: 1.5px dashed #9b7ede;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.94);
  pointer-events: auto;
  white-space: nowrap;
}

.gframe-title {
  color: #5e35b1;
  font-size: 12px;
  font-weight: 600;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.gframe-btn {
  flex: none;
  padding: 0 4px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #7c4dff;
  font-size: 11px;
  line-height: 16px;
  cursor: pointer;
}

.gframe-btn:hover {
  background: rgba(124, 77, 255, 0.12);
}
</style>
