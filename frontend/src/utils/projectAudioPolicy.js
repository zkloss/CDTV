// Audio belongs to each shot's sound panel, rather than the visual asset library.
export function removeAudioAssets(document) {
  const value = JSON.parse(JSON.stringify(document || {}))
  const audioIds = new Set()
  const isAudio = asset => asset?.category === 'audio' || /^(?:aud_|breeze_)/.test(String(asset?.id || asset || ''))
  const roots = [value, value.consistency, !Array.isArray(value.assets) && value.assets].filter(Boolean)
  for (const root of roots) {
    for (const key of ['audio', 'audios', 'sound_effects', 'sounds', 'bgm', 'voices', 'sound']) {
      if (!Array.isArray(root[key])) continue
      for (const asset of root[key]) if (asset?.id) audioIds.add(String(asset.id))
      delete root[key]
    }
    if (Array.isArray(root.assets)) {
      root.assets = root.assets.filter(asset => {
        if (!isAudio(asset)) return true
        audioIds.add(String(asset.id)); return false
      })
    }
  }
  const excluded = ref => isAudio(ref) || audioIds.has(String(ref?.id || ref || ''))
  for (const root of roots) {
    if (Array.isArray(root.asset_wirelist)) root.asset_wirelist = root.asset_wirelist.filter(item => !excluded(item.asset_id))
    for (const shot of [...(root.storyboards || []), ...(root.shots || [])]) {
      const references = Array.isArray(shot.references) ? shot.references : []
      const dubbing = references.find(ref => ref?.id && ref.id === shot.breezeAudioAssetId)
      if (dubbing) shot.dubbingAudio = dubbing
      references.filter(excluded).forEach(ref => audioIds.add(String(ref?.id || ref)))
      shot.references = references.filter(ref => !excluded(ref))
      if (Array.isArray(shot.wirelist)) shot.wirelist = shot.wirelist.filter(item => !excluded(item.asset_id || item.id))
      if (shot.referenceLabels) for (const id of Object.keys(shot.referenceLabels)) if (excluded(id)) delete shot.referenceLabels[id]
      for (const key of ['prompt', 'video_prompt']) {
        if (typeof shot[key] !== 'string') continue
        shot[key] = shot[key].split('\n').map(line => {
          if (!/^一致性引用[：:]/.test(line)) return line
          return '一致性引用：' + line.replace(/^一致性引用[：:]/, '').split(/[，,]/).filter(part => {
            const id = part.match(/\{\{([^}]+)\}\}/)?.[1]
            return !id || !excluded(id)
          }).join('，')
        }).join('\n')
      }
    }
  }
  return value
}
