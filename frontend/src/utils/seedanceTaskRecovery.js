const ACTIVE = new Set(['preparing', 'submitting', 'queued', 'pending', 'generating', 'processing', 'running', 'cancelling'])
const TERMINAL = new Set(['succeeded', 'completed', 'done', 'success', 'failed', 'error', 'cancelled', 'canceled', 'rejected', 'expired'])

// API video tasks are persisted on the shot; they are not browser-worker tasks
// returned by list_tasks. Reopening must query the same provider job, not submit.
export function restoreSeedanceTask(shot) {
  if (shot?.generationEngine !== 'seedance') return false
  const attempt = shot.lastGenerationAttempt
  const status = String(attempt?.status || '').toLowerCase()
  if (TERMINAL.has(status)) return false
  const taskId = String((ACTIVE.has(status) && attempt?.taskId) || shot.seedanceTaskId || '').trim()
  if (!taskId) return false
  shot.taskId = taskId
  shot.seedanceTaskId = taskId
  shot.seedanceTaskCreatedAt = Number(shot.seedanceTaskCreatedAt || attempt?.submittedAt || 0)
  shot.status = ACTIVE.has(status) && status !== 'cancelling' ? status : 'pending'
  shot.statusText = shot.seedanceModel
    ? '已找回原生成任务，正在查询最新进度…'
    : '原生成任务已保留，但缺少原模型配置；请先恢复配置，不要重复提交'
  shot.generationError = ''
  shot.progress = Number(shot.progress || 0)
  return true
}
