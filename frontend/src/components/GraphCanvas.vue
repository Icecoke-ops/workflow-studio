<script setup>
import { markRaw, onBeforeUnmount, onMounted } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import WorkflowEdge from './WorkflowEdge.vue'

const props = defineProps({
  nodeTypes: { type: Object, required: true },
})

const nodes = defineModel('nodes', { default: () => [] })
const edges = defineModel('edges', { default: () => [] })

const emit = defineEmits(['connect', 'drop-component'])

const { fitView, screenToFlowCoordinate, getSelectedEdges, removeEdges } =
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

// 自己接管 Delete/Backspace：只删选中的边，绝不连带删节点。
// Vue Flow 原生删除会同时删掉选中的节点，所以下面把 delete-key-code 禁用。
function onKeydown(event) {
  if (event.key !== 'Delete' && event.key !== 'Backspace') return
  if (event.ctrlKey || event.metaKey || event.altKey) return
  if (isTypingTarget(event.target)) return
  const selected = getSelectedEdges.value || []
  if (!selected.length) return
  event.preventDefault()
  removeEdges(selected.map((edge) => edge.id))
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

function isValidConnection(connection) {
  const { source, target, sourceHandle, targetHandle } = connection || {}
  if (!source || !target || source === target) return false
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

defineExpose({ fitView })
</script>

<template>
  <div class="graph" @drop="onDrop" @dragover.prevent @dragenter.prevent>
    <VueFlow
      v-model:nodes="nodes"
      v-model:edges="edges"
      :node-types="props.nodeTypes"
      :edge-types="edgeTypes"
      :is-valid-connection="isValidConnection"
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
