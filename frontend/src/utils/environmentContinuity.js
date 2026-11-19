export const cleanTransitionBlock = value => String(value || '').replace(/【自动转场安排·开始】[\s\S]*?【自动转场安排·结束】/g, '')
export const clean = cleanTransitionBlock
export function environmentHints(text) {
  text=String(text || '')
  const timeOfDay = /黄昏转夜|夜晚|夜间|夜色|月光|深夜|入夜/.test(text) ? '夜晚' : /黄昏|傍晚|落日|夕阳|暮色|残阳/.test(text) ? '黄昏' : /黎明|清晨|晨光/.test(text) ? '清晨' : /白天|日间|日光|午后|正午|阳光/.test(text) ? '白天' : ''
  const weather = /下雪|飘雪|雪天|大雪/.test(text) ? '雪天' : /下雨|雨天|大雨|暴雨|淋雨/.test(text) ? '雨天' : /浓雾|大雾|雾天/.test(text) ? '雾天' : /晴|少云|干燥|无雨/.test(text) ? '晴到少云、地面干燥' : ''
  return { timeOfDay, weather }
}
export function environmentAt(shots, index) {
  let previous={ timeOfDay:'',weather:'',lighting:'' }
  for(let i=0;i<=index;i++) {
    const shot=shots[i], explicit=shot.environmentContinuity || {}
    const scene=shot.references?.find(a=>a.category==='scene') || {}
    const body=clean(shot.prompt)
    const reset=i===0 || explicit.reset || shot.temporalBreak || /次日|翌日|数日后|多年后|数十年后|回忆|梦境|夜幕降临|天色转暗|另一座|异地|远在|时空|变迁|流转|重组|跨越|现代|时代|岁月|跨场景|转场/.test(body)
    const hints=environmentHints(body)
    const sceneHints=environmentHints([scene.environment,scene.prompt].join(' '))
    const requested={timeOfDay:explicit.timeOfDay || hints.timeOfDay || scene.time_of_day || sceneHints.timeOfDay,
      weather:explicit.weather || hints.weather || scene.weather || sceneHints.weather,
      lighting:explicit.lighting || ''}
    previous={ timeOfDay:(!reset && previous.timeOfDay) || requested.timeOfDay || '',
      weather:(!reset && previous.weather) || requested.weather || '',
      lighting:(!reset && previous.lighting) || requested.lighting || '', reset:Boolean(reset) }
  }
  return previous
}
export function environmentInstruction(shots, shot) {
  const index=shots.findIndex(s=>s.id===shot.id)
  if(index<0)return ''
  const env=environmentAt(shots,index)
  const details=[env.timeOfDay && `时间：${env.timeOfDay}`,env.weather && `天气：${env.weather}`,env.lighting && `光线：${env.lighting}`].filter(Boolean).join('；')
  if(!details && index===0)return ''
  return `【时空与天气连续性】${details || '延续前镜已经建立的时间、天气和自然光方向'}。${index>0 && !env.reset ? '这是连续发生的剧情，换场景不代表时间跳跃；必须沿用前镜的昼夜、天气、地面干湿和光色。' : '以本镜明确指定的时空条件建立画面。'}室内可以因遮挡较暗，屋外应符合相同日照，不能将室内阴影解释成夜晚；保持合理曝光和环境细节，不突然下雨、起雾、变黄昏或出现月亮。场景参考图仅锁定建筑和布局，若旧图光照冲突，以本段时空条件为准。`
}
export function environmentConflicts(shots, shot) {
  const env=environmentAt(shots,shots.findIndex(s=>s.id===shot.id))
  return (shot.references || []).filter(a=>a.category==='scene' && (a.fileId || a.coverId || a.cover)).flatMap(a=>{
    const reference=a.referenceEnvironment || environmentHints(a.generatedPrompt || a.prompt || a.environment)
    const mismatches=[]
    if(env.timeOfDay && reference.timeOfDay && env.timeOfDay!==reference.timeOfDay)mismatches.push(`参考图为${reference.timeOfDay}，连续剧情为${env.timeOfDay}`)
    if(env.weather && reference.weather && env.weather!==reference.weather)mismatches.push(`参考图天气为${reference.weather}，连续剧情为${env.weather}`)
    return mismatches.length ? [`${a.name || a.id}：${mismatches.join('；')}`] : []
  })
}

// Check authored picture fields too: an inherited daylight lock must not coexist
// with a leftover dusk/rain description, even if it is outside the main prompt.
export function shotEnvironmentConflicts(shots, shot) {
  const index = shots.findIndex(s => s.id === shot.id)
  if (index < 0) return []
  const env = environmentAt(shots, index)
  return [['画面正文', clean(shot.prompt)], ['画面摘要', shot.visual]].flatMap(([label, value]) => {
    const picture = String(value || '').split('\n')
      .filter(line => !/^\s*(对白|台词|旁白|音频提示词)[：:]/.test(line))
      .join(' ').replace(/(?:不|禁止|严禁|不得|不能)(?:突然|出现|变成|变)?(?:下雨|雨天|起雾|夜晚|黄昏|月光|暮色|残阳)/g, '')
    const hints = environmentHints(picture), problems = []
    if (env.timeOfDay && hints.timeOfDay && env.timeOfDay !== hints.timeOfDay) problems.push(`${label}写的是${hints.timeOfDay}，环境已锁定${env.timeOfDay}`)
    if (env.weather && hints.weather && env.weather !== hints.weather) problems.push(`${label}天气为${hints.weather}，环境已锁定${env.weather}`)
    return problems
  })
}
