<script setup>
import { computed } from 'vue'
import { BaseEdge, EdgeLabelRenderer, getBezierPath } from '@vue-flow/core'

const props = defineProps({
  id: { type: String, required: true },
  sourceX: { type: Number, required: true },
  sourceY: { type: Number, required: true },
  targetX: { type: Number, required: true },
  targetY: { type: Number, required: true },
  sourcePosition: { type: String, required: true },
  targetPosition: { type: String, required: true },
  markerEnd: { type: String, default: '' },
  style: { type: Object, default: () => ({}) },
  selected: { type: Boolean, default: false },
  data: { type: Object, default: () => ({}) },
})

const path = computed(() =>
  getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    targetX: props.targetX,
    targetY: props.targetY,
    sourcePosition: props.sourcePosition,
    targetPosition: props.targetPosition,
  }),
)

const edgeStyle = computed(() => {
  const base = { stroke: '#b4b9c4', strokeWidth: 1.8, ...props.style }
  if (!props.selected) return base
  return {
    ...base,
    stroke: '#f56c6c',
    strokeWidth: 2.8,
    filter: 'drop-shadow(0 0 3px rgba(245, 108, 108, 0.6))',
  }
})
</script>

<template>
  <BaseEdge :path="path[0]" :marker-end="markerEnd" :style="edgeStyle" />
  <EdgeLabelRenderer>
    <button
      class="edge-delete"
      :class="{ active: selected }"
      type="button"
      title="删除连线"
      aria-label="删除连线"
      :style="{ transform: `translate(-50%, -50%) translate(${path[1]}px, ${path[2]}px)` }"
      @click.stop="data.onDelete(id)"
    >
      ×
    </button>
  </EdgeLabelRenderer>
</template>

<style scoped>
.edge-delete {
  position: absolute;
  pointer-events: all;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 1px solid #dcdfe6;
  border-radius: 50%;
  background: #fff;
  color: var(--muted);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  opacity: 0.45;
  transition: opacity 0.12s, color 0.12s, border-color 0.12s, box-shadow 0.12s;
}

.edge-delete:hover,
.edge-delete.active {
  opacity: 1;
  color: var(--danger);
  border-color: var(--danger);
  box-shadow: 0 0 0 2px rgba(245, 108, 108, 0.15);
}
</style>
