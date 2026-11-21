<script setup>
import { computed, reactive, watch } from 'vue'

const props = defineProps({
  schema: { type: Object, default: () => ({}) },
  config: { type: Object, required: true },
})

const open = defineModel('open', { type: Boolean, default: true })

function toggleOpen() {
  open.value = !open.value
}

const fields = computed(() => Object.entries(props.schema || {}))

const jsonDrafts = reactive({})
const jsonErrors = reactive({})

function toJsonText(value) {
  if (value === undefined) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return ''
  }
}

function hasDefault(spec) {
  return Boolean(spec) && Object.prototype.hasOwnProperty.call(spec, 'default')
}

function formatDefault(spec) {
  if (!hasDefault(spec)) return ''
  const value = spec.default
  try {
    const text = JSON.stringify(value)
    return text === undefined ? String(value) : text
  } catch {
    return String(value)
  }
}

function choicesFor(spec) {
  return (spec.choices || []).map((item) => {
    if (item && typeof item === 'object') {
      return { value: item.value, label: item.label ?? String(item.value) }
    }
    return { value: item, label: String(item) }
  })
}

function resetDrafts() {
  for (const key of Object.keys(jsonDrafts)) delete jsonDrafts[key]
  for (const key of Object.keys(jsonErrors)) delete jsonErrors[key]
  for (const [name, spec] of Object.entries(props.schema || {})) {
    if (spec?.type === 'json' || spec?.type === 'array') {
      jsonDrafts[name] = toJsonText(props.config?.[name])
    }
  }
}

watch(() => [props.schema, props.config], resetDrafts, { immediate: true })

function setValue(name, value) {
  if (value === undefined || value === null) {
    delete props.config[name]
    return
  }
  props.config[name] = value
}

function onJsonInput(name, text, spec) {
  jsonDrafts[name] = text
  const trimmed = text.trim()
  if (!trimmed) {
    delete props.config[name]
    delete jsonErrors[name]
    return
  }
  try {
    const parsed = JSON.parse(trimmed)
    if (spec.type === 'array' && !Array.isArray(parsed)) throw new Error('需要 JSON 数组')
    if (spec.type === 'json' && (parsed === null || typeof parsed !== 'object')) {
      throw new Error('需要 JSON 对象或数组')
    }
    props.config[name] = parsed
    delete jsonErrors[name]
  } catch (err) {
    jsonErrors[name] = err.message
  }
}
</script>

<template>
  <div class="config-panel">
    <button
      class="collapse-toggle nodrag nopan"
      type="button"
      @pointerdown.stop
      @click.stop="toggleOpen"
    >
      <span class="collapse-chevron">{{ open ? '▾' : '▸' }}</span>
      <span>参数（{{ fields.length }}）</span>
    </button>

    <el-form
      v-if="open"
      label-position="top"
      size="small"
      class="config-form"
      @submit.prevent
    >
      <el-form-item v-for="[name, spec] in fields" :key="name">
        <template #label>
          <span class="field-label">{{ spec.title || name }}</span>
          <span class="field-meta">
            <span v-if="spec.required" class="field-required">必填</span>
            <span class="field-type">{{ spec.type }}</span>
            <span
              v-if="hasDefault(spec)"
              class="field-default"
              :title="formatDefault(spec)"
            >
              默认 {{ formatDefault(spec) }}
            </span>
          </span>
        </template>

        <div v-if="spec.desc" class="field-desc">{{ spec.desc }}</div>

        <el-input
          v-if="spec.type === 'string'"
          :model-value="config[name] ?? ''"
          placeholder="请输入"
          @update:model-value="setValue(name, $event)"
        />

        <el-select
          v-else-if="spec.type === 'enum'"
          :model-value="config[name]"
          placeholder="请选择"
          clearable
          @update:model-value="setValue(name, $event)"
        >
          <el-option
            v-for="option in choicesFor(spec)"
            :key="String(option.value)"
            :label="option.label"
            :value="option.value"
          />
        </el-select>

        <el-input-number
          v-else-if="spec.type === 'integer' || spec.type === 'number'"
          :model-value="config[name]"
          :min="spec.min"
          :max="spec.max"
          :step="spec.step ?? (spec.type === 'integer' ? 1 : 0.1)"
          :step-strictly="spec.type === 'integer'"
          :precision="spec.type === 'integer' ? 0 : undefined"
          controls-position="right"
          class="number-input"
          @update:model-value="setValue(name, $event)"
        />

        <el-switch
          v-else-if="spec.type === 'boolean'"
          :model-value="!!config[name]"
          @update:model-value="setValue(name, $event)"
        />

        <el-input
          v-else-if="spec.type === 'array'"
          :model-value="jsonDrafts[name] ?? ''"
          placeholder="JSON 数组"
          @update:model-value="onJsonInput(name, $event, spec)"
        />

        <el-input
          v-else
          type="textarea"
          :model-value="jsonDrafts[name] ?? ''"
          :rows="3"
          class="json-input"
          placeholder="JSON"
          @update:model-value="onJsonInput(name, $event, spec)"
        />

        <div v-if="jsonErrors[name]" class="json-error">{{ jsonErrors[name] }}</div>
      </el-form-item>

      <div v-if="!fields.length" class="muted small">该组件没有参数</div>
    </el-form>
  </div>
</template>

<style scoped>
.config-panel {
  border-top: 1px dashed #f0f2f5;
  margin-top: 2px;
  padding-top: 2px;
}

.config-form {
  padding: 2px 0 0;
}

.config-form :deep(.el-form-item) {
  margin-bottom: 10px;
}

.config-form :deep(.el-form-item__label) {
  display: flex;
  width: 100%;
  align-items: baseline;
  gap: 6px;
  padding-bottom: 2px;
  line-height: 16px;
}

.field-label {
  font-size: 11px;
  color: var(--text-2);
}

.field-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: flex-end;
  gap: 5px;
  margin-left: auto;
  color: var(--muted);
  font-size: 10px;
}

.field-required {
  color: var(--danger);
}

.field-type {
  padding: 0 4px;
  border-radius: 3px;
  background: #f0f2f5;
  font-size: 10px;
  line-height: 14px;
}

.field-default {
  max-width: 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: Consolas, 'Courier New', monospace;
}

.field-desc {
  color: var(--muted);
  font-size: 10px;
  line-height: 14px;
  margin-bottom: 3px;
}

.number-input {
  width: 100%;
}

.config-form :deep(.el-select) {
  width: 100%;
}

.json-input :deep(textarea) {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 11px;
}

.json-error {
  color: var(--danger);
  font-size: 10px;
  margin-top: 2px;
}
</style>
