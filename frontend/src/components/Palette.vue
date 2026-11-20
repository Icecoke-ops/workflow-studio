<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  plugins: { type: Array, default: () => [] },
})

const emit = defineEmits(['add', 'collapse'])

const keyword = ref('')
const opened = ref([])

watch(
  () => props.plugins,
  (list) => {
    opened.value = list.filter((plugin) => plugin.components?.length).map((plugin) => plugin.name)
  },
  { immediate: true },
)

const filtered = computed(() => {
  // std 这类只声明类型、没有组件的伪插件不渲染分组
  const groups = props.plugins.filter((plugin) => plugin.components?.length)
  const needle = keyword.value.trim().toLowerCase()
  if (!needle) return groups
  return groups
    .map((plugin) => ({
      ...plugin,
      components: plugin.components.filter((component) =>
        `${component.title} ${component.name} ${component.desc}`.toLowerCase().includes(needle),
      ),
    }))
    .filter((plugin) => plugin.components.length > 0)
})

function onDragStart(event, plugin, component) {
  const payload = JSON.stringify({ plugin: plugin.name, component: component.name })
  event.dataTransfer.setData('application/x-workflow-component', payload)
  event.dataTransfer.setData('text/plain', payload)
  event.dataTransfer.effectAllowed = 'copy'
}
</script>

<template>
  <aside class="palette">
    <div class="panel-title">
      <span>组件库</span>
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
    <div class="palette-search">
      <el-input v-model="keyword" size="small" placeholder="搜索组件" clearable />
    </div>

    <div class="palette-body">
      <el-collapse v-if="filtered.length" v-model="opened">
        <el-collapse-item v-for="plugin in filtered" :key="plugin.name" :name="plugin.name">
          <template #title>
            <span class="plugin-title">{{ plugin.title }}</span>
            <span class="plugin-version">v{{ plugin.version }}</span>
          </template>

          <div
            v-for="component in plugin.components"
            :key="component.name"
            class="palette-item"
            draggable="true"
            :title="component.desc"
            @dragstart="onDragStart($event, plugin, component)"
            @click="emit('add', { plugin: plugin.name, component: component.name })"
          >
            <div class="item-title">{{ component.title }}</div>
            <div class="item-name">{{ component.name }}</div>
            <div v-if="component.desc" class="item-desc">{{ component.desc }}</div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <el-empty
        v-else
        :image-size="52"
        :description="plugins.length ? '没有匹配的组件' : '还没加载到插件'"
      />
    </div>
  </aside>
</template>

<style scoped>
.palette {
  display: flex;
  flex-direction: column;
  width: 248px;
  flex: none;
  background: var(--panel);
  border-right: 1px solid var(--border);
  min-height: 0;
}

.palette-search {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
}

.palette-body {
  flex: 1;
  overflow: auto;
  min-height: 0;
  padding: 4px 6px 12px;
}

.palette-body :deep(.el-collapse) {
  border-top: none;
}

.palette-body :deep(.el-collapse-item__header) {
  padding: 0 6px;
  height: 34px;
  font-size: 12px;
  gap: 6px;
}

.palette-body :deep(.el-collapse-item__content) {
  padding-bottom: 6px;
}

.plugin-title {
  font-weight: 600;
}

.plugin-version {
  color: var(--muted);
  font-size: 11px;
  margin-left: auto;
  margin-right: 6px;
}

.palette-item {
  padding: 6px 8px;
  margin: 4px 2px;
  border: 1px solid var(--border);
  border-radius: 5px;
  cursor: grab;
  background: #fff;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.palette-item:hover {
  border-color: var(--primary);
  box-shadow: 0 1px 4px rgba(64, 158, 255, 0.18);
}

.palette-item:active {
  cursor: grabbing;
}

.item-title {
  font-size: 12px;
  font-weight: 600;
  line-height: 17px;
}

.item-name {
  font-size: 11px;
  color: var(--muted);
  line-height: 15px;
  font-family: Consolas, 'Courier New', monospace;
}

.item-desc {
  font-size: 11px;
  color: var(--text-2);
  line-height: 15px;
  margin-top: 2px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
</style>
