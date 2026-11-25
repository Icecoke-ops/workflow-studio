// 前端调 studio/server.py 的 HTTP 客户端；接口契约见 docs/CONTRACT.md 第 6 节。

const BASE = '/api'

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(BASE + path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch (err) {
    throw new Error(`无法连接后端（${path}）：${err.message}`)
  }

  const text = await res.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      throw new Error(`后端返回的不是 JSON（HTTP ${res.status}）：${text.slice(0, 200)}`)
    }
  }
  if (!res.ok) {
    const detail = data && Array.isArray(data.errors) ? data.errors.join('；') : ''
    throw new Error(detail || `HTTP ${res.status}`)
  }
  return data ?? {}
}

/** ``std_1.0@table`` -> ``std@table``（与 engine.registry.short_type 一致）。 */
function shortType(typeId) {
  if (!typeId) return '?'
  const text = String(typeId)
  const at = text.indexOf('@')
  if (at < 0) return text
  const head = text.slice(0, at)
  const name = text.slice(at + 1)
  const cut = head.lastIndexOf('_')
  return `${cut > 0 ? head.slice(0, cut) : head}@${name}`
}

function normalizePlugins(data) {
  const typeLabels = {}
  const typeDescs = {}

  const plugins = (data.plugins || []).map((plugin) => {
    for (const entry of plugin.types || []) {
      typeDescs[entry.id] = entry.desc
      typeLabels[entry.id] = shortType(entry.id)
    }

    const components = (plugin.components || []).map((component) => {
      // 端口 schema 里带了后端算好的短名，优先用它，和 registry.short_type 保一致
      for (const spec of Object.values(component.input_schema || {})) {
        ;(spec.types || []).forEach((typeId, index) => {
          const label = spec.type_labels?.[index]
          if (label) typeLabels[typeId] = label
        })
      }
      for (const spec of Object.values(component.output_schema || {})) {
        if (spec.type && spec.type_label) typeLabels[spec.type] = spec.type_label
      }
      return { plugin: plugin.name, ...component }
    })

    return { ...plugin, components }
  })

  return { plugins, typeLabels, typeDescs }
}

export async function fetchHealth() {
  return request('/health')
}

export async function fetchPlugins() {
  return normalizePlugins(await request('/plugins'))
}

export async function validateWorkflow(workflow) {
  return request('/validate', {
    method: 'POST',
    body: JSON.stringify({ workflow }),
  })
}

export async function runWorkflow(workflow) {
  const data = await request('/run', {
    method: 'POST',
    body: JSON.stringify({ workflow }),
  })
  const nodes = data.nodes.map((node) => ({
    ...node,
    failed: node.error !== null,
    outputs: Object.entries(node.outputs).map(([port, text]) => ({ port, text })),
  }))
  return {
    ...data,
    nodes,
    failedIds: nodes.filter((node) => node.failed).map((node) => node.id),
  }
}

/** 起一个调试子进程；返回 {ok, session, port, token}。契约见 §6.1。 */
export async function startDebugSession(workflow) {
  return request('/debug/start', {
    method: 'POST',
    body: JSON.stringify({ workflow }),
  })
}

/** 关掉调试会话（Studio 负责退子进程）。 */
export async function stopDebugSession(session) {
  return request('/debug/stop', {
    method: 'POST',
    body: JSON.stringify({ session }),
  })
}

/** 当前项目：{ok, root, name, launcher, plugins, skipped}。 */
export async function fetchProject() {
  return request('/project')
}

/** 列项目内一层目录；path 是项目内相对路径，'' 表示项目根。 */
export async function fetchTree(path = '') {
  return request(`/tree?path=${encodeURIComponent(path)}`)
}

/** 读项目内文本文件：{ok, path, kind, text, size}。 */
export async function fetchFile(path) {
  return request(`/file?path=${encodeURIComponent(path)}`)
}

/** 新建或覆盖文本文件。 */
export async function writeFile(path, text) {
  return request('/file', {
    method: 'POST',
    body: JSON.stringify({ path, text }),
  })
}

export async function makeDir(path) {
  return request('/mkdir', {
    method: 'POST',
    body: JSON.stringify({ path }),
  })
}

export async function renamePath(path, newName) {
  return request('/rename', {
    method: 'POST',
    body: JSON.stringify({ path, new_name: newName }),
  })
}

export async function deletePath(path) {
  return request('/delete', {
    method: 'POST',
    body: JSON.stringify({ path }),
  })
}
