import { roleHandoffPlan } from './continuityHandoff.js'

const visualBody = shot => {
  const text = String(shot?.prompt || '').replace(/【自动转场安排·开始】[\s\S]*?【自动转场安排·结束】/g, '')
  const action = text.match(/【本镜动作】([^]*?)(?=\n【|\n对白[：:]|$)/)
  return action ? action[1] : text.split('\n').filter(line => !/^\s*(对白|声音|音频|【声音】)/.test(line)).join('\n')
}
const arrival = plan => plan?.mode === 'observer_reveal' && plan.actorName && plan.observerName && !['inside', 'scripted'].includes(plan.phase)

// A door sound or a future arrival mentioned in a reaction shot does not put
// that actor inside the room. The following authored arrival owns the crossing.
export function doorwayMovementInstruction(shots, shot) {
  const current = roleHandoffPlan(shots, shot)
  if (arrival(current)) {
    return `【入屋路线与落点】${current.actorName}的路线是屋外来路→当前门槛→${current.destination || '观察者所在的同一间屋内'}。新入画时先在屋外显露，再朝${current.observerName}所在入口靠近、跨过门槛，最后按正文停在屋内；三个阶段不能倒放或省略为屋外跑过。不得让来人先从屋内出现、背对屋内观察者跑出门，再在街上回头；不可用转头看门外代替入屋。观察者与来人分别执行各自的动作，保持正文指定的机位，不为说明路线另换入口。`
  }
  const index = shots.findIndex(item => item.id === shot?.id)
  if (index < 0) return ''
  const next = shots[index + 1]
  const incoming = next && roleHandoffPlan(shots, next)
  const body = visualBody(shot)
  const preparesArrival = /[给为][^。；\n]{0,30}(?:从外面|从屋外|从村道|由村道)[^。；\n]{0,20}(?:留出|让出)(?:通道|位置|道路)/.test(body)
  if (!arrival(incoming) || !preparesArrival || !body.includes(incoming.observerName)) return ''
  // An explicit current-shot entrance or exit takes priority over anticipation.
  const withoutPreparation = body.replace(/[给为][^。；\n]{0,30}(?:从外面|从屋外|从村道|由村道)[^。；\n]{0,20}(?:留出|让出)(?:通道|位置|道路)/g, '')
  const actions = shot.actionChain?.requiredActions || shot.actionChain?.required_actions || []
  if (/(?:跑进|跑入|冲进|冲入|奔入|跑出|冲出|离开屋|走进屋)/.test(`${withoutPreparation}\n${Array.isArray(actions) ? actions.join('\n') : ''}`)) return ''
  return `【本镜出场边界】本镜拍${incoming.observerName}听到屋外动静、转向既定门口并在屋内留出通道；“给来人留出通道”是下一镜入屋的铺垫。${incoming.actorName}此刻仍在屋外画外，本镜只用已有脚步或追喊引出注意，不把他提前放到屋内或门槛边，不生成他从屋里往外跑、在门外回头或横穿门口的画面。镜尾停在观察者看向来路的状态；来人从屋外靠近、跨门槛入屋由下一镜按正文完成，不抢拍下一镜动作。`
}
