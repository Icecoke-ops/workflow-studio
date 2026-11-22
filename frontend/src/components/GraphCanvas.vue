<script setup>
import { markRaw, onBeforeUnmount, onMounted, watch } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import WorkflowEdge from './WorkflowEdge.vue'

const props = defineProps({
  nodeTypes: { type: Object, required: true },
  edges: { type: Array, default: () => [] },
})

const nodes = defineModel('nodes', { default: () => [] })

const emit = defineEmits([
  'connect',
  'drop-component',
  'remove-edges',
  'selection-change',
  'copy',
  'paste',
  'context-menu',
])

const {
  addSelectedNodes,
  fitView,
  getNodes,
  screenToFlowCoordinate,
  getSelectedEdges,
  getSelectedNodes,
  removeSelectedElements,
} = useVueFlow()

// 连线使用自定义边：中点带删除按钮，选中时高亮
const edgeTypes = { workflow: markRaw(WorkflowEdge) }

// 输入类控件（含 contenteditable）：键盘快捷键和右键都让位给浏览器/原生控件。
function isTypingTarget(target) {
  const element = target instanceof Element ? target : null
  if (!element) return false
  if (element.isContentEditable) return true
  return Boolean(
    element.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])'),
  )
}

// 自己接管 Delete/Backspace：只把选中的边交给 App 删，绝不连带删节点。
// Ctrl+C / Ctrl+V 也在这里截获（输入框内不动，交给浏览器）。
function onKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey) {
    if (isTypingTarget(event.target)) return
    const key = event.key.toLowerCase()
    if (key === 'c') {
      // 有文字选中时放行，交给浏览器复制文字；没有选中文字才复制节点
      if (window.getSelection()?.toString()) return
      const ids = getSelectedNodes.value.map((node) => node.id)
      if (!ids.length) return
      event.preventDefault()
      emit('copy', ids)
    } else if (key === 'v') {
      event.preventDefault()
      emit('paste')
    }
    return
  }
  if (event.key !== 'Delete' && event.key !== 'Backspace') return
  if (event.ctrlKey || event.metaKey || event.altKey) return
  if (isTypingTarget(event.target)) return
  const selected = getSelectedEdges.value || []
  if (!selected.length) return
  event.preventDefault()
  emit('remove-edges', selected.map((edge) => edge.id))
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

// 选择变化：把选中单元抛给 App（右键菜单的组合判定、复制、删除后的收敛都读它）。
// getSelectedNodes 是 computed，选中标记一变就重算；computed 每次返回新数组，
// 所以按 id 串去重，拖动等无关重算不重复 emit。
let lastIds = ''
watch(getSelectedNodes, (list) => {
  const ids = list.map((node) => node.id)
  const key = ids.join('\u0000')
  if (key === lastIds) return
  lastIds = key
  emit('selection-change', ids)
})

function onDrop(event) {
  event.preventDefault()
  const raw = event.dataTransfer?.getData('application/x-workflow-component')
  if (!raw) return
  let payload
  try {
    payload = JSON.parse(raw)
  } catch {
    return
  }
  const point = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  emit('drop-component', {
    plugin: payload.plugin,
    component: payload.component,
    position: { x: point.x - 115, y: point.y - 30 },
  })
}

// 右键：输入类控件上不接管（参数表单里要复制粘贴文本），其余落点交给 App 决定菜单项。
function onContextMenu(event) {
  const target = event.target instanceof Element ? event.target : null
  if (isTypingTarget(target)) return
  event.preventDefault()
  // 连线没有菜单项，但原生菜单也不该冒出来
  if (target?.closest('.vue-flow__edge')) {
    emit('context-menu', null)
    return
  }
  const nodeEl = target?.closest('.vue-flow__node')
  emit('context-menu', {
    x: event.clientX,
    y: event.clientY,
    nodeId: nodeEl?.getAttribute('data-id') || null,
  })
}

/** 右键落点先成为唯一选中：清掉全部节点与边的选中，再选中给定节点。 */
function selectOnly(ids) {
  removeSelectedElements()
  const wanted = new Set(ids)
  const picked = getNodes.value.filter((node) => wanted.has(node.id))
  if (picked.length) addSelectedNodes(picked)
}

defineExpose({ fitView, clearSelection: removeSelectedElements, selectOnly })
</script>

<template>
  <div
    class="graph"
    @drop="onDrop"
    @dragover.prevent
    @dragenter.prevent
    @contextmenu.capture="onContextMenu"
  >
    <VueFlow
      v-model:nodes="nodes"
      :edges="edges"
      :node-types="props.nodeTypes"
      :edge-types="edgeTypes"
      :fit-view-on-init="true"
      :min-zoom="0.2"
      :max-zoom="2"
      :delete-key-code="null"
      @connect="emit('connect', $event)"
    />

    <div v-if="!nodes.length" class="graph-empty">
      从左侧组件库点击或拖入组件，开始搭建工作流
    </div>
  </div>
</template>

<style scoped>
.graph {
  position: relative;
  width: 100%;
  height: 100%;
  min-width: 0;
  overflow: hidden;
}

.graph :deep(.vue-flow) {
  width: 100%;
  height: 100%;
  background-color: #fafbfc;
  background-image: radial-gradient(#e3e6eb 1px, transparent 1px);
  background-size: 18px 18px;
}

.graph-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  pointer-events: none;
  font-size: 13px;
}
</style>
