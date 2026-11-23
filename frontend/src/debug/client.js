/** 调试会话的 WebSocket 客户端；报文见 docs/CONTRACT.md §9.6。
 *  浏览器原生 WebSocket，不引依赖。 */

const OPEN = 1

export class DebugClient {
  constructor({ port, token, handlers = {} } = {}) {
    this.port = port
    this.token = token
    this.handlers = handlers || {}
    this.socket = null
    this.intentionalClose = false
  }

  /** 连上调试钩子。Promise 在 onopen 时 resolve；连不上或连上就被关时 reject。 */
  connect() {
    this.close()
    this.intentionalClose = false

    const url = `ws://127.0.0.1:${this.port}/?token=${encodeURIComponent(this.token)}`

    return new Promise((resolve, reject) => {
      let settled = false
      let failed = false
      let socket
      try {
        socket = new WebSocket(url)
      } catch (err) {
        reject(new Error(`无法连接调试端口 ${this.port}：${err.message}`))
        return
      }
      this.socket = socket

      socket.onopen = () => {
        settled = true
        resolve()
      }

      socket.onerror = () => {
        failed = true
        if (settled) return
        settled = true
        this.socket = null
        reject(new Error(`调试连接失败（端口 ${this.port}）`))
      }

      socket.onmessage = (event) => this.dispatch(event.data)

      socket.onclose = (event) => {
        // 已被新连接替换的旧 socket 不再处理，否则上一轮的关闭会通知到新会话
        if (this.socket !== socket) return
        this.socket = null
        if (!settled) {
          settled = true
          reject(new Error('调试连接在建立前被关闭'))
          return
        }
        // 主动 close() 或连接本身出错时不通知；钩子自己退出必须让上层知道
        if (failed || this.intentionalClose) return
        this.handlers.onClose?.({ code: event.code, reason: event.reason })
      }
    })
  }

  dispatch(raw) {
    if (typeof raw !== 'string') return
    let message
    try {
      message = JSON.parse(raw)
    } catch {
      return
    }
    if (!message || typeof message !== 'object') return

    const handlers = this.handlers
    switch (message.type) {
      case 'state':
        handlers.onState?.(message.data)
        break
      case 'log':
        handlers.onLog?.(message)
        break
      case 'ack':
        handlers.onAck?.(message)
        break
      case 'inspect':
        handlers.onInspect?.(message.data)
        break
      case 'error':
        handlers.onError?.(message)
        break
      default:
        break
    }
  }

  /** 发一条命令；连接不可用时返回 false，不抛异常。 */
  send(cmd) {
    if (!this.socket || this.socket.readyState !== OPEN) return false
    this.socket.send(JSON.stringify(cmd))
    return true
  }

  /** 主动断开：不再触发 onClose。 */
  close() {
    const socket = this.socket
    if (!socket) return
    this.intentionalClose = true
    try {
      socket.close()
    } catch {
      this.socket = null
    }
  }
}
