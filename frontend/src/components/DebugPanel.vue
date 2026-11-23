<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { isBusy, phaseLabel, statusLabel } from '../debug/model.js'
import { trackPointer } from '../pointer.js'

const props = defineProps({
  view: { type: Object, required: true },
  logs: { type: Array, default: () => [] },
  error: { type: String, default: '' },
  inspect: { type: Function, required: true },
  active: { type: Boolean, default: true },
})

const emit = defineEmits(['continue', 'stop'])

const box = ref(null)
// 贴底才自动滚；用户往上翻了就由用户自己控制
let stick = true

function onScroll() {
  const el = box.value
  if (!el) return
  stick = el.scrollHeight - el.scrollTop - el.clientHeight <= 24
}

// 日志换了新数组就滚：贴底才跟，用户往上翻了就不抢；清空（新会话）时恢复贴底
watch(
  () => props.logs,
  () => {
    if (!props.logs.length) stick = true
    else if (stick) stickToEnd()
  },
  { flush: 'post' },
)

// 页签切回来 / dock 重新展开时补一次贴底：隐藏期间 scrollHeight 为 0，位置会丢
function stickToEnd() {
  stick = true
  const el = box.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(() => props.active, (active) => active && stickToEnd(), { flush: 'post' })
onMounted(stickToEnd)

// ---- 左右分栏：拖动改比例、双击回默认，比例存 localStorage ----
const SPLIT_KEY = 'workflow-studio.debugSplit'
const DEFAULT_SPLIT = 0.3
const MIN_SIDE = 180

const body = ref(null)
const split = ref(readSplit())

function readSplit() {
  try {
    const saved = Number(localStorage.getItem(SPLIT_KEY))
    return Number.isFinite(saved) && saved > 0 && saved < 1 ? saved : DEFAULT_SPLIT
  } catch {
    return DEFAULT_SPLIT
  }
}

function saveSplit() {
  try {
    localStorage.setItem(SPLIT_KEY, String(split.value))
  } catch {
    // 存不了只影响下次打开，不影响当前布局
  }
}

function startSplit(event) {
  event.preventDefault()
  const rect = body.value?.getBoundingClientRect()
  if (!rect?.width) return
  const min = Math.min(MIN_SIDE / rect.width, 0.5)
  const max = Math.max(1 - MIN_SIDE / rect.width, 0.5)
  trackPointer((moveEvent) => {
    const ratio = (moveEvent.clientX - rect.left) / rect.width
    split.value = Math.min(max, Math.max(min, ratio))
  }, saveSplit)
}

function resetSplit() {
  split.value = DEFAULT_SPLIT
  saveSplit()
}

// ---- 节点详情弹窗 ----
const detail = ref(null)
let detailSeq = 0

async function openDetail(id) {
  const seq = ++detailSeq
  detail.value = { id, loading: true, error: '', data: null }
  const entry = detail.value
  try {
    entry.data = await props.inspect(id)
  } catch (err) {
    entry.error = err?.message || '没拿到详情'
  }
  if (seq !== detailSeq) return
  entry.loading = false
}

function closeDetail() {
  detail.value = null
}

function toPorts(value) {
  if (!value || typeof value !== 'object') return []
  return Object.entries(value).map(([name, text]) => ({ name, text: String(text ?? '') }))
}

const sections = computed(() => {
  const data = detail.value?.data
  if (!data) return []
  return [
    { key: 'inputs', label: '输入', ports: toPorts(data.inputs) },
    { key: 'outputs', label: '输出', ports: toPorts(data.outputs) },
  ].filter((section) => section.ports.length)
})

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // 剪贴板不可用就静默
  }
}
</script>

<template>
  <section class="debug-panel">
    <div class="debug-head">
      <span class="debug-phase" :class="`phase-${view.phase}`">
        {{ phaseLabel(view.phase) }}
      </span>
      <span v-if="view.current" class="debug-current">当前 {{ view.current }}</span>
      <span class="debug-spacer"></span>
      <el-button
        size="small"
        :disabled="isBusy(view.phase)"
        @click="emit('continue')"
      >
        继续
      </el-button>
      <el-button size="small" :disabled="!isBusy(view.phase)" @click="emit('stop')">
        停止
      </el-button>
    </div>

    <div v-if="error" class="debug-error">{{ error }}</div>

    <div ref="body" class="debug-body">
      <div class="debug-nodes" :style="{ width: `${split * 100}%` }">
        <div v-if="!Object.keys(view.nodes).length" class="debug-empty">等待结果中</div>
        <div v-for="(info, id) in view.nodes" :key="id" class="dbg-node">
          <div class="dbg-node-head">
            <span class="dbg-node-id">{{ id }}</span>
            <span class="dbg-node-status" :class="`is-${info.status}`">
              {{ statusLabel(info.status) }}
            </span>
            <span v-if="info.duration_ms !== null" class="dbg-node-ms">
              {{ info.duration_ms }} ms
            </span>
            <button class="dbg-detail" type="button" @click="openDetail(id)">⤢ 查看</button>
          </div>
          <div v-if="info.error" class="dbg-node-error" :title="info.error">{{ info.error }}</div>
          <div v-for="(text, port) in info.outputs" :key="port" class="dbg-out">
            <span class="dbg-port">{{ port }}</span>
            <span class="dbg-preview" :title="text">{{ text }}</span>
          </div>
        </div>
      </div>

      <div
        class="debug-split"
        title="拖动调整宽度，双击回默认"
        @pointerdown="startSplit"
        @dblclick="resetSplit"
      ></div>

      <div ref="box" class="debug-log" @scroll.passive="onScroll">
        <div
          v-for="(line, index) in logs"
          :key="index"
          class="log-line"
          :class="line.stream === 'stderr' ? 'is-stderr' : 'is-stdout'"
        >
          <span v-if="line.node" class="log-node">[{{ line.node }}]</span>{{ line.text }}
        </div>
        <div v-if="!logs.length" class="debug-empty">等待日志…</div>
      </div>
    </div>

    <el-dialog
      :model-value="Boolean(detail)"
      :title="detail ? `节点 ${detail.id}` : ''"
      width="min(720px, 92vw)"
      @closed="closeDetail"
    >
      <template v-if="detail">
        <div v-if="detail.loading" class="dbg-modal-tip">加载中…</div>
        <div v-else-if="detail.error" class="dbg-modal-tip is-error">{{ detail.error }}</div>
        <div v-else-if="!sections.length" class="dbg-modal-tip">该节点还没有结果（先执行它）</div>
        <template v-else>
          <section v-for="section in sections" :key="section.key" class="dbg-section">
            <div class="dbg-section-title">{{ section.label }}</div>
            <div v-for="port in section.ports" :key="port.name" class="dbg-port-block">
              <div class="dbg-port-head">
                <span class="dbg-port-name">{{ port.name }}</span>
                <button class="dbg-copy" type="button" @click="copyText(port.text)">复制</button>
              </div>
              <pre class="dbg-port-text">{{ port.text }}</pre>
            </div>
          </section>
        </template>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.debug-panel {
  position: relative;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.debug-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 12px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}

.debug-phase {
  font-weight: 600;
  color: var(--muted);
}

.debug-phase.phase-running {
  color: var(--primary);
}

.debug-phase.phase-paused {
  color: var(--warning);
}

.debug-phase.phase-failed {
  color: var(--danger);
}

.debug-current {
  color: var(--text-2);
  font-family: Consolas, 'Courier New', monospace;
}

.debug-spacer {
  flex: 1;
}

.debug-head :deep(.el-button + .el-button) {
  margin-left: 0;
}

.debug-error {
  flex: none;
  padding: 4px 12px;
  background: rgba(245, 108, 108, 0.08);
  color: var(--danger);
  font-size: 12px;
  line-height: 18px;
  border-bottom: 1px solid var(--border);
}

.debug-body {
  flex: 1;
  min-height: 0;
  display: flex;
}

/* 节点结果：左列自己滚，端口预览单行省略，长文本靠 title 看全；宽度由拖动比例给 */
.debug-nodes {
  flex: 0 0 auto;
  min-width: 180px;
  max-width: calc(100% - 180px);
  min-height: 0;
  overflow: auto;
  padding: 6px 10px 8px;
}

.debug-split {
  flex: none;
  width: 6px;
  border-left: 1px solid var(--border);
  cursor: col-resize;
  touch-action: none;
}

.debug-split:hover {
  background: rgba(64, 158, 255, 0.25);
}

.dbg-node + .dbg-node {
  margin-top: 6px;
}

.dbg-node-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  line-height: 16px;
}

.dbg-detail {
  flex: none;
  margin-left: auto;
  padding: 0 4px;
  border: none;
  border-radius: 3px;
  background: transparent;
  color: var(--muted);
  font-family: inherit;
  font-size: 11px;
  line-height: 16px;
  cursor: pointer;
}

.dbg-detail:hover {
  color: var(--primary);
  background: #ecf5ff;
}

.dbg-node-id {
  font-family: Consolas, 'Courier New', monospace;
  font-weight: 600;
  color: var(--text);
}

.dbg-node-status {
  color: var(--muted);
}

.dbg-node-status.is-fresh {
  color: var(--success);
}

.dbg-node-status.is-stale {
  color: var(--warning);
}

.dbg-node-status.is-failed {
  color: var(--danger);
}

.dbg-node-ms {
  color: var(--muted);
}

.dbg-node-error {
  color: var(--danger);
  font-size: 11px;
  line-height: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dbg-out {
  display: flex;
  gap: 6px;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 11px;
  line-height: 16px;
}

.dbg-port {
  flex: none;
  color: var(--muted);
}

.dbg-preview {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.debug-log {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: 6px 12px 10px;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 11px;
  line-height: 16px;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.log-line.is-stderr {
  color: var(--danger);
}

.log-node {
  margin-right: 4px;
  color: var(--muted);
}

.debug-empty {
  color: var(--muted);
  font-family: inherit;
}

/* 详情弹窗：外框交给 el-dialog；端口多时在弹窗内滚，别让整页跟着滚（单个端口 pre 仍 220px 内部滚动） */
:deep(.el-dialog__body) {
  max-height: 70vh;
  overflow: auto;
}

.dbg-modal-tip {
  padding: 6px 0;
  color: var(--muted);
  font-size: 12px;
}

.dbg-modal-tip.is-error {
  color: var(--danger);
}

.dbg-section + .dbg-section {
  margin-top: 12px;
}

.dbg-section-title {
  margin-bottom: 4px;
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
}

.dbg-port-block + .dbg-port-block {
  margin-top: 8px;
}

.dbg-port-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dbg-port-name {
  flex: 1;
  color: var(--text-2);
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
}

.dbg-copy {
  flex: none;
  padding: 0 6px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: #fff;
  color: var(--muted);
  font-family: inherit;
  font-size: 11px;
  line-height: 18px;
  cursor: pointer;
}

.dbg-copy:hover {
  color: var(--primary);
  border-color: var(--primary);
}

/* 全文可能到 16 KiB：固定最大高度 + 内部滚动，不撑爆弹窗 */
.dbg-port-text {
  margin: 4px 0 0;
  max-height: 220px;
  overflow: auto;
  padding: 6px 8px;
  background: #f7f8fa;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-2);
  font-family: Consolas, 'Courier New', monospace;
  font-size: 11px;
  line-height: 16px;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
