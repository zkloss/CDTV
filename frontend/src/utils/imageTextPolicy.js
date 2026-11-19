export const IMAGE_TEXT_OPTIONS = [
  { value: 'specified', label: '只用提示词明确指定的文字' },
  { value: 'none', label: '无文字底图（文字后期添加）' },
  { value: 'exact', label: '使用下方指定文字' },
]

export function imageTextPolicy(asset = {}, general = false) {
  if (!general || asset.category === 'audio') return ''
  const mode = asset.imageTextMode || 'specified'
  if (mode === 'none') return '【画面文字约束】这是一张无文字底图。只生成背景、材质、构图和光影，不绘制任何标题、标语、字母、数字、Logo或水印；字卡文字后期另加。原描述中的字体和排字效果仅表示留白与视觉风格，不代表允许自行写字。'
  if (mode === 'exact') {
    const text = String(asset.imageText || '').trim()
    if (!text) throw new Error('请填写图片中需要显示的文字原文，或改选无文字底图')
    return `【画面文字约束】唯一允许的画面文字原文为：${JSON.stringify(text)}。逐字保留，不改写、不翻译、不增删，不增加其他标题、标语、说明、示例文案或水印。原描述中的排字只用于呈现这段原文。`
  }
  return '【画面文字约束】仅绘制提示词明确要求显示、并且给出具体原文的文字，逐字保留。若只描述字体、大字、压印、排字、标语版式等风格但没有给出文字原文，必须留白，不得自行补写标题、标语或示例文案。不得根据项目风格或主题联想新的文字；不添加水印。'
}

export function withImageTextPolicy(prompt, asset, general = false) {
  const policy = imageTextPolicy(asset, general)
  return [String(prompt || '').trim(), policy].filter(Boolean).join('\n\n')
}
