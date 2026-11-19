// A unique visual alias can recover a missing role reference. Ambiguous aliases
// must be resolved by the user instead of silently choosing another character.
import { stripTransitionBlock } from './narrativeTransition.js'

export function missingShotRoles(shot, assets = []) {
  const prompt = stripTransitionBlock(shot?.prompt)
  const visual = prompt.split('\n').filter(line => !/^\s*(?:对白|旁白|独白|音频|声音|一致性引用|接线单)/.test(line)).join('\n')
  const roles = (assets || []).filter(asset => asset && asset.category === 'role')
  const ids = new Set((shot?.references || []).map(asset => String(asset.id)))
  // Only explicit reference-variant names with one exact canonical role count
  // as the same identity. Similar appearance/age or a shared name prefix is
  // insufficient to merge genuinely different characters.
  const identity = role => {
    const name=String(role.name || '')
    const base=name.replace(/·(?:单人动作参考|单人参考|动作参考|三视图参考|三视图)$/, '')
    if(base!==name){
      const canonical=roles.filter(other=>String(other.name || '')===base)
      if(canonical.length===1)return String(canonical[0].id)
    }
    return String(role.id)
  }
  const selectedIdentities=new Set(roles.filter(role=>ids.has(String(role.id))).map(identity))
  const missing = new Map()
  const ambiguous = []
  const add = role => {
    const key=identity(role)
    if(!selectedIdentities.has(key)&&!missing.has(key))missing.set(key,role)
  }
  // A fully named variant wins over its shorter canonical name in the same
  // sentence; an already selected variant is never silently replaced.
  const named=[]
  for (const role of roles) {
    const names = [role.name, ...(Array.isArray(role.aliases) ? role.aliases : [])].filter(Boolean)
    const matches=names.filter(name=>visual.includes(name))
    if(matches.length)named.push({role,length:Math.max(...matches.map(name=>name.length))})
  }
  named.sort((a,b)=>b.length-a.length).forEach(({role})=>add(role))
  for (const alias of ['少年', '少女', '老者', '老人']) {
    if (!visual.includes(alias)) continue
    const candidates = roles.filter(role => [role.name, role.appearance, role.description].filter(Boolean).join(' ').includes(alias))
    const groups=new Map()
    for(const role of candidates){const key=identity(role);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(role)}
    if(groups.size===1){
      const [key,variants]=[...groups][0]
      add(roles.find(role=>String(role.id)===key)||variants[0])
    }
    if(groups.size>1 && ![...groups.keys()].some(key=>selectedIdentities.has(key)||missing.has(key)))ambiguous.push(alias)
  }
  return { missing: [...missing.values()], ambiguous }
}

export function durationValidation(expected, actual) {
  expected = Number(expected)
  actual = Math.round(Number(actual) * 100) / 100
  const passed = Number.isFinite(actual) && actual > 0 && Math.abs(actual - expected) <= Math.max(.5, expected * .05)
  return { passed, expectedDuration: expected, actualDuration: actual,
    reason: passed ? '' : `请求 ${expected} 秒，实际返回 ${actual} 秒，未通过单镜时长验收` }
}
