<script setup>
import { computed } from 'vue'
import { Handle, Position, useVueFlow } from '@vue-flow/core'
import { memberLeaves } from '../groups.js'
import ConfigForm from './ConfigForm.vue'

const props = defineProps({
  id: { type: String, default: '' },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const { findNode } = useVueFlow()

const leaves = computed(() =>
  memberLeaves(props.data.groups || [], props.data.groupId)
    .map((leaf) => {
      const node = findNode(leaf.nodeId)
      if (!node?.data) return null
      return {
        nodeId: leaf.nodeId,
        node,
        crumb: [props.data.title, ...leaf.trail, node.data.title || leaf.nodeId].join(' / '),
      }
    })
    .filter(Boolean),
)

function portStyle(index, count, side) {
  const top = `${((index + 1) / (count + 1)) * 100}%`
  return side === 'left'
    ? { top, left: '-15px', transform: 'translateY(-50%)' }
    : { top, right: '-15px', left: 'auto', transform: 'translateY(-50%)' }
}
</script>

<template>
  <div class="gnode" :class="{ selected }">
    <div class="gnode-head">
      <div class="gnode-head-text">
        <div class="gnode-title" :title="data.title">{{ data.title }}</div>
        <div class="gnode-badge">子图 · {{ data.count }} 项</div>
      </div>
      <button
        class="gnode-btn nodrag nopan"
        type="button"
        title="展开子图"
        aria-label="展开子图"
        @pointerdown.stop
        @click.stop="data.onToggleCollapse?.(data.groupId, false)"
      >
        ▸
      </button>
      <button
        class="gnode-btn danger nodrag nopan"
        type="button"
        title="解散子图"
        aria-label="解散子图"
        @pointerdown.stop
        @click.stop="data.onDissolve?.(data.groupId)"
      >
        ×
      </button>
    </div>

    <div class="gnode-ports">
      <Handle
        v-for="(port, index) in data.inPorts"
        :id="port.name"
        :key="`in-${port.name}`"
        type="target"
        :position="Position.Left"
        class="gnode-handle"
        :style="{ ...portStyle(index, data.inPorts.length, 'left'), background: port.color }"
      />
      <Handle
        v-for="(port, index) in data.outPorts"
        :id="port.name"
        :key="`out-${port.name}`"
        type="source"
        :position="Position.Right"
        class="gnode-handle"
        :style="{ ...portStyle(index, data.outPorts.length, 'right'), background: port.color }"
      />
    </div>

    <div class="gnode-scroll nodrag nopan nowheel" @pointerdown.stop @wheel.stop>
      <div v-for="row in leaves" :key="row.nodeId" class="gnode-leaf">
        <div class="gnode-crumb" :title="row.crumb">{{ row.crumb }}</div>
        <ConfigForm
          :schema="row.node.data.config_schema"
          :config="row.node.data.config"
        />
      </div>
      <div v-if="!leaves.length" class="gnode-empty">子图里没有组件</div>
    </div>
  </div>
</template>

<style scoped>
.gnode {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 280px;
  max-height: 400px;
  background: #fff;
  border: 1.5px dashed #9b7ede;
  border-radius: 8px;
  font-size: 12px;
  color: #303133;
  box-shadow: 0 2px 6px rgba(120, 90, 190, 0.12);
  transition: border-color 0.15s, box-shadow 0.15s;
}

.gnode.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.22);
}

.gnode-head {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  padding: 6px 6px 5px 10px;
  background: linear-gradient(90deg, #efe8ff, #f7f3ff);
  border-bottom: 1px solid #e4d9fb;
  border-radius: 7px 7px 0 0;
  flex: none;
}

.gnode-head-text {
  flex: 1;
  min-width: 0;
}

.gnode-title {
  font-weight: 600;
  font-size: 13px;
  line-height: 18px;
  margin-top: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.gnode-badge {
  display: inline-block;
  margin-top: 3px;
  padding: 0 6px;
  border-radius: 8px;
  background: #7c4dff;
  color: #fff;
  font-size: 10px;
  line-height: 15px;
}

.gnode-btn {
  flex: none;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #8c8c9e;
  font-size: 14px;
  line-height: 18px;
  cursor: pointer;
}

.gnode-btn:hover {
  background: rgba(124, 77, 255, 0.12);
  color: #5e35b1;
}

.gnode-btn.danger:hover {
  background: rgba(245, 108, 108, 0.12);
  color: var(--danger);
}

.gnode-ports {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.gnode-handle {
  pointer-events: all;
  width: 10px;
  height: 10px;
  border: 2px solid #fff;
}

.gnode-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 4px 8px 8px;
}

.gnode-leaf + .gnode-leaf {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed #ebe6f7;
}

.gnode-crumb {
  color: var(--muted);
  font-size: 10px;
  line-height: 15px;
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.gnode-empty {
  color: var(--muted);
  padding: 8px 2px;
}
</style>
