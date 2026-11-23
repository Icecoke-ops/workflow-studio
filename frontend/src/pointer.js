// 按住拖动：window 上挂 move/up/cancel，抬手（或取消）时摘监听并回调 onEnd
export function trackPointer(onMove, onEnd) {
  const stop = () => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop)
    onEnd?.()
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
}
