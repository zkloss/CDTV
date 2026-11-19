// Authored cuts must not be converted into extensions by a checkbox or tail refresh.
// Do not infer a cut merely from a wide shot, a new character, or crossing a door.
export function authoredContinuityKind(shot) {
  const kind = shot?.continuityPlan?.kind
  if (['scene-start', 'camera-cut', 'scene-cut', 'continuous'].includes(kind)) return kind
  if (shot?.continuityHandoff?.mode === 'observer_reveal' && shot.continuityHandoff.phase !== 'scripted') return 'continuous'
  const body = String(shot?.prompt || '').replace(/【自动转场安排·开始】[\s\S]*?【自动转场安排·结束】/g, '')
  if (/【镜头】\s*换机位剪辑进入|本镜已经剪切到|本镜已(?:经)?切到|本镜不要求与它同像素构图/.test(body)) return 'camera-cut'
  return ''
}

export function hasAuthoredCut(shot) {
  return ['scene-start', 'camera-cut', 'scene-cut'].includes(authoredContinuityKind(shot))
}

export function alignAuthoredContinuity(shot) {
  if (shot?.continuityMode === 'transition') return false
  if (!hasAuthoredCut(shot)) return false
  const changed = shot.inheritPrevTail !== false || shot.continuityMode !== 'matchCut'
  shot.inheritPrevTail = false
  shot.continuityMode = 'matchCut'
  // Explicit cuts use the selected scene, never an implicit gaze/tail opening.
  shot.gazeHandoff = false
  shot.continuityHandoff = null
  if (changed) shot.continuityReview = null
  return changed
}

export function continuityPlanProblems(shot, references = []) {
  const problems = []
  if (hasAuthoredCut(shot)) {
    if (shot.continuityMode !== 'transition' && (shot.inheritPrevTail !== false || shot.continuityMode !== 'matchCut')) problems.push('正文要求剪辑切镜，但当前正在使用尾帧续接')
    const sceneId = shot.continuityPlan?.sceneReferenceId
    if (sceneId && !references.some(a => a.id === sceneId)) problems.push('指定的场景参考图缺失')
    if (shot.continuityPlan?.referencePolicy === 'composed-start-only') {
      const start = references.find(a => a.id === sceneId)
      if (!start?.isComposedStartFrame || start.startFrameReview?.status !== 'passed') problems.push('合成起始帧尚未核对，不能作为唯一画面依据')
    }
  }
  return problems
}

export function sceneCutReferences(shot, references, anchor) {
  if (anchor) {
    if (shot.continuityPlan?.referencePolicy === 'composed-start-only') return [anchor]
    return [anchor, ...references.filter(a => a.id !== anchor.id)]
  }
  // Fallback: If no anchor was explicitly chosen, but references contain a scene and role,
  // prioritize the scene asset over character turnaround sheets so the video doesn't open on a 4-view turnaround
  const SCENE_CATS = new Set(['scene', 'environment', 'env'])
  const sceneAsset = (references || []).find(a => SCENE_CATS.has(String(a?.category || a?.type || '').toLowerCase()))
  if (sceneAsset) {
    return [sceneAsset, ...references.filter(a => a.id !== sceneAsset.id)]
  }
  return references
}

export function pinSceneStart(shot) {
  return hasAuthoredCut(shot) && shot.continuityPlan?.referencePolicy === 'composed-start-only'
}
