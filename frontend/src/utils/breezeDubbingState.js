import { sameDialogue } from './audioContract.js'

const clone = value => JSON.parse(JSON.stringify(value))
export const dubbingAudioId = audio => String(audio?.fileId || audio?.coverId || '')
export const hasAppliedDubbing = shot => Boolean(shot?.resultFileId && shot.mixedVideoFileId === shot.resultFileId && shot.mixedAudioFileId)
export const isDubbingApplied = (shot, audio) => hasAppliedDubbing(shot) && shot.mixedAudioFileId === dubbingAudioId(audio)
export function dubbingSourceVideoId(shot) {
  if (hasAppliedDubbing(shot)) {
    // A known applied mix is the sound reference for the next voice replacement.
    // Keep originalVideoFileId separately so "restore original" still works.
    if (shot.breezeTiming?.videoFileId === shot.resultFileId) return String(shot.resultFileId)
    return String(shot.originalVideoFileId || shot.resultFileId)
  }
  return String(shot?.resultFileId || '')
}
export function confirmedDubbingTiming(timing, contract, videoFileId) {
  if (!timing || timing.videoFileId !== videoFileId || !sameDialogue(timing.contract, contract)
    || timing.rows?.length !== contract.lines.length || !(timing.videoDuration > 0)) return false
  let previous = 0
  return timing.rows.every((row, index) => {
    const valid = Number.isFinite(row.start) && Number.isFinite(row.end)
      && row.start >= previous - .05 && row.end - row.start >= .12 && row.end <= timing.videoDuration + .02
      && sameDialogue({ explicit: true, lines: [row.text], roles: [row.role || '未标注角色'] },
        { explicit: true, lines: [contract.lines[index]], roles: [contract.roles?.[index] || '未标注角色'] })
    if (valid) {
      row.confirmed = true
      previous = row.end
    }
    return valid
  })
}
export function alignmentForDubbing(shot, audio, contract) {
  const source = dubbingSourceVideoId(shot), id = dubbingAudioId(audio)
  if (!id) return null
  const current = shot.breezeAlignment
  const currentMatches = current && current.videoFileId === source && current.audioFileId === id && sameDialogue(current.contract, contract)
  if (currentMatches && confirmedDubbingTiming(current, contract, source)) return current
  const timing = shot.breezeTiming
  if (!confirmedDubbingTiming(timing, contract, source)) return currentMatches ? current : null
  const result = clone(timing)
  result.audioFileId = id
  result.status = 'confirmed_timing_reused'
  result.recognitionNote = '沿用已确认的说话时间；新音频只替换声音，不重新识别或改动画面。'
  if (timing.audioFileId !== id) {
    // Source-audio sample offsets belong to the old take, never to a new take.
    for (const row of result.rows) {
      for (const key of ['pieces', 'planStart', 'planEnd', 'pausePlan']) delete row[key]
      row.method = 'confirmed_timing_reused'
    }
  }
  return result
}
export function rememberAppliedDubbing(shot, audio, contract) {
  const source = dubbingSourceVideoId(shot)
  const timing = alignmentForDubbing(shot, audio, contract)
  if (!confirmedDubbingTiming(timing, contract, source)) return false
  if (isDubbingApplied(shot, audio)) {
    const appliedTiming = { ...clone(timing), videoFileId: String(shot.resultFileId) }
    shot.breezeTiming = appliedTiming
    shot.breezeAlignment = clone(appliedTiming)
    shot.appliedDubbing = { audio: clone(audio), alignment: clone(appliedTiming),
      contract: clone(contract), videoFileId: String(shot.resultFileId) }
  } else shot.breezeTiming = clone(timing)
  return true
}
