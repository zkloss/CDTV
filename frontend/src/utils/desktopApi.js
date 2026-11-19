let readyPromise = null

export function isApiAvailable(api = window.pywebview?.api) {
  return Boolean(
    api &&
    typeof api === 'object' &&
    typeof api.backend_request === 'function'
  )
}

export function waitForDesktopApi(timeoutMs = 15000) {
  if (isApiAvailable()) {
    return Promise.resolve(window.pywebview.api)
  }

  if (readyPromise) {
    return readyPromise
  }

  readyPromise = new Promise((resolve) => {
    let settled = false
    let timer = null
    let timeoutTimer = null

    const finish = (api) => {
      if (settled) return
      if (!isApiAvailable(api)) return
      settled = true
      if (timer) clearInterval(timer)
      if (timeoutTimer) clearTimeout(timeoutTimer)
      window.removeEventListener('pywebviewready', handleReady)
      readyPromise = null
      resolve(api)
    }

    const handleReady = () => {
      if (isApiAvailable()) {
        finish(window.pywebview.api)
      }
    }

    window.addEventListener('pywebviewready', handleReady)
    timer = setInterval(() => {
      if (isApiAvailable()) {
        finish(window.pywebview.api)
      }
    }, 15)

    timeoutTimer = setTimeout(() => {
      if (settled) return
      settled = true
      if (timer) clearInterval(timer)
      window.removeEventListener('pywebviewready', handleReady)
      readyPromise = null
      resolve(isApiAvailable() ? window.pywebview.api : null)
    }, timeoutMs)

    handleReady()
  })

  return readyPromise
}

export async function getDesktopApi(timeoutMs = 15000) {
  return await waitForDesktopApi(timeoutMs)
}

export async function desktopBackendRequest(method, path, token = 'local-storage', body = null, maxRetries = 3) {
  let lastError = null
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const api = await waitForDesktopApi(attempt === 0 ? 15000 : 3000)
    if (!isApiAvailable(api)) {
      lastError = new Error('桌面接口连接超时，请重试')
      if (attempt < maxRetries) {
        await new Promise(r => setTimeout(r, 200 * (attempt + 1)))
        continue
      }
      throw lastError
    }

    try {
      return await api.backend_request(method, path, token, body)
    } catch (err) {
      lastError = err
      const errStr = String(err?.message || err || '')
      const isTransient = errStr.includes('无法连接 Storage') || errStr.includes('尚未就绪') || errStr.includes('连接')
      if (attempt < maxRetries && isTransient) {
        await new Promise(r => setTimeout(r, 250 * (attempt + 1)))
        continue
      }
      throw err
    }
  }
  throw lastError || new Error('请求失败，请稍后重试')
}
