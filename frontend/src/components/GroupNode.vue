<script setup>
import { computed, ref } from 'vue'
import { Handle, Position, useVueFlow } from '@vue-flow/core'
import { memberLeaves } from '../groups.js'
import { useInlineTitle } from '../useInlineTitle.js'
import ConfigForm from './ConfigForm.vue'

const props = defineProps({
  id: { type: String, default: '' },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const { findNode } = useVueFlow()

const {
  editing, draft, titleInput,
  beginRename, onCompositionStart, onCompositionEnd, commitTitle, cancelTitle,
} = useInlineTitle(() => props.data)

// 折叠卡片里的成员：一行一个组件，标题即组件自己的标题；参数默认收起。
const leaves = computed(() =>
  memberLeaves(props.data.groups || [], props.data.groupId)
    .map((leaf) => {
      const node = findNode(leaf.nodeId)
      if (!node?.data) return null
      return {
        nodeId: leaf.nodeId,
        node,
        title: node.data.title || leaf.nodeId,
        count: Object.keys(node.data.config_schema || {}).length,
      }
    })
    .filter(Boolean),
)

const openIds = ref(new Set())

function toggleMember(nodeId) {
  const next = new Set(openIds.value)
  if (next.has(nodeId)) next.delete(nodeId)
  else next.add(nodeId)
  openIds.value = next
}

// 端口行与组件卡片同一套规则：常驻、卡内左右分列、一行一对
const rowCount = computed(() =>
  Math.max(props.data.inPorts?.length || 0, props.data.outPorts?.length || 0),
)

function portTip(port) {
  return port.title ? `${port.label}\n${port.title}` : port.label
}
</script>

<template>
  <div class="gnode" :class="{ selected }">
    <div class="gnode-head">
      <div class="gnode-head-text">
        <input
          v-if="editing"
          ref="titleInput"
          v-model="draft"
          class="gnode-title gnode-title-input nodrag nopan"
          maxlength="40"
          @pointerdown.stop
          @click.stop
          @keydown.stop
          @keydown.enter="commitTitle"
          @keydown.esc="cancelTitle"
          @compositionstart="onCompositionStart"
          @compositionend="onCompositionEnd"
          @blur="commitTitle"
        />
        <div
          v-else
          class="gnode-title"
          :title="data.title"
          @pointerdown.stop
          @click.stop="beginRename"
        >
          {{ data.title }}
        </div>
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
        title="删除子图"
        aria-label="删除子图"
        @pointerdown.stop
        @click.stop="data.onDeleteSubgraph?.(data.groupId)"
      >
        ×
      </button>
    </div>

    <div class="gnode-ports">
      <div v-for="i in rowCount" :key="i" class="port-row">
        <div class="port-side input">
          <template v-if="data.inPorts[i - 1]">
            <Handle
              :id="data.inPorts[i - 1].name"
              type="target"
              :position="Position.Left"
              class="port-handle gnode-handle"
              :style="{
                background: data.inPorts[i - 1].color,
                left: '-15px',
                top: '50%',
                transform: 'translateY(-50%)',
              }"
            />
            <span class="gnode-port" :title="portTip(data.inPorts[i - 1])">
              {{ data.inPorts[i - 1].label }}
            </span>
          </template>
        </div>

        <div class="port-side output">
          <template v-if="data.outPorts[i - 1]">
            <span class="gnode-port" :title="portTip(data.outPorts[i - 1])">
              {{ data.outPorts[i - 1].label }}
            </span>
            <Handle
              :id="data.outPorts[i - 1].name"
              type="source"
              :position="Position.Right"
              class="port-handle gnode-handle"
              :style="{
                background: data.outPorts[i - 1].color,
                right: '-15px',
                left: 'auto',
                top: '50%',
                transform: 'translateY(-50%)',
              }"
            />
          </template>
        </div>
      </div>
      <div v-if="rowCount === 0" class="gnode-empty">无输入 / 输出端口</div>
    </div>

    <div class="gnode-scroll nowheel" @wheel.stop>
      <div v-for="row in leaves" :key="row.nodeId" class="gnode-member">
        <button
          class="gnode-member-row nodrag nopan"
          type="button"
          :aria-expanded="openIds.has(row.nodeId)"
          @pointerdown.stop
          @click.stop="toggleMember(row.nodeId)"
        >
          <span class="gnode-member-chevron">{{ openIds.has(row.nodeId) ? '▾' : '▸' }}</span>
          <span class="gnode-member-name" :title="row.title">{{ row.title }}</span>
          <span v-if="row.count" class="gnode-member-count">{{ row.count }} 项</span>
        </button>
        <div
          v-if="openIds.has(row.nodeId)"
          class="gnode-member-form nodrag nopan"
          @pointerdown.stop
        >
          <ConfigForm
            :header="false"
            :schema="row.node.data.config_schema"
            :config="row.node.data.config"
            @pointerdown.stop
          />
        </div>
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
  /* 徽标删掉后，标题下方留一条空白专门用来拖卡片 */
  padding: 6px 6px 8px 10px;
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
  cursor: text;
}

.gnode-title-input {
  width: 100%;
  box-sizing: border-box;
  padding: 0 3px;
  border: 1px solid var(--primary);
  border-radius: 3px;
  background: #fff;
  color: #303133;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  line-height: 16px;
  outline: none;
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
  flex: none;
  padding: 2px 10px 0;
}

/* 组件卡片用 max-width: 70px 截断；组端口名是「组件标题.端口名」，更宽，
   所以让名字占满本列（flex:1）再省略，完整名字留在 title 里 */
.gnode-port {
  flex: 1;
  min-width: 0;
  font-size: 11px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.port-side.output .gnode-port {
  text-align: right;
}

.gnode-handle {
  pointer-events: all;
}

.gnode-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 4px 8px 8px;
}

/* 成员行：一行一个组件标题，点击展开参数；参数区不再套卡片和分隔条 */
.gnode-member-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 2px 4px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text);
  font-family: inherit;
  font-size: 12px;
  line-height: 18px;
  text-align: left;
  cursor: pointer;
}

.gnode-member-row:hover {
  background: #f5f2fc;
}

.gnode-member-chevron {
  flex: none;
  width: 10px;
  color: var(--muted);
  font-size: 10px;
  line-height: 14px;
  text-align: center;
}

.gnode-member-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gnode-member-count {
  flex: none;
  color: var(--muted);
  font-size: 10px;
}

.gnode-member-form {
  padding: 0 4px 8px 20px;
}

.gnode-empty {
  color: var(--muted);
  padding: 8px 2px;
}
</style>
