<script setup>
const active = defineModel('active', { type: String, default: 'explorer' })

const items = [
  { id: 'components', label: '组件' },
  { id: 'explorer', label: '资源管理器' },
]
</script>

<template>
  <nav class="activity-bar" aria-label="侧栏切换">
    <button
      v-for="item in items"
      :key="item.id"
      class="activity-item"
      :class="{ active: active === item.id }"
      type="button"
      :title="item.label"
      :aria-pressed="active === item.id"
      @click="active = item.id"
    >
      <svg
        v-if="item.id === 'components'"
        class="activity-icon"
        viewBox="0 0 24 24"
        width="20"
        height="20"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
      >
        <rect x="3.5" y="3.5" width="7" height="7" rx="1.2" />
        <rect x="13.5" y="3.5" width="7" height="7" rx="1.2" />
        <rect x="3.5" y="13.5" width="7" height="7" rx="1.2" />
        <rect x="13.5" y="13.5" width="7" height="7" rx="1.2" />
      </svg>
      <svg
        v-else
        class="activity-icon"
        viewBox="0 0 24 24"
        width="20"
        height="20"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
      >
        <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4l2 2h7A1.5 1.5 0 0 1 19 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 3 17.5z" />
      </svg>
      <span class="activity-label">{{ item.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
.activity-bar {
  display: flex;
  flex-direction: column;
  flex: none;
  width: 64px;
  background: var(--panel);
  border-right: 1px solid var(--border);
}

.activity-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 9px 2px 7px;
  border: none;
  border-left: 2px solid transparent;
  background: transparent;
  color: var(--muted);
  font-family: inherit;
  font-size: 10px;
  line-height: 13px;
  cursor: pointer;
}

.activity-item:hover {
  color: var(--text-2);
}

.activity-item.active {
  color: var(--primary);
  border-left-color: var(--primary);
  background: rgba(64, 158, 255, 0.08);
}

.activity-label {
  max-width: 60px;
  text-align: center;
  white-space: nowrap;
}
</style>
