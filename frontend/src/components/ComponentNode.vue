<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { nodeStatusClass } from '../debug/model.js'
import ConfigForm from './ConfigForm.vue'

const props = defineProps({
  id: { type: String, default: '' },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const rowCount = computed(() =>
  Math.max(props.data.inPorts?.length || 0, props.data.outPorts?.length || 0),
)

const paramCount = computed(() => Object.keys(props.data.config_schema || {}).length)

// 标题行是拖动把子：pointerdown 记起点，click 里位移超过 3px 就当成拖动、不切参数。
let pressStart = null

function onTitlePress(event) {
  pressStart = { x: event.clientX, y: event.clientY }
}

function onTitleClick(event) {
  const start = pressStart
  pressStart = null
  if (start && event.detail > 0) {
    const dx = event.clientX - start.x
    const dy = event.clientY - start.y
    if (dx * dx + dy * dy > 9) return
  }
  props.data.paramsOpen = !props.data.paramsOpen
}
</script>

<template>
  <div
    class="cnode"
    :class="[
      nodeStatusClass(data.debugStatus),
      { selected, failed: data.failed && !data.debugStatus, missing: data.missing },
    ]"
  >
    <div class="cnode-head">
      <div class="cnode-head-text">
        <div class="cnode-title-line">
          <button
            class="cnode-title-row nopan"
            type="button"
            :aria-expanded="data.paramsOpen"
            :disabled="data.missing"
            @pointerdown="onTitlePress"
            @click.stop="onTitleClick"
          >
            <span v-if="!data.missing" class="cnode-chevron">
              {{ data.paramsOpen ? '▾' : '▸' }}
            </span>
            <span class="cnode-title" :title="data.title">{{ data.title }}</span>
            <span v-if="paramCount" class="cnode-count">{{ paramCount }} 项</span>
          </button>
          <button
            v-if="data.desc && !data.missing"
            class="cnode-info nodrag nopan"
            :class="{ active: data.descOpen }"
            type="button"
            title="组件简介"
            aria-label="组件简介"
            :aria-expanded="Boolean(data.descOpen)"
            @pointerdown.stop
            @click.stop="data.descOpen = !data.descOpen"
          >
            ⓘ
          </button>
        </div>
        <div v-if="!data.missing" class="cnode-meta">{{ data.plugin }}.{{ data.component }}</div>
        <div v-if="data.descOpen && data.desc" class="cnode-desc">{{ data.desc }}</div>
      </div>
      <button
        v-if="data.debugStatus && !data.missing"
        class="cnode-run nodrag nopan"
        type="button"
        title="运行此节点"
        aria-label="运行此节点"
        :disabled="!data.debugCanRun"
        @pointerdown.stop
        @click.stop="data.onDebugRun?.(id)"
      >
        ▶
      </button>
      <button
        class="cnode-delete nodrag nopan"
        type="button"
        title="删除节点"
        aria-label="删除节点"
        @pointerdown.stop
        @click.stop="data.onDelete(id)"
      >
        ×
      </button>
    </div>

    <div class="cnode-body">
      <div class="cnode-ports">
        <div v-for="i in rowCount" :key="i" class="cnode-row">
          <div class="cnode-side input">
            <template v-if="data.inPorts[i - 1]">
              <Handle
                :id="data.inPorts[i - 1].name"
                type="target"
                :position="Position.Left"
                class="cnode-handle"
                :style="{
                  background: data.inPorts[i - 1].color,
                  left: '-15px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                }"
              />
              <span class="cnode-port">{{ data.inPorts[i - 1].name }}</span>
              <span
                class="cnode-type"
                :style="{ color: data.inPorts[i - 1].color }"
                :title="data.inPorts[i - 1].full"
              >
                {{ data.inPorts[i - 1].short }}
              </span>
            </template>
          </div>

          <div class="cnode-side output">
            <template v-if="data.outPorts[i - 1]">
              <span
                class="cnode-type"
                :style="{ color: data.outPorts[i - 1].color }"
                :title="data.outPorts[i - 1].full"
              >
                {{ data.outPorts[i - 1].short }}
              </span>
              <span class="cnode-port">{{ data.outPorts[i - 1].name }}</span>
              <Handle
                :id="data.outPorts[i - 1].name"
                type="source"
                :position="Position.Right"
                class="cnode-handle"
                :style="{
                  background: data.outPorts[i - 1].color,
                  right: '-15px',
                  left: 'auto',
                  top: '50%',
                  transform: 'translateY(-50%)',
                }"
              />
            </template>
          </div>
        </div>

        <div v-if="rowCount === 0" class="cnode-empty">无输入 / 输出端口</div>
      </div>

      <div v-if="data.missing" class="cnode-empty error">组件未加载</div>
      <div
        v-else-if="data.paramsOpen"
        class="cnode-scroll nodrag nopan nowheel"
        @pointerdown.stop
        @wheel.stop
      >
        <ConfigForm :header="false" :schema="data.config_schema" :config="data.config" />
      </div>
    </div>

    <div v-if="data.failed && !data.debugStatus" class="cnode-fail">运行失败</div>
  </div>
</template>

<style scoped>
.cnode {
  display: flex;
  flex-direction: column;
  width: 280px;
  max-height: 400px;
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  font-size: 12px;
  color: #303133;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
  transition: border-color 0.15s, box-shadow 0.15s;
}

.cnode.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.22);
}

.cnode.failed {
  border-color: var(--danger);
  background: #fff7f7;
}

.cnode.missing {
  border-style: dashed;
  border-color: var(--danger);
}

/* 调试态：节点按运行状态描边（selected 的选中环走 box-shadow，不冲突） */
.cnode.status-unrun {
  border-color: var(--border);
}

.cnode.status-fresh {
  border-color: var(--success);
}

.cnode.status-stale {
  border-color: var(--warning);
}

.cnode.status-failed {
  border-color: var(--danger);
}

.cnode-head {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 6px 8px 5px 10px;
  border-bottom: 1px solid #ebeef5;
  flex: none;
}

.cnode-head-text {
  flex: 1;
  min-width: 0;
}

.cnode-title-line {
  display: flex;
  align-items: center;
  gap: 4px;
}

.cnode-title-row {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  gap: 5px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  line-height: 18px;
  text-align: left;
  cursor: pointer;
}

.cnode-title-row:disabled {
  cursor: default;
}

.cnode-chevron {
  flex: none;
  width: 10px;
  color: var(--muted);
  font-size: 10px;
  line-height: 14px;
  text-align: center;
}

.cnode-title {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cnode-count {
  flex: none;
  color: var(--muted);
  font-size: 10px;
  font-weight: 400;
}

.cnode-info {
  flex: none;
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  line-height: 18px;
  cursor: pointer;
}

.cnode-info:hover,
.cnode-info.active {
  color: var(--primary);
  background: #ecf5ff;
}

.cnode-meta {
  padding-left: 15px;
  color: var(--muted);
  font-size: 11px;
  line-height: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cnode-desc {
  margin-top: 2px;
  padding-left: 15px;
  color: var(--text-2);
  font-size: 11px;
  line-height: 16px;
  word-break: break-word;
}

.cnode-delete,
.cnode-run {
  flex: none;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  line-height: 18px;
  cursor: pointer;
  transition: color 0.12s, background 0.12s;
}

.cnode-delete {
  color: #c0c4cc;
  font-size: 16px;
}

.cnode-delete:hover {
  color: var(--danger);
  background: #fef0f0;
}

.cnode-run {
  color: var(--muted);
  font-size: 10px;
}

.cnode-run:hover:not(:disabled) {
  color: var(--primary);
  background: #ecf5ff;
}

.cnode-run:disabled {
  cursor: default;
  opacity: 0.4;
}

.cnode-body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
  padding: 4px 10px 6px;
}

.cnode-ports {
  flex: none;
}

.cnode-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  height: 24px;
}

.cnode-side {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.cnode-side.output {
  justify-content: flex-end;
}

.cnode-port {
  font-size: 11px;
  color: #606266;
  max-width: 70px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cnode-type {
  font-size: 10px;
  max-width: 74px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cnode-handle {
  width: 10px;
  height: 10px;
  border: 2px solid #fff;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.08);
}

.cnode-scroll {
  min-height: 0;
  overflow: auto;
  margin-top: 4px;
}

.cnode-empty {
  color: var(--muted);
  font-size: 11px;
  text-align: center;
  padding: 4px 0;
}

.cnode-empty.error {
  color: var(--danger);
}

.cnode-fail {
  flex: none;
  border-top: 1px dashed #fbc4c4;
  color: var(--danger);
  font-size: 11px;
  padding: 3px 10px 4px;
}
</style>
