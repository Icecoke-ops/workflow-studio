<script setup>
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import ActivityBar from './components/ActivityBar.vue'
import ComponentNode from './components/ComponentNode.vue'
import CollapsedRail from './components/CollapsedRail.vue'
import ContextMenu from './components/ContextMenu.vue'
import EnvDrawer from './components/EnvDrawer.vue'
import GraphCanvas from './components/GraphCanvas.vue'
import GroupFrame from './components/GroupFrame.vue'
import GroupNode from './components/GroupNode.vue'
import Inspector from './components/Inspector.vue'
import Palette from './components/Palette.vue'
import ProjectPanel from './components/ProjectPanel.vue'
import TextViewer from './components/TextViewer.vue'
import BottomDock from './components/BottomDock.vue'
import { readAddition } from './addition'
import {
  fetchFile,
  fetchHealth,
  fetchPlugins,
  fetchProject,
  runWorkflow,
  startDebugSession,
  stopDebugSession,
  validateWorkflow,
  writeFile,
} from './api'
import { collectCopy, planPaste } from './clipboard'
import { DebugClient } from './debug/client.js'
import { EMPTY_VIEW, appendLog, applyState, isBusy } from './debug/model.js'
import { isFlowPath, normalizePath, titleFromPath } from './documents'
import {
  canGroup,
  commonParent,
  connectionAllowed,
  createGroup,
  dissolveGroup,
  dropEdgesForNodes,
  groupPositions,
  isComponentNode,
  memberLeaves,
  nextGroupId,
  nodeBoxes,
  pruneGroups,
  projectGraph,
  renameGroup,
  selectionBox,
  selectionUnits,
  serializeGroups,
  setCollapsed,
  unitBox,
} from './groups'
import { buildNodeData, missingNodeData, planImport } from './importWorkflow'
import { buildWorkflow as modelBuildWorkflow } from './model'
import { trackPointer } from './pointer'
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
const canvasEdges = ref([])
const groups = ref([])
const selectedIds = ref([])
const clipboard = ref(null)
const contextMenu = ref(null)

// ---- 调试会话状态（协议见 docs/CONTRACT.md §9.6 / §6.1） ----
const debugSession = ref(null) // { session, port, token }
const debugView = ref(EMPTY_VIEW)
const debugLogs = ref([])
const debugError = ref('')
const debugStarting = ref(false)
let debugClient = null

const debugActive = computed(() => debugSession.value !== null)
const debugBusy = computed(() => isBusy(debugView.value.phase))
const workflowName = ref('未命名工作流')
const workflowEnv = ref([])
const additionState = ref(null)
const envDrawerVisible = ref(false)

// ---- 项目与文档（当前只允许一个文档，结构上按多标签留） ------------------
const project = ref(null) // { root, name, launcher }
const leftView = ref('explorer')
const docs = ref([])
const activeId = ref(null)
const saving = ref(false)

const activeDoc = computed(() => docs.value.find((doc) => doc.id === activeId.value) || null)

const validateReport = ref(null)
const runResult = ref(null)
const validating = ref(false)
const running = ref(false)
const activeTab = ref('validate')
const serverOnline = ref(null)

const graphRef = ref(null)

// ---- 三面板布局（开合 / 尺寸，localStorage 持久化） ---------------------

const LAYOUT_KEY = 'workflow-studio:layout'

const layout = ref({
  leftOpen: true,
  rightOpen: false,
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

  trackPointer(onMove, saveLayout)
}

loadLayout()

const nodeTypes = {
  comp: markRaw(ComponentNode),
  group: markRaw(GroupNode),
  frame: markRaw(GroupFrame),
}

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
  if (activeDoc.value?.kind !== 'flow') {
    ElMessage.warning('先打开一个流程图文件')
    return
  }
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
  reproject()
}

function onConnect(connection) {
  // 新连线只校验「两端不是同一可见实体」+ 端口类型兼容，不按层级拒绝。
  // 跨子图边界的连线必须放行：折叠组的跨组边就是这样产生的。
  // 校验只作用于用户新拉的线；不能交给 Vue Flow 的 isValidConnection prop，
  // 那会对每一条模型边重审，导入/投影边会被误杀。
  const real = connectionAllowed(nodes.value, groups.value, connection)
  if (!real) return
  const kept = edges.value.filter(
    (edge) => !(edge.target === real.target && edge.targetHandle === real.targetHandle),
  )
  kept.push({
    id: `e-${real.target}-${real.targetHandle}`,
    type: 'workflow',
    ...real,
  })
  edges.value = kept
  reproject()
}

// ---- 子图接线 ----------------------------------------------------------

function decorateNodes(projectedNodes) {
  return projectedNodes.map((node) => {
    if (node.type === 'group') {
      return {
        ...node,
        data: {
          ...node.data,
          onDeleteSubgraph: deleteSubgraph,
          onToggleCollapse: toggleGroupCollapsed,
          onRename: renameOne,
        },
      }
    }
    if (node.type === 'frame') {
      return {
        ...node,
        data: { ...node.data, onToggleCollapse: toggleGroupCollapsed, onRename: renameOne },
      }
    }
    return withDebug({ ...node, data: { ...node.data, onDelete: removeComponent } })
  })
}

/** 组件节点挂调试信息：右上角运行三角 + 状态描边；非调试态一律 null。 */
function withDebug(node) {
  const status = debugActive.value ? debugView.value.nodes[node.id]?.status || 'unrun' : null
  return {
    ...node,
    data: {
      ...node.data,
      debugStatus: status,
      debugCanRun: debugActive.value && !debugBusy.value,
      onDebugRun: runDebugNode,
    },
  }
}

/** 状态 / phase / 在途标记变了就刷新画布节点上的调试字段，不动图结构。 */
function refreshDebugNodes() {
  nodes.value = nodes.value.map((node) => (isComponentNode(node) ? withDebug(node) : node))
}

function decorateEdges(projectedEdges) {
  return projectedEdges.map((edge) => ({
    ...edge,
    data: { onDelete: (id) => onEdgesRemoved([id]) },
  }))
}

/** 真实节点/边/组 -> 画布三件套：组件节点（折叠时 hidden）+ 组卡片/框 + 投影边。 */
function reproject() {
  const projected = projectGraph({ nodes: nodes.value, edges: edges.value, groups: groups.value })
  nodes.value = decorateNodes(projected.nodes)
  canvasEdges.value = decorateEdges(projected.edges)
}

function removeComponent(id) {
  nodes.value = nodes.value.filter((node) => node.id !== id)
  edges.value = dropEdgesForNodes(edges.value, [id])
  groups.value = pruneGroups(groups.value, nodes.value)
  reproject()
}

function onEdgesRemoved(ids) {
  const removed = new Set(ids)
  const next = edges.value.filter((edge) => !removed.has(edge.id))
  if (next.length === edges.value.length) return
  edges.value = next
  reproject()
}

function onSelectionChange(ids) {
  selectedIds.value = ids
}

function groupSelection() {
  const units = selectionUnits(groups.value, selectedIds.value)
  const parent = commonParent(groups.value, units)
  if (units.length < 2 || parent === undefined) {
    ElMessage.warning('请先选中同一层的至少两个单元')
    return
  }
  const box = selectionBox(units, groups.value, nodeBoxes(nodes.value))
  groups.value = createGroup(groups.value, {
    id: nextGroupId(groups.value, nodes.value),
    title: `子图 ${groups.value.length + 1}`,
    units,
    parent,
    position: box ? { x: box.x + box.width / 2, y: box.y + box.height / 2 } : null,
  })
  reproject()
  graphRef.value?.clearSelection?.()
}

function dissolveOne(groupId) {
  groups.value = dissolveGroup(groups.value, groupId)
  reproject()
  graphRef.value?.clearSelection?.()
}

/** 删除整棵子图：叶子组件、相关边、该组和全部嵌套组一起删，父组交给 pruneGroups 收敛。 */
async function deleteSubgraph(groupId) {
  const group = groups.value.find((item) => item.id === groupId)
  if (!group) return
  // 先按实际要删的集合取数：members 里有重复 id 时 leaf 条数会比去重后的节点数多
  const doomedNodes = new Set(memberLeaves(groups.value, groupId).map((leaf) => leaf.nodeId))
  try {
    await ElMessageBox.confirm(
      `将删除「${group.title}」及其中 ${doomedNodes.size} 个组件，无法撤销`,
      '删除子图',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  nodes.value = nodes.value.filter((node) => !doomedNodes.has(node.id))
  edges.value = dropEdgesForNodes(edges.value, [...doomedNodes])
  groups.value = pruneGroups(groups.value, nodes.value)
  reproject()
  // 子树随 prune 消失：选中集合里已不存在的节点/组 id 统一清掉（保留的是确定收敛，不赌 watch 时序）
  const alive = new Set(nodes.value.map((node) => node.id))
  selectedIds.value = selectedIds.value.filter((id) => alive.has(id))
}

function toggleGroupCollapsed(groupId, collapsed) {
  let position = null
  if (collapsed) {
    const box = unitBox(groupId, groups.value, nodeBoxes(nodes.value))
    if (box) position = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
  }
  groups.value = setCollapsed(groups.value, groupId, collapsed, position)
  reproject()
}

function renameOne(groupId, title) {
  groups.value = renameGroup(groups.value, groupId, title)
  reproject()
}

// ---- 右键菜单 ----------------------------------------------------------

let menuSeq = 0

/** 画布右键落点 -> 菜单项（每项自带动作，点击即执行）。 */
function onCanvasContextMenu(payload) {
  if (!payload) {
    contextMenu.value = null
    return
  }
  const { x, y, nodeId } = payload
  const node = nodeId ? nodes.value.find((item) => item.id === nodeId) : null
  if (!node) {
    contextMenu.value = {
      id: ++menuSeq,
      x,
      y,
      items: [{ label: '粘贴', disabled: !clipboard.value, action: () => pasteClipboard() }],
    }
    return
  }

  // 右键未选中的单元 -> 先把它设成唯一选中；已在选中集合里 -> 保留多选（组合才够得着）
  const unit = selectionUnits(groups.value, [node.id])[0]
  const selectedUnits = selectionUnits(groups.value, selectedIds.value)
  const keepSelection = selectedUnits.includes(unit)
  if (!keepSelection) graphRef.value?.selectOnly?.([node.id])
  const units = keepSelection ? selectedUnits : [unit]
  const ids = keepSelection ? selectedIds.value : [node.id]

  const items = [{ label: '复制', action: () => copySelection(ids) }]
  if (!isComponentNode(node)) {
    items.push({ label: '解散子图', action: () => dissolveOne(unit) })
    items.push({ label: '删除子图', danger: true, action: () => deleteSubgraph(unit) })
  }
  if (canGroup(groups.value, units)) items.push({ label: '组合', action: () => groupSelection() })

  contextMenu.value = { id: ++menuSeq, x, y, items }
}

function onMenuSelect(item) {
  contextMenu.value = null
  item.action()
}

// ---- 复制 / 粘贴 --------------------------------------------------------

function copySelection(ids = selectedIds.value) {
  const snapshot = collectCopy({
    nodes: nodes.value,
    edges: edges.value,
    groups: groups.value,
    selectedIds: ids,
  })
  if (!snapshot.nodes.length) {
    ElMessage.warning('请先选中要复制的节点或子图')
    return
  }
  clipboard.value = snapshot
}

function pasteClipboard() {
  if (!clipboard.value) return
  const plan = planPaste(clipboard.value, { nodes: nodes.value, groups: groups.value })
  const created = plan.nodes.map((item) => {
    const entry = componentIndex.value.get(`${item.plugin}.${item.component}`)
    return {
      id: item.id,
      type: 'comp',
      position: item.position,
      data: entry
        ? buildNodeData(entry, item.config, {
            typeDescs: typeDescs.value,
            typeColors: typeColors.value,
          })
        : missingNodeData(item.plugin, item.component),
    }
  })
  nodes.value = [...nodes.value, ...created]
  edges.value = [...edges.value, ...plan.edges]
  groups.value = [...groups.value, ...plan.groups]
  reproject()
}

// ---- 工作流 JSON -------------------------------------------------------

function buildWorkflow() {
  return modelBuildWorkflow({
    name: workflowName.value,
    nodes: nodes.value,
    edges: edges.value,
    envRows: workflowEnv.value,
    addition: additionState.value,
    groups: serializeGroups(pruneGroups(groups.value, nodes.value), groupPositions(nodes.value)),
  })
}

// 内容签名只包含会写进文件的字段（节点位置在 addition 里）；选中、调试状态不进签名。
const contentSignature = computed(() => JSON.stringify(buildWorkflow()))
const dirty = computed(() => {
  const doc = activeDoc.value
  return Boolean(doc && doc.kind === 'flow' && doc.savedSignature !== contentSignature.value)
})

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

/** 载入一份工作流 JSON 到画布；取景由 openDocument 在画布挂载后做。 */
function applyWorkflow(raw) {
  const plan = planImport(raw, {
    componentFor: (plugin, component) => componentIndex.value.get(`${plugin}.${component}`),
    typeDescs: typeDescs.value,
    typeColors: typeColors.value,
  })
  const addition = readAddition(raw)

  workflowName.value = plan.name
  importEnv(raw)
  additionState.value = addition
  groups.value = plan.groups
  nodes.value = plan.nodes
  edges.value = plan.edges
  selectedIds.value = []
  validateReport.value = null
  runResult.value = null
  activeTab.value = 'validate'
  reproject()

  if (addition.warning) {
    ElMessage.warning(addition.warning)
  }
  if (plan.droppedGroups) {
    ElMessage.warning(
      `导入时忽略 ${plan.droppedGroups} 个子图分组（id 为空、重复或与节点冲突）`,
    )
  }
  const prunedParts = []
  if (plan.prunedGroups) prunedParts.push(`丢弃 ${plan.prunedGroups} 组`)
  if (plan.trimmedMembers) prunedParts.push(`移除 ${plan.trimmedMembers} 个成员`)
  if (prunedParts.length) {
    ElMessage.warning(`导入时按文件里现有节点裁剪分组：${prunedParts.join('、')}`)
  }
  if (plan.missing.length) {
    ElMessage.warning(
      `有 ${plan.missing.length} 个组件未加载：${[...new Set(plan.missing)].join(', ')}`,
    )
  }
  if (plan.skipped.length) {
    ElMessage.warning(`导入时跳过 ${plan.skipped.length} 项：${plan.skipped.slice(0, 3).join('；')}`)
  }
}

// ---- 项目与文档 --------------------------------------------------------

function fileErrors(data) {
  const errors = data && Array.isArray(data.errors) ? data.errors.filter(Boolean) : []
  return errors.join('；') || '接口返回失败'
}

async function loadProject() {
  try {
    const data = await fetchProject()
    if (data.ok === false) throw new Error(fileErrors(data))
    project.value = { root: data.root, name: data.name, launcher: data.launcher }
    if (data.skipped?.length) ElMessage.warning(`有 ${data.skipped.length} 个插件未能加载`)
  } catch (err) {
    project.value = null
    ElMessage.error(`读取项目失败：${err.message}`)
  }
}

async function confirmDiscard() {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('当前流程图有未保存的修改，继续会丢失这些修改。', '未保存的修改', {
      type: 'warning',
      confirmButtonText: '继续',
      cancelButtonText: '取消',
    })
    return true
  } catch {
    return false
  }
}

/** 为多标签预留：切走前把当前画布快照进 doc（当前只允许一个文档，旧 doc 随后会被替换）。 */
function snapshotActiveDoc() {
  const doc = activeDoc.value
  if (!doc || doc.kind !== 'flow') return
  doc.workflow = buildWorkflow()
}

async function openDocument(rawPath) {
  const path = normalizePath(rawPath)
  if (!path || activeDoc.value?.path === path) return
  if (!(await confirmDiscard())) return
  snapshotActiveDoc()
  await stopDebug()

  let file
  try {
    file = await fetchFile(path)
    if (file.ok === false) throw new Error(fileErrors(file))
  } catch (err) {
    ElMessage.error(`打开失败：${err.message}`)
    return
  }

  if (isFlowPath(path)) {
    if (file.kind !== 'text') {
      ElMessage.error(file.kind === 'too_large' ? '文件太大，无法打开。' : '不是文本文件。')
      return
    }
    try {
      applyWorkflow(JSON.parse(file.text))
    } catch (err) {
      ElMessage.error(`打开失败：${err.message}`)
      return
    }
    const doc = { id: path, path, title: titleFromPath(path), kind: 'flow', savedSignature: '' }
    docs.value = [doc]
    activeId.value = path
    await nextTick()
    // 复用同 id 的 Vue Flow 节点对象时旧的 selected 会残留，显式清一次
    graphRef.value?.clearSelection?.()
    // 新节点要等 ResizeObserver 量出尺寸；等两帧再 fitView，否则 0×0 会 no-op
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    graphRef.value?.fitView?.({ padding: 0.2 })
    doc.savedSignature = contentSignature.value
    return
  }

  docs.value = [{
    id: path,
    path,
    title: titleFromPath(path),
    kind: 'text',
    text: file.text,
    fileKind: file.kind,
    size: file.size,
  }]
  activeId.value = path
}

async function saveDocument() {
  const doc = activeDoc.value
  if (!doc || doc.kind !== 'flow' || saving.value) return
  const problem = envError(workflowEnv.value)
  if (problem) {
    ElMessage.error(problem)
    return
  }
  saving.value = true
  try {
    const text = `${JSON.stringify(buildWorkflow(), null, 2)}\n`
    const data = await writeFile(doc.path, text)
    if (data.ok === false) throw new Error(fileErrors(data))
    doc.savedSignature = contentSignature.value
    ElMessage.success(`已保存 ${doc.title}`)
  } catch (err) {
    ElMessage.error(`保存失败：${err.message}`)
  } finally {
    saving.value = false
  }
}

async function closeProject() {
  if (!project.value) return
  if (!(await confirmDiscard())) return
  const launcher = project.value.launcher
  if (!launcher) {
    ElMessage.warning('当前项目没有 launcher 地址，无法关闭。')
    return
  }
  const sep = launcher.includes('?') ? '&' : '?'
  window.location.href = `${launcher}${sep}close=${encodeURIComponent(project.value.root)}`
}

function openLauncher() {
  if (project.value?.launcher) window.open(project.value.launcher, '_blank')
}

function onPathRenamed({ from, to }) {
  const doc = activeDoc.value
  if (!doc) return
  const oldPath = normalizePath(from)
  const newPath = normalizePath(to)
  let next = ''
  if (doc.path === oldPath) next = newPath
  else if (doc.path.startsWith(`${oldPath}/`)) next = `${newPath}${doc.path.slice(oldPath.length)}`
  if (!next) return
  doc.path = next
  doc.id = next
  doc.title = titleFromPath(next)
  activeId.value = next
}

function resetCanvas() {
  nodes.value = []
  edges.value = []
  canvasEdges.value = []
  groups.value = []
  selectedIds.value = []
  workflowName.value = '未命名工作流'
  workflowEnv.value = []
  additionState.value = null
  validateReport.value = null
  runResult.value = null
  activeTab.value = 'validate'
}

function onPathDeleted(path) {
  const doc = activeDoc.value
  if (!doc || doc.path !== normalizePath(path)) return
  void stopDebug()
  resetCanvas()
  docs.value = []
  activeId.value = null
}

function onBeforeUnload(event) {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

function onWindowKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 's') {
    event.preventDefault()
    void saveDocument()
  }
}

// ---- 工具栏动作 --------------------------------------------------------

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

// ---- 调试会话 ----------------------------------------------------------

function onDebugState(state) {
  debugView.value = applyState(debugView.value, state)
  refreshDebugNodes()
}

function onDebugLog(message) {
  debugLogs.value = appendLog(debugLogs.value, message)
}

function onDebugError(message) {
  debugError.value = typeof message?.message === 'string' ? message.message : '调试出错'
}

// inspect 详情：一次只挂一条，回包按节点 id 对上才 resolve；20 秒没回就 reject
let inspectPending = null

// 唯一结算点：摘 pending、清定时器，再 resolve/reject
function finishInspect(error, data) {
  const pending = inspectPending
  if (!pending) return
  inspectPending = null
  clearTimeout(pending.timer)
  if (error) pending.reject(error)
  else pending.resolve(data)
}

function onDebugInspect(data) {
  if (data?.node === inspectPending?.id) finishInspect(null, data)
}

function inspectNode(id) {
  if (!debugClient) return Promise.reject(new Error('调试连接已断开'))
  return new Promise((resolve, reject) => {
    finishInspect(new Error('已发起新的详情请求'))
    const timer = setTimeout(() => finishInspect(new Error('没拿到详情')), 20000)
    inspectPending = { id, timer, resolve, reject }
    if (!debugClient.send({ cmd: 'inspect', id })) finishInspect(new Error('调试连接已断开'))
  })
}

function onDebugClose() {
  if (!debugActive.value) return
  finishInspect(new Error('调试进程已退出'))
  ElMessage.warning('调试进程已退出')
  void stopDebug()
}

async function startDebug() {
  if (debugStarting.value || debugActive.value) return
  debugStarting.value = true
  let started = null
  try {
    started = await startDebugSession(buildWorkflow())
    // Studio 启动失败是 200 + ok:false，errors 里带原因和子进程 stderr 尾部，原样透给用户
    if (started?.ok === false || !started?.session || !started?.port || !started?.token) {
      const detail = Array.isArray(started?.errors) && started.errors.length
        ? started.errors.join('；')
        : '调试服务返回的会话信息不完整'
      throw new Error(detail)
    }
    const client = new DebugClient({
      port: started.port,
      token: started.token,
      handlers: {
        onState: onDebugState,
        onLog: onDebugLog,
        onError: onDebugError,
        onInspect: onDebugInspect,
        onClose: onDebugClose,
      },
    })
    debugClient = client
    await client.connect()
    debugSession.value = started
    debugView.value = EMPTY_VIEW
    debugLogs.value = []
    debugError.value = ''
    refreshDebugNodes()
    // 调试面板就在底部 dock 里：展开并切到调试页签
    layout.value.bottomOpen = true
    activeTab.value = 'debug'
    saveLayout()
    client.send({ cmd: 'state' })
  } catch (err) {
    debugClient?.close()
    debugClient = null
    debugSession.value = null
    debugView.value = EMPTY_VIEW
    refreshDebugNodes()
    if (started?.session) {
      await stopDebugSession(started.session).catch(() => {})
    }
    ElMessage.error(`启动调试失败：${err.message}`)
  } finally {
    debugStarting.value = false
  }
}

async function stopDebug() {
  const info = debugSession.value
  finishInspect(new Error('调试连接已断开'))
  debugClient?.close()
  debugClient = null
  debugSession.value = null
  debugView.value = EMPTY_VIEW
  debugLogs.value = []
  debugError.value = ''
  refreshDebugNodes()
  // 停在调试页签时退回运行结果；在别的页签就不打扰。放在 await 之前，避免收子进程期间用户切页签被覆盖
  if (activeTab.value === 'debug') activeTab.value = 'run'
  if (info?.session) {
    try {
      await stopDebugSession(info.session)
    } catch {
      // 子进程可能已经自己退了
    }
  }
}

async function toggleDebug() {
  if (debugStarting.value) return
  if (debugActive.value) await stopDebug()
  else await startDebug()
}

function sendDebugCommand(cmd) {
  if (!debugClient || debugBusy.value) return
  debugError.value = ''
  if (!debugClient.send(cmd)) {
    ElMessage.warning('调试连接已断开')
  }
}

function runDebugNode(nodeId) {
  const node = nodes.value.find((item) => item.id === nodeId)
  if (!node) return
  sendDebugCommand({ cmd: 'run_node', id: nodeId, config: node.data.config || {} })
}

function continueDebug() {
  sendDebugCommand({ cmd: 'continue' })
}

function stopDebugExecution() {
  debugClient?.send({ cmd: 'stop' })
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
  window.addEventListener('beforeunload', onBeforeUnload)
  window.addEventListener('keydown', onWindowKeydown)
  await Promise.all([loadProject(), loadPlugins(), checkHealth()])
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  window.removeEventListener('keydown', onWindowKeydown)
})
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">工作流编辑器</div>

      <div v-if="project" class="project-chip" :title="project.root">{{ project.name }}</div>

      <div class="doc-title" :title="activeDoc ? activeDoc.path : ''">
        <span v-if="dirty" class="dirty-dot" title="有未保存的修改">●</span>
        {{ activeDoc ? activeDoc.title : '未打开文件' }}
      </div>

      <el-button
        size="small"
        :loading="saving"
        :disabled="!activeDoc || activeDoc.kind !== 'flow' || !dirty"
        @click="saveDocument"
      >
        保存
      </el-button>

      <el-button
        size="small"
        type="primary"
        plain
        :loading="validating"
        :disabled="running || !activeDoc || activeDoc.kind !== 'flow'"
        @click="doValidate"
      >
        校验
      </el-button>
      <el-button
        size="small"
        type="primary"
        :loading="running"
        :disabled="validating || !activeDoc || activeDoc.kind !== 'flow'"
        @click="doRun"
      >
        运行
      </el-button>
      <el-button size="small" @click="envDrawerVisible = true">环境变量</el-button>
      <el-button
        size="small"
        :type="debugActive ? 'danger' : 'primary'"
        plain
        :loading="debugStarting"
        :disabled="running || validating || !activeDoc || activeDoc.kind !== 'flow'"
        @click="toggleDebug"
      >
        {{ debugActive ? '结束调试' : '调试' }}
      </el-button>

      <div class="spacer"></div>

      <el-button size="small" :disabled="!project || !project.launcher" @click="openLauncher">
        项目列表
      </el-button>
      <el-button size="small" :disabled="!project" @click="closeProject">关闭项目</el-button>

      <el-tag
        size="small"
        effect="plain"
        class="health"
        :type="serverOnline === null ? 'info' : serverOnline ? 'success' : 'danger'"
        @click="checkHealth"
      >
        {{ serverOnline === null ? '检测后端…' : serverOnline ? '后端在线' : '后端未连接' }}
      </el-tag>
    </header>

    <main class="main">
      <ActivityBar v-model:active="leftView" />

      <template v-if="layout.leftOpen">
        <Palette
          v-if="leftView === 'components'"
          :plugins="plugins"
          :style="{ width: layout.leftWidth + 'px' }"
          @add="addNode"
          @collapse="togglePanel('left')"
        />
        <ProjectPanel
          v-else
          :project="project"
          :style="{ width: layout.leftWidth + 'px' }"
          @open="openDocument"
          @collapse="togglePanel('left')"
          @renamed="onPathRenamed"
          @deleted="onPathDeleted"
        />
        <div
          class="resize-handle resize-vertical"
          title="拖拽调整左栏宽度"
          @pointerdown="startResize('left', $event)"
        />
      </template>
      <CollapsedRail
        v-else
        side="left"
        :label="leftView === 'components' ? '组件库' : '资源管理器'"
        @expand="togglePanel('left')"
      />

      <GraphCanvas
        v-if="activeDoc && activeDoc.kind === 'flow'"
        ref="graphRef"
        v-model:nodes="nodes"
        :edges="canvasEdges"
        class="canvas"
        :node-types="nodeTypes"
        @connect="onConnect"
        @drop-component="addNode"
        @remove-edges="onEdgesRemoved"
        @selection-change="onSelectionChange"
        @copy="copySelection"
        @paste="pasteClipboard"
        @context-menu="onCanvasContextMenu"
      />
      <TextViewer v-else-if="activeDoc" :doc="activeDoc" class="canvas" />
      <div v-else class="canvas empty-doc">
        <p>从左侧资源管理器打开一个 <code>.flow</code> 文件</p>
        <p class="muted small">右键目录可以新建流程图。</p>
      </div>

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
    <BottomDock
      v-if="layout.bottomOpen"
      v-model:active-tab="activeTab"
      :report="validateReport"
      :run="runResult"
      :debug-active="debugActive"
      :debug-view="debugView"
      :debug-logs="debugLogs"
      :debug-error="debugError"
      :inspect="inspectNode"
      :style="{ height: layout.bottomHeight + 'px' }"
      @collapse="togglePanel('bottom')"
      @debug-continue="continueDebug"
      @debug-stop="stopDebugExecution"
    />
    <CollapsedRail
      v-else
      side="bottom"
      label="运行与调试"
      @expand="togglePanel('bottom')"
    />

    <EnvDrawer v-model:visible="envDrawerVisible" v-model:rows="workflowEnv" />

    <ContextMenu
      v-if="contextMenu"
      :key="contextMenu.id"
      :x="contextMenu.x"
      :y="contextMenu.y"
      :items="contextMenu.items"
      @select="onMenuSelect"
      @close="contextMenu = null"
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

.project-chip {
  flex: none;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-2);
  font-size: 12px;
}

.doc-title {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.dirty-dot {
  flex: none;
  color: var(--warning);
  font-size: 12px;
}

.empty-doc {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: var(--text-2);
  background: var(--bg);
}

.empty-doc p {
  margin: 0;
}

.empty-doc code {
  padding: 0 3px;
  border-radius: 3px;
  background: #eef1f6;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
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
