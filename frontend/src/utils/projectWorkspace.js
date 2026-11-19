export const GENERAL_VIDEO_TYPES = [
  { value: 'commercial', label: '产品宣传', description: '功能演示、产品上新、商业广告' },
  { value: 'promo', label: '品牌形象', description: '品牌故事、企业形象、活动宣传' },
  { value: 'science', label: '知识科普', description: '知识讲解、原理展示、步骤教学' },
  { value: 'lifestyle', label: '生活记录', description: '生活分享、旅行、美食与日常' },
  { value: 'documentary', label: '专题纪录', description: '人文观察、纪实与专题内容' },
  { value: 'short_video', label: '创意短视频', description: '创意表达、活动预告与社交短片' },
]

export function projectWorkspace(project) {
  if (project?.workspace === 'stickman' || project?.type === 'stickman' || String(project?.style || '').startsWith('stickman-')) return 'stickman'
  if (project?.workspace === 'general') return 'general'
  return GENERAL_VIDEO_TYPES.some(option => option.value === project?.type) ? 'general' : 'drama'
}

export const generalTypeName = project => {
  if (project?.type === 'stickman' || String(project?.style || '').startsWith('stickman-')) return '墨柴火柴人'
  return GENERAL_VIDEO_TYPES.find(option => option.value === project?.type)?.label || '通用视频'
}
