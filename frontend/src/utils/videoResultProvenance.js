const linkedFields = ['resultValidation', 'resultVisualReview', 'continuityReview', 'referenceReview', 'audioReview', 'generationProvenance']
export function snapshotVideoResult(shot) {
  const result = {fileId: shot.resultFileId || '', url: shot.resultUrl || ''}
  for (const key of linkedFields) result[key] = shot[key] ? JSON.parse(JSON.stringify(shot[key])) : null
  // Keep compatibility with older project snapshots.
  result.validation = result.resultValidation
  result.visualReview = result.resultVisualReview
  return result
}
export function restoreVideoResult(shot) {
  const previous = shot.previousVideoResult
  if (!previous?.fileId && !previous?.url) {
    shot.resultFileId = ''; shot.resultUrl = ''
    for (const key of linkedFields) shot[key] = null
    return false
  }
  shot.resultFileId = previous.fileId || ''
  shot.resultUrl = previous.url || ''
  for (const key of linkedFields) shot[key] = previous[key] || null
  shot.resultValidation ||= previous.validation || null
  shot.resultVisualReview ||= previous.visualReview || null
  return true
}
export function finishGenerationAttempt(shot, status, error = '') {
  shot.lastGenerationAttempt = {...shot.lastGenerationAttempt, taskId: shot.taskId || shot.seedanceTaskId || shot.lastGenerationAttempt?.taskId || '', status, finishedAt: Date.now(), error,
    resultFileId: status === 'succeeded' ? shot.resultFileId : ''}
}
export function resultSourceMessage(shot) {
  const attempt = shot?.lastGenerationAttempt
  const failed = ['failed', 'error', 'cancelled', 'canceled', 'rejected', 'expired'].includes(attempt?.status)
  const parts = []
  if (failed) parts.push(['cancelled','canceled'].includes(attempt.status) ? '本次生成已取消，没有新成片。' : attempt.status === 'rejected' ? '本次候选未通过检查，未采用为成片。' : '本次生成失败，没有新成片。')
  if (failed && shot.resultFileId) parts.push(shot.showHistoricalResult ? '当前播放的是保留的历史版本。' : '历史版本已保留，未作为本次输出；可单独查看。')
  if (shot.referenceReview?.fileId === shot.resultFileId && shot.referenceReview?.status === 'failed') parts.push('当前候选未通过参考图一致性检查，请勿当作已确认成片。')
  else if (shot.referenceReview?.fileId === shot.resultFileId && shot.referenceReview?.status === 'pending') parts.push('视频已返回；人物与场景参考仍待核对，首帧通过不代表整镜通过。')
  if (shot.resultFileId && shot.generationProvenance?.sourceTask) parts.push(`画面来源任务：${shot.generationProvenance.sourceTask}`)
  return parts.join(' ')
}
export function hasFailedAttempt(shot) {
  return ['failed', 'error', 'cancelled', 'canceled', 'rejected', 'expired'].includes(shot?.lastGenerationAttempt?.status)
}
export function hasRejectedReferences(shot) {
  return Boolean(shot?.resultFileId && shot.referenceReview?.fileId === shot.resultFileId && shot.referenceReview.status === 'failed')
}

export function currentContinuityReview(shot) {
  const review = shot?.continuityReview
  const attempt = shot?.lastGenerationAttempt
  if (!review || !shot.resultFileId || hasFailedAttempt(shot)) return null
  if (attempt && attempt.status !== 'succeeded') return null
  if (review.fileId && review.fileId !== shot.resultFileId) return null
  if (review.taskId && review.taskId !== attempt?.taskId) return null
  if (attempt?.submittedAt && Number(review.checkedAt || 0) < Number(attempt.submittedAt)) return null
  if (!attempt && review.fileId !== shot.resultFileId) return null
  if (shot.continuityOutdated || (shot.continuityTailFrame?.fileId && review.expectedFirstFrameId !== shot.continuityTailFrame.fileId)) return null
  return review
}

export function videoTaskFailureMessage(data, label = '视频') {
  const message = typeof data?.error === 'string' ? data.error : data?.error?.message
  const detail = [message, data?.message].map(value => String(value || '').trim()).find(Boolean)
  if (detail) return detail
  const code = String(data?.error?.code || '').trim()
  return `${label}任务失败，服务商未返回具体原因${code ? `（${code}）` : ''}；请查看网关任务日志。`
}

export function rejectedCandidate(shot) {
  const attempt=shot?.lastGenerationAttempt
  if(attempt?.status!=='rejected'||!shot.rejectedResultFileId)return null
  const review=shot.rejectedContinuityReview
  const tagged=shot.rejectedResultTaskId
  if(tagged){if(!attempt.taskId||tagged!==attempt.taskId)return null}
  else if(!review?.checkedAt||!attempt.submittedAt||review.checkedAt<attempt.submittedAt)return null
  const submitted=attempt.references?.find(r=>r.role==='first_frame')
  return {fileId:shot.rejectedResultFileId,review,
    expectedFrameId:review?.expectedFirstFrameId||submitted?.fileId||'',
    actualFrameId:review?.generatedFirstFrameId||''}
}
