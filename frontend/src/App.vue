<script setup>
import { computed, markRaw, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import ComponentNode from './components/ComponentNode.vue'
import CollapsedRail from './components/CollapsedRail.vue'
import EnvDrawer from './components/EnvDrawer.vue'
import GraphCanvas from './components/GraphCanvas.vue'
import Inspector from './components/Inspector.vue'
import Palette from './components/Palette.vue'
import ResultPanel from './components/ResultPanel.vue'
import { fetchHealth, fetchPlugins, runWorkflow, validateWorkflow } from './api'
import { buildNodeData, planImport } from './importWorkflow'
import { buildWorkflow as modelBuildWorkflow } from './model'
import { envError, envToRows } from './workflow'

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
const workflowEnv = ref([])
const envDrawerVisible = ref(false)

const validateReport = ref(null)
const runResult = ref(null)
const validating = ref(false)
const running = ref(false)
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

// ---- 节点构造 ----------------------------------------------------------

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
    data: buildNodeData(entry, {}, { typeDescs: typeDescs.value, typeColors: typeColors.value }),
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
  return modelBuildWorkflow({
    name: workflowName.value,
    nodes: nodes.value,
    edges: edges.value,
    envRows: workflowEnv.value,
  })
}

function importEnv(raw) {
  if (raw.env === undefined) {
    workflowEnv.value = []
    return
  }
  const rows = envToRows(raw.env)
  if (rows === null) {
    workflowEnv.value = []
    ElMessage.warning('工作流顶层 env 不是对象，已忽略')
    return
  }
  workflowEnv.value = rows
}

function exportJson() {
  const problem = envError(workflowEnv.value)
  if (problem) {
    ElMessage.error(problem)
    return
  }
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

async function applyWorkflow(raw) {
  const plan = planImport(raw, {
    componentFor: (plugin, component) => componentIndex.value.get(`${plugin}.${component}`),
    typeDescs: typeDescs.value,
    typeColors: typeColors.value,
  })

  workflowName.value = plan.name
  importEnv(raw)
  nodes.value = plan.nodes
  edges.value = plan.edges
  validateReport.value = null
  runResult.value = null
  activeTab.value = 'validate'

  if (plan.missing.length) {
    ElMessage.warning(
      `有 ${plan.missing.length} 个组件未加载：${[...new Set(plan.missing)].join(', ')}`,
    )
  }
  if (plan.skipped.length) {
    ElMessage.warning(`导入时跳过 ${plan.skipped.length} 项：${plan.skipped.slice(0, 3).join('；')}`)
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
  workflowEnv.value = []
  validateReport.value = null
  runResult.value = null
  activeTab.value = 'validate'
}

async function doValidate() {
  validating.value = true
  try {
    validateReport.value = await validateWorkflow(buildWorkflow())
  } catch (err) {
    validateReport.value = { ok: false, errors: [err.message], warnings: [], order: [] }
  } finally {
    validating.value = false
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
  running.value = true
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
    running.value = false
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
      <el-button
        size="small"
        type="primary"
        plain
        :loading="validating"
        :disabled="running"
        @click="doValidate"
      >
        校验
      </el-button>
      <el-button
        size="small"
        type="primary"
        :loading="running"
        :disabled="validating"
        @click="doRun"
      >
        运行
      </el-button>
      <el-button size="small" @click="envDrawerVisible = true">环境变量</el-button>

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

    <EnvDrawer v-model:visible="envDrawerVisible" v-model:rows="workflowEnv" />
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
