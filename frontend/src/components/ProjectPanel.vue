<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ContextMenu from './ContextMenu.vue'
import { deletePath, fetchTree, makeDir, renamePath, writeFile } from '../api'
import { joinPath, newFlowText, normalizePath, parentPath, titleFromPath } from '../documents'

const props = defineProps({
  project: { type: Object, default: null },
})

const emit = defineEmits(['open', 'collapse', 'renamed', 'deleted'])

const NAME_PATTERN = /^[^\\/:*?"<>|]+$/

const treeRef = ref(null)
const version = ref(0)
const menu = ref(null)
let menuSeq = 0

const rootNodes = computed(() => (props.project
  ? [{ name: props.project.name, path: '', kind: 'dir', isLeaf: false }]
  : []))

watch(
  () => props.project?.root,
  () => {
    version.value += 1
    menu.value = null
  },
)

function failMessage(data) {
  const errors = data && Array.isArray(data.errors) ? data.errors.filter(Boolean) : []
  return errors.join('；') || '操作失败'
}

/** el-tree 懒加载：根节点是项目名，其余按展开时请求一层。 */
async function loadNode(node, resolve) {
  if (node.level === 0) {
    resolve(rootNodes.value)
    return
  }
  try {
    const data = await fetchTree(node.data?.path ?? '')
    if (data.ok === false) throw new Error(failMessage(data))
    resolve(sortEntries(data.entries || []))
  } catch (err) {
    ElMessage.error(`读取目录失败：${err.message}`)
    resolve([])
  }
}

/** 目录在前，同类按名字排；后端顺序不作为契约依赖。 */
function sortEntries(entries) {
  return entries
    .map((entry) => ({ ...entry, isLeaf: entry.kind === 'file' }))
    .sort((left, right) => {
      if (left.kind !== right.kind) return left.kind === 'dir' ? -1 : 1
      return left.name.localeCompare(right.name)
    })
}

function onNodeClick(data, node) {
  if (data.kind === 'file') {
    emit('open', data.path)
    return
  }
  if (node.expanded) node.collapse()
  else node.expand()
}

function onNodeContextMenu(event, data, node) {
  event.preventDefault()
  const items = data.kind === 'dir'
    ? [
        { label: '新建流程图', action: () => createFlow(data, node) },
        { label: '新建文件夹', action: () => createFolder(data, node) },
        { label: '刷新', action: () => refreshNode(node) },
      ]
    : [
        { label: '重命名', action: () => renameEntry(data, node) },
        { label: '删除', danger: true, action: () => removeEntry(data, node) },
        { label: '刷新', action: () => refreshNode(node) },
      ]
  menu.value = { id: ++menuSeq, x: event.clientX, y: event.clientY, items }
}

function onMenuSelect(item) {
  menu.value = null
  item.action()
}

function refreshNode(node) {
  if (!node) {
    version.value += 1
    return
  }
  node.loaded = false
  node.expand()
}

async function promptName(title, value) {
  const result = await ElMessageBox.prompt('名称', title, {
    inputValue: value,
    inputValidator: (input) => {
      const text = String(input || '').trim()
      if (!text) return '名称不能为空'
      if (text === '.' || text === '..') return '名称不能是 . 或 ..'
      if (!NAME_PATTERN.test(text)) return '名称不能包含 \\ / : * ? " < > |'
      return true
    },
    confirmButtonText: '确定',
    cancelButtonText: '取消',
  })
  return String(result.value || '').trim()
}

/** 目标目录下有没有同名条目：新建前先查一次，别让 /api/file 静默覆盖没展开的旧文件。 */
async function nameTaken(dirPath, name) {
  const data = await fetchTree(dirPath)
  if (data.ok === false) throw new Error(failMessage(data))
  const lower = name.toLowerCase()
  return (data.entries || []).some((entry) => entry.name.toLowerCase() === lower)
}

async function createFlow(dir, node) {
  let name
  try {
    name = await promptName('新建流程图', '未命名.flow')
  } catch {
    return
  }
  if (!name) return
  if (!name.toLowerCase().endsWith('.flow')) name += '.flow'
  const path = joinPath(dir.path, name)
  try {
    if (await nameTaken(dir.path, name)) {
      ElMessage.error(`已存在同名文件：${name}`)
      return
    }
    const data = await writeFile(path, newFlowText(titleFromPath(path)))
    if (data.ok === false) throw new Error(failMessage(data))
    refreshNode(node)
    emit('open', path)
  } catch (err) {
    ElMessage.error(`新建流程图失败：${err.message}`)
  }
}

async function createFolder(dir, node) {
  let name
  try {
    name = await promptName('新建文件夹', '新建文件夹')
  } catch {
    return
  }
  if (!name) return
  try {
    if (await nameTaken(dir.path, name)) {
      ElMessage.error(`已存在同名文件夹：${name}`)
      return
    }
    const data = await makeDir(joinPath(dir.path, name))
    if (data.ok === false) throw new Error(failMessage(data))
    refreshNode(node)
  } catch (err) {
    ElMessage.error(`新建文件夹失败：${err.message}`)
  }
}

async function renameEntry(entry, node) {
  let name
  try {
    name = await promptName('重命名', entry.name)
  } catch {
    return
  }
  if (!name || name === entry.name) return
  try {
    const data = await renamePath(entry.path, name)
    if (data.ok === false) throw new Error(failMessage(data))
    const to = normalizePath(data.path || joinPath(parentPath(entry.path), name))
    refreshNode(node.parent)
    emit('renamed', { from: entry.path, to })
  } catch (err) {
    ElMessage.error(`重命名失败：${err.message}`)
  }
}

async function removeEntry(entry, node) {
  try {
    await ElMessageBox.confirm(`删除「${entry.name}」？`, '删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const data = await deletePath(entry.path)
    if (data.ok === false) throw new Error(failMessage(data))
    refreshNode(node.parent)
    emit('deleted', entry.path)
  } catch (err) {
    ElMessage.error(`删除失败：${err.message}`)
  }
}
</script>

<template>
  <aside class="project-panel">
    <div class="panel-title">
      <span class="panel-name" :title="project ? project.root : ''">
        {{ project ? project.name : '资源管理器' }}
      </span>
      <button
        class="panel-collapse"
        type="button"
        title="收起左栏"
        aria-label="收起左栏"
        @click="emit('collapse')"
      >
        ◀
      </button>
    </div>

    <div v-if="!project" class="panel-empty">没有绑定项目。请从项目列表打开一个项目。</div>
    <el-tree
      v-else
      :key="version"
      ref="treeRef"
      class="project-tree"
      :props="{ label: 'name', isLeaf: 'isLeaf' }"
      :load="loadNode"
      node-key="path"
      lazy
      highlight-current
      :expand-on-click-node="false"
      @node-click="onNodeClick"
      @node-contextmenu="onNodeContextMenu"
    >
      <template #default="{ data }">
        <span class="tree-row">
          <span class="tree-name">{{ data.name }}</span>
          <span v-if="data.kind === 'file' && /\.zip$/i.test(data.name)" class="tree-tag">插件</span>
        </span>
      </template>
    </el-tree>

    <ContextMenu
      v-if="menu"
      :key="menu.id"
      :x="menu.x"
      :y="menu.y"
      :items="menu.items"
      @select="onMenuSelect"
      @close="menu = null"
    />
  </aside>
</template>

<style scoped>
.project-panel {
  display: flex;
  flex-direction: column;
  flex: none;
  min-height: 0;
  background: var(--panel);
  border-right: 1px solid var(--border);
}

.panel-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-empty {
  padding: 16px 14px;
  color: var(--muted);
  font-size: 12px;
  line-height: 19px;
}

.project-tree {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 4px 0 12px;
  background: transparent;
  font-size: 12px;
}

.project-tree :deep(.el-tree-node__content) {
  height: 26px;
}

.tree-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.tree-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-tag {
  flex: none;
  padding: 0 5px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--muted);
  font-size: 10px;
  line-height: 14px;
}
</style>
