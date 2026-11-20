<script setup>
import { computed, markRaw, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import ComponentNode from './components/ComponentNode.vue'
import CollapsedRail from './components/CollapsedRail.vue'
import GraphCanvas from './components/GraphCanvas.vue'
import Inspector from './components/Inspector.vue'
import Palette from './components/Palette.vue'
import ResultPanel from './components/ResultPanel.vue'
import { fetchHealth, fetchPlugins, runWorkflow, validateWorkflow } from './api'

const TYPE_COLORS = [
  '#409eff',
  '#67c23a',
  '#e6a23c',
  '#f56c6c',
  '#9b59b6',
  '#16a085',
  '#d35400',
  '#2c3e50',
  '#c0392b',
  '#2980b9',
  '#8e44ad',
  '#b8860b',
]

const plugins = ref([])
const typeDescs = ref({})
const typeColors = ref({})

const nodes = ref([])
const edges = ref([])
const workflowName = ref('未命名工作流')

const validateReport = ref(null)
const runResult = ref(null)
const busy = ref('')
const activeTab = ref('validate')
const serverOnline = ref(null)

const fileInput = ref(null)
const graphRef = ref(null)

// ---- 三面板布局（开合 / 尺寸，localStorage 持久化） ---------------------

const LAYOUT_KEY = 'workflow-studio:layout'

const layout = ref({
  leftOpen: true,
  rightOpen: true,
  bottomOpen: true,
  leftWidth: 248,
  rightWidth: 320,
  bottomHeight: 232,
})

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

function clampNumber(value, fallback, min, max) {
  const number = Number(value)
  return Number.isFinite(number) ? clamp(number, min, max) : fallback
}

function loadLayout() {
  try {
    const saved = JSON.parse(localStorage.getItem(LAYOUT_KEY) || 'null')
    if (!saved || typeof saved !== 'object') return
    for (const key of ['leftOpen', 'rightOpen', 'bottomOpen']) {
      if (typeof saved[key] === 'boolean') layout.value[key] = saved[key]
    }
    layout.value.leftWidth = clampNumber(saved.leftWidth, 248, 180, 420)
    layout.value.rightWidth = clampNumber(saved.rightWidth, 320, 220, 480)
    layout.value.bottomHeight = clampNumber(saved.bottomHeight, 232, 120, 600)
  } catch {
    // localStorage 不可用时用默认布局
  }
}

function saveLayout() {
  try {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout.value))
  } catch {
    // 忽略隐私模式等写入失败
  }
}

function togglePanel(panel) {
  if (panel === 'left') layout.value.leftOpen = !layout.value.leftOpen
  else if (panel === 'right') layout.value.rightOpen = !layout.value.rightOpen
  else layout.value.bottomOpen = !layout.value.bottomOpen
  saveLayout()
}

function startResize(panel, event) {
  if (event.button !== 0) return
  event.preventDefault()
  const startX = event.clientX
  const startY = event.clientY
  const startWidth = panel === 'right' ? layout.value.rightWidth : layout.value.leftWidth
  const startHeight = layout.value.bottomHeight

  const onMove = (moveEvent) => {
    if (panel === 'left') {
      layout.value.leftWidth = clamp(startWidth + (moveEvent.clientX - startX), 180, 420)
    } else if (panel === 'right') {
      layout.value.rightWidth = clamp(startWidth - (moveEvent.clientX - startX), 220, 480)
    } else {
      layout.value.bottomHeight = clamp(startHeight - (moveEvent.clientY - startY), 120, 600)
    }
  }

  const onUp = () => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    window.removeEventListener('pointercancel', onUp)
    saveLayout()
  }

  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onUp)
}

loadLayout()

const nodeTypes = { comp: markRaw(ComponentNode) }

const componentIndex = computed(() => {
  const index = new Map()
  for (const plugin of plugins.value) {
    for (const component of plugin.components) {
      index.set(`${plugin.name}.${component.name}`, component)
    }
  }
  return index
})

// ---- 类型显示 ----------------------------------------------------------

function typeColor(typeId) {
  return typeColors.value[typeId] || '#909399'
}

/** 端口短名直接用后端给的 type_labels / type_label。 */
function portDisplay(types, labels) {
  const short = labels.length > 1 ? `${labels[0]} +${labels.length - 1}` : labels[0]
  const full = types
    .map((id, index) => `${labels[index]}${typeDescs.value[id] ? ` — ${typeDescs.value[id]}` : ''}`)
    .join('\n')
  return { short, full }
}

// ---- 节点构造 ----------------------------------------------------------

function defaultsFor(schema) {
  const config = {}
  for (const [name, spec] of Object.entries(schema || {})) {
    if (spec && Object.prototype.hasOwnProperty.call(spec, 'default')) {
      config[name] = structuredClone(spec.default)
    }
  }
  return config
}

function buildNodeData(component, config) {
  return {
    plugin: component.plugin,
    pluginTitle: component.pluginTitle || '',
    component: component.name,
    title: component.title,
    desc: component.desc,
    config: { ...defaultsFor(component.config_schema), ...(config || {}) },
    config_schema: component.config_schema,
    descOpen: false,
    paramsOpen: true,
    inPorts: Object.entries(component.input_schema || {}).map(([name, spec]) => {
      const display = portDisplay(spec.types, spec.type_labels)
      return {
        name,
        types: spec.types || [],
        color: typeColor((spec.types || [])[0]),
        short: display.short,
        full: display.full,
      }
    }),
    outPorts: Object.entries(component.output_schema || {}).map(([name, spec]) => {
      const display = portDisplay([spec.type], [spec.type_label])
      return {
        name,
        type: spec.type,
        color: typeColor(spec.type),
        short: display.short,
        full: display.full,
      }
    }),
    missing: false,
    failed: false,
  }
}

function missingNodeData(plugin, component) {
  return {
    plugin,
    pluginTitle: '',
    component,
    title: `${plugin}.${component}`,
    desc: '当前插件集合里没有这个组件',
    config: {},
    config_schema: {},
    descOpen: false,
    paramsOpen: true,
    inPorts: [],
    outPorts: [],
    missing: true,
    failed: false,
  }
}

function nextNodeId() {
  const used = new Set(nodes.value.map((node) => node.id))
  let index = nodes.value.length + 1
  while (used.has(`n${index}`)) index += 1
  return `n${index}`
}

function autoPosition() {
  const index = nodes.value.length
  return { x: 80 + (index % 3) * 340, y: 60 + Math.floor(index / 3) * 440 }
}

function addNode({ plugin, component, position }) {
  const entry = componentIndex.value.get(`${plugin}.${component}`)
  if (!entry) {
    ElMessage.error(`组件不存在：${plugin}.${component}`)
    return
  }
  const node = {
    id: nextNodeId(),
    type: 'comp',
    position: position || autoPosition(),
    data: buildNodeData(entry, {}),
  }
  nodes.value = [...nodes.value, node]
}

function onConnect(connection) {
  if (!connection?.source || !connection?.target) return
  const { source, target, sourceHandle, targetHandle } = connection
  const kept = edges.value.filter(
    (edge) => !(edge.target === target && edge.targetHandle === targetHandle),
  )
  kept.push({
    id: `e-${target}-${targetHandle}`,
    type: 'workflow',
    source,
    target,
    sourceHandle,
    targetHandle,
  })
  edges.value = kept
}

// ---- 导入 / 导出 -------------------------------------------------------

function buildWorkflow() {
  const inputsByTarget = new Map()
  for (const edge of edges.value) {
    if (!edge.source || !edge.target || !edge.targetHandle || !edge.sourceHandle) continue
    if (!inputsByTarget.has(edge.target)) inputsByTarget.set(edge.target, {})
    inputsByTarget.get(edge.target)[edge.targetHandle] = {
      from: edge.source,
      port: edge.sourceHandle,
    }
  }

  return {
    name: workflowName.value.trim() || '未命名工作流',
    nodes: nodes.value.map((node) => ({
      id: node.id,
      plugin: node.data.plugin,
      component: node.data.component,
      config: { ...node.data.config },
      inputs: inputsByTarget.get(node.id) || {},
    })),
  }
}

function exportJson() {
  const workflow = buildWorkflow()
  const text = JSON.stringify(workflow, null, 2)
  const blob = new Blob([text], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${workflow.name.replace(/[\\/:*?"<>|]/g, '_')}.json`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出工作流 JSON')
}

function layoutDepth(rawNodes) {
  const byId = new Map()
  for (const raw of rawNodes) {
    if (raw && typeof raw.id === 'string') byId.set(raw.id, raw)
  }
  const memo = new Map()
  const visiting = new Set()

  function depthOf(id) {
    if (memo.has(id)) return memo.get(id)
    if (visiting.has(id)) return 0
    visiting.add(id)
    const raw = byId.get(id)
    let depth = 0
    if (raw && raw.inputs && typeof raw.inputs === 'object') {
      for (const link of Object.values(raw.inputs)) {
        if (
          link &&
          typeof link === 'object' &&
          typeof link.from === 'string' &&
          byId.has(link.from)
        ) {
          depth = Math.max(depth, depthOf(link.from) + 1)
        }
      }
    }
    visiting.delete(id)
    memo.set(id, depth)
    return depth
  }

  return depthOf
}

async function applyWorkflow(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('JSON 根节点必须是对象')
  if (!Array.isArray(raw.nodes)) throw new Error('缺少 nodes 数组')

  const raws = []
  const seen = new Set()
  const skipped = []
  for (const item of raw.nodes) {
    if (!item || typeof item !== 'object') {
      skipped.push('存在非对象节点')
      continue
    }
    if (typeof item.id !== 'string' || !item.id) {
      skipped.push('节点缺少 id')
      continue
    }
    if (seen.has(item.id)) {
      skipped.push(`id 重复：${item.id}`)
      continue
    }
    if (typeof item.plugin !== 'string' || typeof item.component !== 'string') {
      skipped.push(`${item.id} 缺少 plugin/component`)
      continue
    }
    seen.add(item.id)
    raws.push(item)
  }

  const depthOf = layoutDepth(raws)
  const rows = new Map()
  const created = []
  const missing = []

  for (const item of raws) {
    const depth = depthOf(item.id)
    const row = rows.get(depth) || 0
    rows.set(depth, row + 1)
    const position = { x: 80 + depth * 340, y: 60 + row * 440 }
    const entry = componentIndex.value.get(`${item.plugin}.${item.component}`)
    if (!entry) {
      missing.push(`${item.plugin}.${item.component}`)
      created.push({
        id: item.id,
        type: 'comp',
        position,
        data: missingNodeData(item.plugin, item.component),
      })
      continue
    }
    const config = item.config && typeof item.config === 'object' ? item.config : {}
    created.push({ id: item.id, type: 'comp', position, data: buildNodeData(entry, config) })
  }

  const nodeById = new Map(created.map((node) => [node.id, node]))
  const inputsTaken = new Set()
  const newEdges = []
  for (const item of raws) {
    const targetNode = nodeById.get(item.id)
    if (!targetNode || !item.inputs || typeof item.inputs !== 'object') continue
    for (const [port, link] of Object.entries(item.inputs)) {
      if (!link || typeof link !== 'object') continue
      if (typeof link.from !== 'string' || typeof link.port !== 'string') continue
      const sourceNode = nodeById.get(link.from)
      if (!sourceNode) continue
      if (!targetNode.data.inPorts.some((entry) => entry.name === port)) continue
      if (!sourceNode.data.outPorts.some((entry) => entry.name === link.port)) continue
      const key = `${item.id}.${port}`
      if (inputsTaken.has(key)) continue
      inputsTaken.add(key)
      newEdges.push({
        id: `e-${item.id}-${port}`,
        type: 'workflow',
        source: link.from,
        target: item.id,
        sourceHandle: link.port,
        targetHandle: port,
      })
    }
  }

  workflowName.value = typeof raw.name === 'string' && raw.name ? raw.name : '导入的工作流'
  nodes.value = created
  edges.value = newEdges
  validateReport.value = null
  runResult.value = null
  activeTab.value = 'validate'

  if (missing.length) {
    ElMessage.warning(`有 ${missing.length} 个组件未加载：${[...new Set(missing)].join(', ')}`)
  }
  if (skipped.length) {
    ElMessage.warning(`导入时跳过 ${skipped.length} 项：${skipped.slice(0, 3).join('；')}`)
  }

  await nextTick()
  graphRef.value?.fitView?.({ padding: 0.2 })
}

async function onImportFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    const raw = JSON.parse(await file.text())
    await applyWorkflow(raw)
    ElMessage.success(`已导入 ${nodes.value.length} 个节点`)
  } catch (err) {
    ElMessage.error(`导入失败：${err.message}`)
  }
}

// ---- 工具栏动作 --------------------------------------------------------

async function newWorkflow() {
  if (nodes.value.length) {
    try {
      await ElMessageBox.confirm('清空当前画布？', '新建工作流', { type: 'warning' })
    } catch {
      return
    }
  }
  nodes.value = []
  edges.value = []
  workflowName.value = '未命名工作流'
  validateReport.value = null
  runResult.value = null
  activeTab.value = 'validate'
}

async function doValidate() {
  busy.value = 'validate'
  try {
    validateReport.value = await validateWorkflow(buildWorkflow())
  } catch (err) {
    validateReport.value = { ok: false, errors: [err.message], warnings: [], order: [] }
  } finally {
    busy.value = ''
    activeTab.value = 'validate'
  }
}

function markFailedNodes(failedIds) {
  const failed = new Set(failedIds || [])
  for (const node of nodes.value) {
    node.data.failed = failed.has(node.id)
  }
}

async function doRun() {
  busy.value = 'run'
  runResult.value = null
  try {
    runResult.value = await runWorkflow(buildWorkflow())
  } catch (err) {
    runResult.value = {
      ok: false,
      errors: [err.message],
      warnings: [],
      order: [],
      nodes: [],
      failedIds: [],
    }
  } finally {
    busy.value = ''
    activeTab.value = 'run'
    markFailedNodes(runResult.value?.failedIds)
  }
}

// ---- 后端连接 ----------------------------------------------------------

async function checkHealth() {
  try {
    await fetchHealth()
    serverOnline.value = true
  } catch {
    serverOnline.value = false
  }
}

async function loadPlugins() {
  try {
    const data = await fetchPlugins()
    plugins.value = data.plugins
    typeDescs.value = data.typeDescs

    const colors = {}
    Object.keys(data.typeLabels)
      .sort()
      .forEach((typeId, index) => {
        colors[typeId] = TYPE_COLORS[index % TYPE_COLORS.length]
      })
    typeColors.value = colors
  } catch (err) {
    ElMessage.error(`加载插件失败：${err.message}（确认后端已在 8765 启动）`)
  }
}

onMounted(async () => {
  await loadPlugins()
  await checkHealth()
})
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">工作流编辑器</div>

      <el-input
        v-model="workflowName"
        size="small"
        class="name-input"
        placeholder="工作流名称"
      />

      <el-button size="small" @click="newWorkflow">新建</el-button>
      <el-button size="small" @click="fileInput.click()">导入 JSON</el-button>
      <el-button size="small" @click="exportJson">导出 JSON</el-button>
      <el-button size="small" type="primary" plain :loading="busy === 'validate'" @click="doValidate">
        校验
      </el-button>
      <el-button size="small" type="primary" :loading="busy === 'run'" @click="doRun">
        运行
      </el-button>

      <div class="spacer"></div>

      <el-tag
        size="small"
        effect="plain"
        class="health"
        :type="serverOnline === null ? 'info' : serverOnline ? 'success' : 'danger'"
        @click="checkHealth"
      >
        {{ serverOnline === null ? '检测后端…' : serverOnline ? '后端在线' : '后端未连接' }}
      </el-tag>

      <input ref="fileInput" type="file" accept=".json,application/json" hidden @change="onImportFile" />
    </header>

    <main class="main">
      <Palette
        v-if="layout.leftOpen"
        :plugins="plugins"
        :style="{ width: layout.leftWidth + 'px' }"
        @add="addNode"
        @collapse="togglePanel('left')"
      />
      <CollapsedRail
        v-else
        side="left"
        label="组件库"
        @expand="togglePanel('left')"
      />
      <div
        v-if="layout.leftOpen"
        class="resize-handle resize-vertical"
        title="拖拽调整左栏宽度"
        @pointerdown="startResize('left', $event)"
      />

      <GraphCanvas
        ref="graphRef"
        v-model:nodes="nodes"
        v-model:edges="edges"
        class="canvas"
        :node-types="nodeTypes"
        @connect="onConnect"
        @drop-component="addNode"
      />

      <div
        v-if="layout.rightOpen"
        class="resize-handle resize-vertical"
        title="拖拽调整右栏宽度"
        @pointerdown="startResize('right', $event)"
      />
      <Inspector
        v-if="layout.rightOpen"
        :style="{ width: layout.rightWidth + 'px' }"
        @collapse="togglePanel('right')"
      />
      <CollapsedRail
        v-else
        side="right"
        label="智能生成"
        @expand="togglePanel('right')"
      />
    </main>

    <div
      v-if="layout.bottomOpen"
      class="resize-handle resize-horizontal"
      title="拖拽调整底部高度"
      @pointerdown="startResize('bottom', $event)"
    />
    <ResultPanel
      v-if="layout.bottomOpen"
      v-model:active-tab="activeTab"
      :report="validateReport"
      :run="runResult"
      :style="{ height: layout.bottomHeight + 'px' }"
      @collapse="togglePanel('bottom')"
    />
    <CollapsedRail
      v-else
      side="bottom"
      label="运行结果"
      @expand="togglePanel('bottom')"
    />
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 48px;
  flex: none;
  padding: 0 12px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}

.topbar :deep(.el-button + .el-button) {
  margin-left: 0;
}

.brand {
  font-weight: 600;
  font-size: 14px;
  margin-right: 6px;
  white-space: nowrap;
}

.name-input {
  width: 190px;
  margin-right: 4px;
}

.spacer {
  flex: 1;
}

.health {
  cursor: pointer;
}

.main {
  display: flex;
  flex: 1;
  min-height: 0;
}

.canvas {
  flex: 1;
  min-width: 0;
}

.resize-handle {
  flex: none;
  touch-action: none;
  background: transparent;
  transition: background 0.15s;
}

.resize-vertical {
  width: 5px;
  cursor: col-resize;
}

.resize-horizontal {
  height: 5px;
  cursor: row-resize;
}

.resize-vertical:hover,
.resize-horizontal:hover {
  background: #d9ecff;
}
</style>
