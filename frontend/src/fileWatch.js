import { onBeforeUnmount, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { statFile } from './api.js'

const POLL_MS = 2000

/** 两个文件版本是否相同（size + mtime_ns）。两边都没有版本视为相同。 */
export function sameVersion(a, b) {
  if (!a || !b) return a == null && b == null
  return a.size === b.size && String(a.mtime_ns) === String(b.mtime_ns)
}

/**
 * `/api/stat` 载荷 → { kind: 'file', version } / { kind: 'missing' }；载荷不可用时返回 null。
 * meta 是 'dir' 也当 missing：文件原来那个位置已经不是文件了，内容无从重载。
 */
export function versionFromStat(payload) {
  if (!payload || payload.ok !== true) return null
  if (payload.kind !== 'file') return { kind: 'missing', version: null }
  return { kind: 'file', version: { size: payload.size, mtime_ns: payload.mtime_ns } }
}

/** 保存响应里的版本；缺 size/mtime_ns 时返回 null（让下一次 stat 当基线）。 */
export function versionFromSave(data) {
  if (!data || data.size == null || data.mtime_ns == null) return null
  return { size: data.size, mtime_ns: data.mtime_ns }
}

/**
 * 轮询文件在磁盘上的版本，外部改动后弹确认、由 reloadFn 把内容读回来。
 * path 传 getter（当前文档会切换）；reloadFn 成功后调用返回的 markSynced() 记新基线。
 */
export function useFileSync(path, reloadFn, { canReload } = {}) {
  const changed = ref(false)
  const missing = ref(false)
  const version = ref(null)

  let baseline = null // 内容与磁盘一致时的版本
  let prompted = null // 已经问过的那一版，同一版不再重复弹
  let timer = 0
  let seq = 0
  let disposed = false
  let prompting = false

  const currentPath = () => String(path() || '')

  async function check() {
    const target = currentPath()
    if (!target) return
    const mine = ++seq
    let payload
    try {
      payload = await statFile(target)
    } catch {
      return // 网络/服务错误静默跳过，下次轮询再试
    }
    // 只认最新一次：序号过期或路径已经换了就丢掉，免得旧响应盖到新文档上
    if (disposed || mine !== seq || currentPath() !== target) return

    const info = versionFromStat(payload)
    if (!info) return
    if (info.kind !== 'file') {
      missing.value = true
      changed.value = false
      version.value = null
      return
    }

    missing.value = false
    version.value = info.version
    if (!baseline) {
      baseline = info.version // 首次成功响应即基线
      changed.value = false
      return
    }
    if (sameVersion(info.version, baseline)) {
      changed.value = false
      return
    }

    changed.value = true
    if (sameVersion(info.version, prompted)) return
    prompted = info.version
    void promptReload(target)
  }

  async function promptReload(target) {
    if (prompting || disposed) return
    prompting = true
    let accepted = false
    try {
      const text = canReload?.() === false
        ? '磁盘上的文件已被修改，是否重新加载？会丢失未保存的修改'
        : '磁盘上的文件已被修改，是否重新加载？'
      await ElMessageBox.confirm(text, '文件已被修改', {
        type: 'warning',
        confirmButtonText: '重新加载',
        cancelButtonText: '稍后',
      })
      accepted = true
    } catch {
      accepted = false // 取消：提示条留着，用户可以手动重载
    } finally {
      prompting = false
    }
    // 弹窗期间切走了文档：这版的确认已经不属于当前文件，别拿它去重载别人
    if (!accepted || disposed || currentPath() !== target) return
    await reloadFn()
  }

  /** 内容已与磁盘同步：next 是确切版本；不传则拿下一次 stat 当基线。 */
  function markSynced(next) {
    baseline = next || null
    prompted = baseline
    changed.value = false
    missing.value = false
    if (baseline) version.value = baseline
    else void check() // 没有确切版本时立刻问一次，别等满 2 秒
  }

  function reload() {
    return Promise.resolve(reloadFn())
  }

  function stopTimer() {
    if (!timer) return
    clearInterval(timer)
    timer = 0
  }

  function start() {
    stopTimer()
    seq += 1 // 作废在途请求
    baseline = null
    prompted = null
    changed.value = false
    missing.value = false
    version.value = null
    if (!currentPath()) return
    timer = setInterval(() => {
      if (!document.hidden) void check()
    }, POLL_MS)
    void check()
  }

  function onVisibilityChange() {
    if (!document.hidden) void check() // 回前台立刻查一次
  }

  watch(path, start)
  document.addEventListener('visibilitychange', onVisibilityChange)
  onBeforeUnmount(() => {
    disposed = true
    stopTimer()
    document.removeEventListener('visibilitychange', onVisibilityChange)
  })
  start()

  return { changed, missing, reload, markSynced, version }
}
