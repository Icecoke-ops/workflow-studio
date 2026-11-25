/** /api/project 载荷 -> 工作台项目状态；纯函数，可被 Node 直接 import 测试。 */

/**
 * 插件同名冲突时后端回 ok:false，但 root/name/launcher 仍然合法、文件接口照常可用；
 * 这种要降级成「能浏览/编辑文件，不能校验/运行/调试」，而不是当成没有项目。
 * 只有载荷缺 root 才返回 null；网络失败由调用方处理。
 */
export function normalizeProject(payload) {
  if (!payload || typeof payload !== 'object') return null
  if (typeof payload.root !== 'string' || !payload.root) return null

  const errors = Array.isArray(payload.errors)
    ? payload.errors.filter((item) => typeof item === 'string' && item)
    : []

  return {
    project: {
      root: payload.root,
      name: typeof payload.name === 'string' && payload.name ? payload.name : payload.root,
      launcher:
        typeof payload.launcher === 'string' && payload.launcher ? payload.launcher : null,
    },
    degraded: payload.ok === false,
    errors,
  }
}
