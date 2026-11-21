<script setup>
import { markRaw, onBeforeUnmount, onMounted } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { canConnect } from '../groups.js'
import WorkflowEdge from './WorkflowEdge.vue'

const props = defineProps({
  nodeTypes: { type: Object, required: true },
  groups: { type: Array, default: () => [] },
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
])

const { fitView, screenToFlowCoordinate, getSelectedEdges, getSelectedNodes, removeSelectedElements } =
  useVueFlow()

// 连线使用自定义边：中点带删除按钮，选中时高亮
const edgeTypes = { workflow: markRaw(WorkflowEdge) }

function isTypingTarget(target) {
  const element = target instanceof Element ? target : null
  if (!element) return false
  const tag = element.tagName.toLowerCase()
  return (
    tag === 'input' ||
    tag === 'textarea' ||
    tag === 'select' ||
    element.isContentEditable
  )
}

// 自己接管 Delete/Backspace：只把选中的边交给 App 删，绝不连带删节点。
// Ctrl+C / Ctrl+V 也在这里截获（输入框内不动，交给浏览器）。
function onKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey) {
    if (isTypingTarget(event.target)) return
    const target = event.target instanceof Element ? event.target : null
    const inCanvas = Boolean(target?.closest('.vue-flow'))
    const hasTextSelection = Boolean(window.getSelection()?.toString())
    if (!inCanvas && hasTextSelection) return
    const key = event.key.toLowerCase()
    if (key === 'c') {
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

// 选择变化：多选/框选后把选中单元抛给 App 控制「组合」「解散」按钮
function onNodesChange(changes) {
  if (changes.some((change) => change.type === 'select')) {
    emit('selection-change', getSelectedNodes.value.map((node) => node.id))
  }
}

function isValidConnection(connection) {
  const { source, target, sourceHandle, targetHandle } = connection || {}
  if (!source || !target || source === target) return false
  if (!canConnect(props.groups, source, target)) return false
  const sourceNode = nodes.value.find((node) => node.id === source)
  const targetNode = nodes.value.find((node) => node.id === target)
  if (!sourceNode || !targetNode) return false
  const output = (sourceNode.data?.outPorts || []).find((port) => port.name === sourceHandle)
  const input = (targetNode.data?.inPorts || []).find((port) => port.name === targetHandle)
  return Boolean(output && input && input.types.includes(output.type))
}

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

defineExpose({ fitView, clearSelection: removeSelectedElements })
</script>

<template>
  <div class="graph" @drop="onDrop" @dragover.prevent @dragenter.prevent>
    <VueFlow
      v-model:nodes="nodes"
      :edges="edges"
      :node-types="props.nodeTypes"
      :edge-types="edgeTypes"
      :is-valid-connection="isValidConnection"
      :fit-view-on-init="true"
      :min-zoom="0.2"
      :max-zoom="2"
      :delete-key-code="null"
      @connect="emit('connect', $event)"
      @nodes-change="onNodesChange"
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
