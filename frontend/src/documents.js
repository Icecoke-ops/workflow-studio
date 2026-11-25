/** 项目内相对路径工具 + 新建流程图文本；纯函数，可被 Node 直接 import 测试。 */

const FLOW_EXT = '.flow'

/** 统一成项目内相对路径：反斜杠转 /、折叠重复分隔符、去掉首尾 /。 */
export function normalizePath(path) {
  return String(path || '')
    .trim()
    .replace(/\\/g, '/')
    .replace(/\/+/g, '/')
    .replace(/^\/+|\/+$/g, '')
}

/** 目录 + 名字；base 为空时就是名字。 */
export function joinPath(base, name) {
  const dir = normalizePath(base)
  const child = String(name || '').replace(/^[\\/]+/, '')
  return dir ? `${dir}/${child}` : child
}

/** 去掉最后一段；根目录返回空串。 */
export function parentPath(path) {
  const text = normalizePath(path)
  const cut = text.lastIndexOf('/')
  return cut < 0 ? '' : text.slice(0, cut)
}

/** 路径最后一段（兼容 / 和 \）。 */
export function titleFromPath(path) {
  const text = String(path || '').replace(/[\\/]+$/, '')
  const cut = Math.max(text.lastIndexOf('/'), text.lastIndexOf('\\'))
  return cut < 0 ? text : text.slice(cut + 1)
}

export function isFlowPath(path) {
  return String(path || '').toLowerCase().endsWith(FLOW_EXT)
}

/** 新建流程图的初始内容：只有名字和空节点表。 */
export function newFlowText(name) {
  return JSON.stringify({ name: String(name || '未命名工作流'), nodes: [] }, null, 2)
}
