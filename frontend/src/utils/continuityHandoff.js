const role = asset => ['role','character','actor'].includes(String(asset?.category || asset?.type || '').toLowerCase())
const bodyOf = shot => String(shot?.prompt || '').replace(/【自动转场安排·开始】[\s\S]*?【自动转场安排·结束】/g, '')
export function roleHandoffPlan(shots, shot) {
  if (!shot || shot.inheritPrevTail === false) return null
  const configured=shot.continuityHandoff
  if (configured?.mode==='observer_reveal' && configured.observerId && configured.actorId && configured.observerId!==configured.actorId) return configured
  const index=shots.findIndex(s=>s.id===shot.id), previous=shots[index-1]
  if (!previous || !/(入|进|奔向|冲向).{0,10}(屋|房|门)|门.{0,8}(奔来|跑来)/.test(bodyOf(shot))) return null
  const incoming=(shot.references || []).filter(role), prior=(previous.references || []).filter(role)
  const actor=incoming.find(a=>!prior.some(b=>a.id===b.id) && bodyOf(shot).includes(a.name))
  const observer=prior[0]
  if (!actor || !observer) return null
  const scene=(shot.references || []).find(a=>['scene','environment','env'].includes(String(a?.category || a?.type || '').toLowerCase()))
  return {version:1,mode:'observer_reveal',phase:'scripted',observerId:observer.id,observerName:observer.name,actorId:actor.id,actorName:actor.name,
    actorReferenceId:actor.id,sceneReferenceId:scene?.id,referencePolicy:scene ? 'characters-and-scene' : 'characters-only',
    observerAction:'按本镜正文执行该角色的动作与站位',
    actorAction:'按本镜正文的进场方式、持物与目的地行动'}
}
export function handoffReferences(plan, references, tail) {
  if (!plan) return null
  if (plan.phase === 'scripted') {
    const scene = plan.sceneReferenceId ? references.find(a => a.id === plan.sceneReferenceId) : null
    const roleOnly = ['characters-only', 'characters-and-scene'].includes(plan.referencePolicy)
    return [tail, ...references.filter(a => role(a) || (!roleOnly && a.category === 'prop')), scene].filter(Boolean).filter((a,i,all)=>all.findIndex(b=>b.id===a.id)===i)
  }
  const actor=references.find(a=>a.id===(plan.actorReferenceId || plan.actorId)) || references.find(a=>a.id===plan.actorId)
  // The real tail already owns the camera and room geometry. A second scene
  // image can make the model reframe the opening even when actor identity holds.
  const layout=plan.useLayoutReference === true ? references.find(a=>a.id===plan.layoutReferenceId) : null
  return [tail,actor,layout].filter(Boolean).filter((a,i,all)=>all.findIndex(b=>b.id===a.id)===i)
}
export function roleHandoffInstruction(plan, descriptors=[]) {
  if (!plan) return ''
  const marker=id=>descriptors.find(d=>d.asset?.id===id)?.marker || ''
  if (plan.phase === 'scripted') return `【人物交接·按剧本执行】第一张图是上一镜真实尾帧，锁定第0秒。${plan.observerName}与新入画的${plan.actorName}是两个不同的人，身份、外貌、服装不互换；后续站位、持物、行走方式、目的地、机位和动作完全按本镜正文执行。其余人物图仅用于身份，道具图仅用于对应物件，不替代真实尾帧，不增加正文未写的动作或环境。${plan.sceneReferenceId ? `\n【场景参考分工】${marker(plan.sceneReferenceId)}是同一空间的场景设定，约束后续显露的门窗、柜台、样片墙及家具布局；第0秒仍只按真实尾帧，场景图不作为新的开场。摄影机连续转动时自然显露图中已有空间，不另造房间或增加陈设。` : ''}`
  const actorImage=marker(plan.actorReferenceId || plan.actorId)
  const layoutImage=marker(plan.layoutReferenceId)
  if (plan.phase === 'inside') return `【屋内双人身份锁】第一张图是同一原屋内的上一镜真实尾帧。${plan.observerName}与${plan.actorName}是两个不同的人，外貌服装不互换。${plan.observerName}：${plan.observerAction}。${actorImage}仅锁定同一个${plan.actorName}的外貌；${plan.actorName}：${plan.actorAction}。两人已经都在同一间原屋，按本镜正文各自的动作继续，不返回街道、不重新跑一次入屋，不去对面房子。保持尾帧的屋内结构、门口方向和日光。`
  return `【人物交接·最高优先级】本镜明确存在两个不同的人，身份与动作不能互换。第一张图是上一镜真实尾帧：其中的${plan.observerName}是观察者，${plan.observerAction}。${actorImage ? actorImage+'是' : ''}${plan.actorName}是另外一个跑来的少年，${plan.actorAction}；不能把尾帧里的${plan.observerName}变成逃跑者，也不能用他替代少年。\n【入屋目标锁定】目的地：${plan.destination}。摄影机留在这间屋门口内侧朝外看；少年朝镜头和观察者跑来，最后从观察者身旁跨过当前门槛进入镜头所在屋。街对面的红纸木门只是背景，不能让任何主角跑到对面房子。${layoutImage ? layoutImage+'仅交代同一门口朝外的街道和来人位置，不作为开场、不替换尾帧人物。' : ''}\n【首帧与人物连续】第0秒复现真实尾帧的站位和光线；随后观察者在门槛内向侧边让半步、始终留在近景，少年由街道纵深跑进画面并接近同一入口。人物参考只锁定同一个少年的外貌，不生成第二个少年、不把多张参考图当成多段故事。`
}
