/** 工作流顶层可选字段 env 的读取与导出。 */

/** env 对象 -> 可编辑行；不是对象时返回 null。 */
export function envToRows(env) {
  if (!env || typeof env !== 'object' || Array.isArray(env)) return null
  return Object.entries(env).map(([key, value]) => ({ key, value: String(value) }))
}

/** 可编辑行 -> env 对象；名称为空的行跳过。 */
export function rowsToEnv(rows) {
  return Object.fromEntries(
    rows.filter((row) => row.key).map((row) => [row.key, String(row.value ?? '')]),
  )
}

const ENV_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/

/** 导出前的环境变量校验；返回空字符串表示通过。 */
export function envError(rows) {
  const seen = new Set()
  for (const row of rows) {
    if (!row.key) continue
    if (!ENV_NAME_RE.test(row.key)) return `环境变量名不合法：${row.key}`
    if (seen.has(row.key)) return `环境变量名重复：${row.key}`
    seen.add(row.key)
  }
  return ''
}

/** 空对象不写 env，避免污染导出 JSON。 */
export function attachEnv(workflow, env) {
  if (Object.keys(env).length === 0) return workflow
  return { ...workflow, env: { ...env } }
}
