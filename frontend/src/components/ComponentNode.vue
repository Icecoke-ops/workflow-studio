<script setup>
import { computed } from 'vue'
import { Handle, Position, useVueFlow } from '@vue-flow/core'
import ConfigForm from './ConfigForm.vue'

const props = defineProps({
  id: { type: String, default: '' },
  data: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const { removeNodes } = useVueFlow()

const rowCount = computed(() =>
  Math.max(props.data.inPorts?.length || 0, props.data.outPorts?.length || 0),
)

function toggleSection(key) {
  props.data[key] = !props.data[key]
}
</script>

<template>
  <div class="cnode" :class="{ selected, failed: data.failed, missing: data.missing }">
    <div class="cnode-head">
      <div class="cnode-head-text">
        <div class="cnode-title" :title="data.desc || data.title">{{ data.title }}</div>
        <div class="cnode-meta">{{ data.plugin }}.{{ data.component }}</div>
      </div>
      <button
        class="cnode-delete nodrag nopan"
        type="button"
        title="删除节点"
        aria-label="删除节点"
        @pointerdown.stop
        @click.stop="removeNodes([id])"
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
        v-else
        class="cnode-scroll nodrag nopan nowheel"
        @pointerdown.stop
        @wheel.stop
      >
        <div class="cnode-section">
          <button
            class="collapse-toggle nodrag nopan"
            type="button"
            @pointerdown.stop
            @click.stop="toggleSection('descOpen')"
          >
            <span class="collapse-chevron">{{ data.descOpen ? '▾' : '▸' }}</span>
            <span>组件介绍</span>
          </button>
          <div v-if="data.descOpen" class="cnode-section-body">
            <div v-if="data.desc">{{ data.desc }}</div>
            <div v-else class="muted">（无介绍）</div>
            <div
              v-if="data.pluginTitle && data.pluginTitle !== data.title"
              class="cnode-plugin-title"
            >
              所属插件：{{ data.pluginTitle }}
            </div>
          </div>
        </div>

        <ConfigForm
          v-model:open="data.paramsOpen"
          :schema="data.config_schema"
          :config="data.config"
        />
      </div>
    </div>

    <div v-if="data.failed" class="cnode-fail">运行失败</div>
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

.cnode-title {
  font-weight: 600;
  font-size: 13px;
  line-height: 18px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cnode-meta {
  color: var(--muted);
  font-size: 11px;
  line-height: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cnode-delete {
  flex: none;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #c0c4cc;
  font-size: 16px;
  line-height: 18px;
  cursor: pointer;
  transition: color 0.12s, background 0.12s;
}

.cnode-delete:hover {
  color: var(--danger);
  background: #fef0f0;
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
  padding-top: 2px;
  border-top: 1px solid #f0f2f5;
}

.cnode-section-body {
  padding: 2px 4px 5px 17px;
  color: var(--text-2);
  font-size: 11px;
  line-height: 16px;
  word-break: break-word;
}

.cnode-plugin-title {
  margin-top: 3px;
  color: var(--muted);
  font-size: 10px;
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
