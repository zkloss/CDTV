import { hasAuthoredCut } from './continuityPlan.js'
const WIDE_SHOT = /^(大远景|远景|大全景|全景|空镜|建立镜头|定场|航拍|广角)/
const SCENE_CATEGORIES = new Set(['scene', 'environment', 'env'])

// Only the leading shot-size word counts: a body line like "后拉至全景" describes a
// camera move, not a shot that should be pinned to the scene plate.
export function isWideEstablishingShot(shot) {
  const segment = String(shot?.title || '').replace(/^【[^】]*】\s*/, '').split(/[·・\s]/)[0]
  return WIDE_SHOT.test(segment)
}

export function isSceneReference(asset) {
  return SCENE_CATEGORIES.has(String(asset?.category || asset?.type || '').toLowerCase())
}

export function pickSceneReference(references) {
  return (references || []).find(isSceneReference) || null
}

// A cut shot has no tail frame to inherit, so the new scene's own still is the only
// visual anchor. Wide/establishing cuts start on it instead of opening on a cold frame.
// The opening shot (first shot of project) also anchors to the establishing scene.
export function needsSceneAnchor(shot, isFirstShot = false) {
  return (isFirstShot || shot?.inheritPrevTail === false) && (hasAuthoredCut(shot) || isWideEstablishingShot(shot))
}
