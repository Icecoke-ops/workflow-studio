<script setup>
import { computed, nextTick, ref } from 'vue'
import { Handle, Position, useVueFlow } from '@vue-flow/core'
import { memberLeaves } from '../groups.js'
import ConfigForm from './ConfigForm.vue'

const props = defineProps({
  id: { type: String, default: '' },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const { findNode } = useVueFlow()

// 标题就地改名：编辑态自持，提交才交给 App（data.onRename），取消直接丢弃草稿。
const editing = ref(false)
const draft = ref('')
const composing = ref(false)
const titleInput = ref(null)

async function beginRename() {
  draft.value = props.data.title || ''
  editing.value = true
  await nextTick()
  titleInput.value?.focus()
  titleInput.value?.select()
}

function onCompositionStart() {
  composing.value = true
}

function onCompositionEnd() {
  composing.value = false
  // 浏览器可能先 blur 后 compositionend：组字结束后若输入框已失焦，补一次提交
  if (editing.value && titleInput.value !== document.activeElement) commitTitle()
}

function commitTitle() {
  if (composing.value || !editing.value) return
  editing.value = false
  const title = draft.value.trim()
  if (!title || title === props.data.title) return
  props.data.onRename?.(props.data.groupId, title)
}

function cancelTitle() {
  if (composing.value) return
  editing.value = false
}

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

const portSides = computed(() =>
  ['inPorts', 'outPorts'].flatMap((listKey, side) =>
    (props.data[listKey] || []).map((port, index) => ({
      key: `${listKey}-${port.name}`,
      port,
      index,
      count: props.data[listKey].length,
      side: side ? 'right' : 'left',
      type: side ? 'source' : 'target',
      position: side ? Position.Right : Position.Left,
    })),
  ),
)

function portStyle(index, count, side) {
  const top = `${((index + 1) / (count + 1)) * 100}%`
  return side === 'left' ? { top, left: '-15px' } : { top, right: '-15px', left: 'auto' }
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
      <template v-for="item in portSides" :key="item.key">
        <div
          class="gnode-port"
          :class="item.side"
          :style="portStyle(item.index, item.count, item.side)"
        >
          <Handle
            :id="item.port.name"
            :type="item.type"
            :position="item.position"
            class="gnode-handle"
            :style="{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              background: item.port.color,
            }"
          />
          <span class="gnode-port-tip">
            <span class="gnode-port-tip-label">{{ item.port.label }}</span>
            <span v-if="item.port.title" class="gnode-port-tip-type">{{ item.port.title }}</span>
          </span>
        </div>
      </template>
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
  position: absolute;
  inset: 0;
  pointer-events: none;
}

/* 端口不进正文布局：圆点挂在卡片边缘，hover 时才在卡片外侧显示文字提示 */
.gnode-port {
  position: absolute;
  width: 10px;
  height: 10px;
  transform: translateY(-50%);
  pointer-events: all;
}

.gnode-port.left {
  left: -15px;
}

.gnode-port.right {
  right: -15px;
}

.gnode-handle {
  pointer-events: all;
  width: 10px;
  height: 10px;
  border: 2px solid #fff;
}

.gnode-port-tip {
  display: none;
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  max-width: 190px;
  padding: 3px 7px;
  border-radius: 5px;
  background: rgba(40, 40, 48, 0.94);
  color: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
  pointer-events: none;
  z-index: 2;
}

.gnode-port.left .gnode-port-tip {
  right: 18px;
  text-align: right;
}

.gnode-port.right .gnode-port-tip {
  left: 18px;
}

.gnode-port:hover .gnode-port-tip {
  display: block;
}

.gnode-port-tip-label {
  display: block;
  max-width: 190px;
  font-size: 11px;
  line-height: 15px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.gnode-port-tip-type {
  display: block;
  color: #d7d7e0;
  font-size: 10px;
  line-height: 14px;
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
