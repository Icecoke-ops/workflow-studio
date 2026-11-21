/** 与 Vue 运行时无关的工作流模型纯函数，可被 Node 直接 import 测试。 */

import { buildAddition } from './addition.js'
import { isComponentNode } from './groups.js'
import { attachEnv, rowsToEnv } from './workflow.js'

// schema 默认值来自后端 JSON；从 props 取出来是响应式 Proxy，
// structuredClone 克隆 Proxy 会抛 DataCloneError，所以用 JSON 往返。
export function cloneDefault(value) {
  return value !== null && typeof value === 'object'
    ? JSON.parse(JSON.stringify(value))
    : value
}

/** 后端 config_schema -> config；只取声明了 default 的字段。 */
export function defaultsFor(schema) {
  const config = {}
  for (const [name, spec] of Object.entries(schema || {})) {
    if (spec && Object.prototype.hasOwnProperty.call(spec, 'default')) {
      config[name] = cloneDefault(spec.default)
    }
  }
  return config
}

/**
 * 编辑器状态 -> 工作流 JSON。inputs 由 edges 按 target/targetHandle 归并。
 * 画布上的组卡片/框只影响视图，这里只导出组件节点。
 * edges 只放真实节点之间的边；投影边只进 canvasEdges，不要传进来。
 * addition 是 readAddition(raw) 的结果（或 null），原样交给 buildAddition；
 * groups 是 groups.js 序列化后的条目，不传时沿用导入时读到的那份。
 */
export function buildWorkflow({ name, nodes, edges, envRows, addition, groups }) {
  const componentNodes = nodes.filter(isComponentNode)
  const inputsByTarget = new Map()
  for (const edge of edges) {
    if (!edge.source || !edge.target || !edge.targetHandle || !edge.sourceHandle) continue
    if (!inputsByTarget.has(edge.target)) inputsByTarget.set(edge.target, {})
    inputsByTarget.get(edge.target)[edge.targetHandle] = {
      from: edge.source,
      port: edge.sourceHandle,
    }
  }

  const workflow = attachEnv(
    {
      name: name.trim() || '未命名工作流',
      nodes: componentNodes.map((node) => ({
        id: node.id,
        plugin: node.data.plugin,
        component: node.data.component,
        config: { ...node.data.config },
        inputs: inputsByTarget.get(node.id) || {},
      })),
    },
    rowsToEnv(envRows),
  )
  return {
    ...workflow,
    addition: buildAddition({ nodes: componentNodes, addition, groups }),
  }
}
