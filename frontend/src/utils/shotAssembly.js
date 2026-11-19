export function assemblySources(clips = []) {
  return clips.map((clip, index) => ({
    fileId: String(clip.fileId || ''),
    shotId: String(clip.id || ''),
    title: String(clip.title || `分镜 ${index + 1}`),
    duration: Number(clip.duration) || 0,
    description: String(clip.description || '').trim(),
  }))
}

export function assemblyProblem(clips = []) {
  if (clips.length < 2) return '请在视频轨道中至少保留两段已生成的分镜视频。'
  if (clips.length > 12) return '当前一次最多组装12段视频，请在左侧隐藏多余片段后分批组片。'
  if (clips.some(clip => clip.exportBlocked)) return '选中的分镜有未通过人物或场景参考检查的候选，请先修正或取消选择。'
  if (clips.some(clip => !clip.fileId)) return '有片段尚未入库，不能只用预览地址组片，请先将原视频导入对应分镜。'
  return ''
}

export function assemblyPrompt(sources, requirements = '') {
  return [
    '以已上传的分镜视频为主要素材，完成导演式组片；遇到接不上的镜头时，自行生成必要的短过渡画面，再接回原素材。',
    '保持关键事件先后与剧情因果，不必逐镜原样照搬、每镜等长或沿原边界硬切。可以调整切点、镜头长短、局部动作与反应，删去冗余停顿。',
    '逐一检查相邻镜头的人物位置、视线、手部与道具、动作阶段、机位及声音。能自然剪接就剪接；无法仅靠剪辑接顺时，主动补出缺失动作或短过渡镜头，不必等用户逐处指出。不要仍然硬拼，也不要只用叠化、黑场或静帧掩盖跳变。',
    '补生成只连接原剧情，保持人物身份、场景空间、天气、道具状态和关键动作结果，不新增实质剧情或角色，不重新拍摄整部作品。',
    '补段必须同时接住上一镜的真实切出状态与下一镜的真实切入状态，先确定两个端点再生成；可以调整原切点，但要重新从原视频取两端参考，不能只延续上一镜后自由结束。',
    '人物脸型、五官比例、衣服、表情幅度、手与道具、视线、景别、机位、曝光和色温都向两侧原片靠齐。不擅自放大眼睛、强化惊讶或添加大片强光，特效的强度和出现时机也应匹配。',
    '分别检查上一镜→补段、补段→下一镜，两头都自然才交付；后端不匹配就重做或重剪该补段，不要只接好前端。',
    '覆盖全部所选片段的有效剧情，保留完整关键对白、说话人及原配音；可让原声音跨镜延续，不截词、不重复台词、不擅自重新配音。不能把某一段源视频直接当作完整结果。',
    '总时长可随修剪冗余和补过渡自然变化，不强制等于源视频时长之和。',
    ...sources.map((source, index) => `${index + 1}. ${source.title}`),
    String(requirements || '').trim() ? `补充剪辑要求：\n${String(requirements).trim()}` : '',
  ].filter(Boolean).join('\n')
}
