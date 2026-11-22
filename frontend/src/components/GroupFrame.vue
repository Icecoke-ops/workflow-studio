<script setup>
import { computed, nextTick, ref } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import { frameItems, unionBox } from '../groups.js'

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
      :class="{ selected }"
      :style="{
        left: box.x + 'px',
        top: box.y + 'px',
        width: box.width + 'px',
        height: box.height + 'px',
      }"
    >
      <div class="gframe-bar nodrag nopan" @pointerdown.stop>
        <input
          v-if="editing"
          ref="titleInput"
          v-model="draft"
          class="gframe-title gframe-title-input nodrag nopan"
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
        <span v-else class="gframe-title" :title="data.title" @click.stop="beginRename">
          {{ data.title }}
        </span>
        <span class="gframe-count">{{ data.count }} 项</span>
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

/* 右键菜单会把展开框设成选中：框体 pointer-events:none 收不到点击，选中态只能靠这圈高亮 */
.gframe.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.22);
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
  cursor: text;
}

.gframe-count {
  flex: none;
  color: var(--muted);
  font-size: 11px;
}

.gframe-title-input {
  width: 160px;
  box-sizing: border-box;
  padding: 0 4px;
  border: 1px solid #9b7ede;
  border-radius: 4px;
  background: #fff;
  color: #5e35b1;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  line-height: 16px;
  outline: none;
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
