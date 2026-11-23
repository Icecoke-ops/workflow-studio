import { nextTick, ref } from 'vue'

// 标题就地改名：编辑态自持，提交才交给宿主（data.onRename），取消直接丢弃草稿。
// getData 每次现取，别把 props.data 的对象引用冻在闭包里（导入覆盖同 id 节点时 data 会换）。
export function useInlineTitle(getData) {
  const editing = ref(false)
  const draft = ref('')
  const composing = ref(false)
  const titleInput = ref(null)

  async function beginRename() {
    draft.value = getData().title || ''
    editing.value = true
    await nextTick()
    titleInput.value?.focus()
    titleInput.value?.select()
  }

  function onCompositionStart() {
    composing.value = true
  }

  function onCompositionEnd() {
    composing.value = false
    // 浏览器可能先 blur 后 compositionend：组字结束后若输入框已失焦，补一次提交
    if (editing.value && titleInput.value !== document.activeElement) commitTitle()
  }

  function commitTitle() {
    if (composing.value || !editing.value) return
    editing.value = false
    const data = getData()
    const title = draft.value.trim()
    if (!title || title === data.title) return
    data.onRename?.(data.groupId, title)
  }

  function cancelTitle() {
    if (composing.value) return
    editing.value = false
  }

  return {
    editing,
    draft,
    titleInput,
    beginRename,
    onCompositionStart,
    onCompositionEnd,
    commitTitle,
    cancelTitle,
  }
}
