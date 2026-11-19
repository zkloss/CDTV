// Metadata alone does not mean the requested picture can be shown. Keep the
// outgoing picture until the incoming video's seek and decode have completed.
export function prepareVideoFrame(video, offset, { signal, timeoutMs = 10000 } = {}) {
  return new Promise((resolve, reject) => {
    let positioned = false
    let frame = 0
    let settled = false
    const events = ['loadedmetadata', 'loadeddata', 'canplay', 'seeked']
    const finish = error => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      cancelAnimationFrame(frame)
      for (const name of events) video.removeEventListener(name, check)
      video.removeEventListener('error', failed)
      signal?.removeEventListener('abort', aborted)
      if (error) reject(error)
      else resolve()
    }
    const aborted = () => finish(new DOMException('Playback selection cancelled', 'AbortError'))
    const failed = () => finish(new Error('视频无法解码，请检查该分镜文件'))
    function check() {
      if (settled || video.readyState < 1) return
      if (!positioned) {
        positioned = true
        const duration = Number(video.duration)
        const target = Math.max(0, Math.min(Number.isFinite(duration) ? Math.max(0, duration - .001) : offset, offset))
        if (Math.abs(video.currentTime - target) > .001) {
          try { video.currentTime = target } catch (error) { finish(error); return }
        }
      }
      if (video.seeking || video.readyState < 2 || frame) return
      frame = requestAnimationFrame(() => {
        frame = 0
        if (!video.seeking && video.readyState >= 2) finish()
      })
    }
    const timer = setTimeout(() => finish(new Error('下一分镜尚未加载完成，已暂停；点击播放可重试')), timeoutMs)
    for (const name of events) video.addEventListener(name, check)
    video.addEventListener('error', failed)
    signal?.addEventListener('abort', aborted, { once: true })
    if (signal?.aborted) aborted()
    else if (video.error) failed()
    else check()
  })
}
