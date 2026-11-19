import MANJU_GENRES from '../utils/manjuGenresCatalog.json'

export const OFFICIAL_MANJU_GENRES = MANJU_GENRES

export const PROJECT_GENRE_CATEGORIES = [
  { id: 'all', label: '全部题材 (21)' },
  { id: '幻想', label: '幻想世界 (5)', icon: '🗡️' },
  { id: '古代', label: '古代风云 (6)', icon: '📜' },
  { id: '现代', label: '现代都市 (8)', icon: '🏙️' },
  { id: '类型片', label: '类型悬疑 (2)', icon: '🔍' },
]

export const PROJECT_TYPE_OPTIONS = [
  { label: '连续短剧 / 漫剧', value: 'drama', icon: '🎬', desc: '多集剧集、人物对白、情节冲突推进与连贯故事' },
  { label: '墨柴工坊 / 火柴人剧场', value: 'stickman', icon: '🤺', desc: '极简黑白高对比、动作打击感、魔性脑洞反转与爆款微剧' },
  { label: '品牌 / 形象宣传片', value: 'promo', icon: '🌟', desc: '企业品牌、宏大开篇、恢弘航拍、愿景展示与史诗节奏' },
  { label: '商业广告 / 产品宣传', value: 'commercial', icon: '🛍️', desc: '黄金3秒抓人、卖点特写、痛点解决、视觉轰炸与购买号召 CTA' },
  { label: '创意短视频 / 爆款自媒体', value: 'short_video', icon: '⚡', desc: '强情绪共鸣、快节奏视觉反转、网梗叙事与高密爆点' },
  { label: '专题纪录片 / 科普专题', value: 'documentary', icon: '📽️', desc: '客观纪实质感、深邃旁白解说、宏观微观交织与知识呈现' },
]

export const LEGACY_PROJECT_STYLE_GROUPS = [
  { label: '商业与宣传', options: [
    { label: '科技未来', value: 'tech-future', desc: '商业科技大片质感，极简深灰冷调，光纤流动，发光HUD数字光效，精密机械微距，金属反光，4K超清画质，无水印文字。' },
    { label: '高级奢华', value: 'luxury-high', desc: '高端奢华广告质感，高级暖光与侧逆光，细腻光影雕琢，微距景深，丝绸与贵金属材质，电影级调色，高贵典雅，4K画质。' },
    { label: '现代生活', value: 'lifestyle-warm', desc: '现代商业生活广告质感，自然阳光漫射，温暖通透氛围，轻松明快，人物自然笑容，生动生活气息，浅景深摄影。' },
    { label: '恢弘史诗', value: 'epic-brand', desc: '大片级宏大宣传片质感，壮阔航拍大广角，天光破云，丁达尔光束，慢门流光，震撼视界，电影宽银幕质感，4K画质。' },
    { label: '纪实人文', value: 'documentary-real', desc: '人文纪录片质感，自然环境光，深沉低饱和纪实影调，胶片颗粒，真实纹理，深刻厚重视觉呈现，4K无水印。' },
  ] },
  { label: '3D国漫', options: [
    { label: '修仙玄幻', value: '3d-xiuxian', desc: '3D国漫玄幻CG风格，3D国漫玄幻风格，东方仙侠世界观，仙府楼阁、悬空仙山、丹药法宝、飞剑御空、渡劫天雷，电影级光影，8K画质，UE5渲染，PBR材质，全局光照，体积光，柔和电影光影，国风玄幻美术风格，仙侠游戏CG，高级低饱和色调，细节丰富，无文字，无水印' },
    { label: '武侠', value: '3d-wuxia', desc: '3D国漫武侠CG风格，3D国漫武侠风格，东方江湖世界观，竹林古寺、飞檐客栈、雨夜长街、刀光剑影、内力气劲，电影级光影，8K画质，UE5渲染，PBR材质，全局光照，体积光，柔和电影光影，国风武侠美术风格，武侠游戏CG，高级低饱和色调，细节丰富，无文字，无水印' },
    { label: '神话', value: '3d-myth', desc: '3D国漫神话CG风格，3D国漫神话风格，上古洪荒世界观，天宫瑶池、神兽异种、封神战场、法宝神通、混沌星河，电影级光影，8K画质，UE5渲染，PBR材质，全局光照，体积光，恢弘史诗光影，国风神话美术风格，神话游戏CG，高级低饱和色调，细节丰富，无文字，无水印' },
  ] },
  { label: '真人写实', options: [
    { label: '都市', value: 'real-urban', desc: '真人写实摄影风格，电影级画质。现代都市，摩天大楼、霓虹夜景、职场穿搭、豪车公寓，自然光影，4K，高细节。' },
    { label: '年代', value: 'real-era', desc: '真人写实摄影风格，电影级画质。年代复古，老街巷弄、旗袍中山装、搪瓷茶缸、绿皮火车，怀旧暖色调，4K，高细节。' },
    { label: '悬疑', value: 'real-mystery', desc: '真人写实摄影风格，电影级画质。悬疑推理，雨夜暗巷、老旧档案室、微光手电、蛛丝马迹，冷色调暗黑氛围，4K，高细节。' },
    { label: '重生', value: 'real-rebirth', desc: '真人写实摄影风格，电影级画质。重生逆袭，校园重聚、商战博弈、时空交错闪回，情感细腻光影，4K，高细节。' },
  ] },
  { label: '二次元', options: [
    { label: '校园', value: 'anime-school', desc: '二次元动画风格，日系赛璐璐上色。青春校园，教室走廊、樱花操场、制服书包、社团活动，明亮通透色调，高细节。' },
    { label: '异世界', value: 'anime-isekai', desc: '二次元动画风格，日系赛璐璐上色。异世界冒险，魔法阵、精灵兽、古城遗迹、技能特效，奇幻绚丽色彩，高细节。' },
    { label: '恋爱', value: 'anime-romance', desc: '二次元动画风格，日系赛璐璐上色。恋爱日常，咖啡馆、天台夕阳、烟花祭典、牵手奔跑，柔和唯美画风，高细节。' },
    { label: '热血', value: 'anime-action', desc: '二次元动画风格，日系赛璐璐上色。热血战斗，能量爆发、速度线、技能对轰、废墟硝烟，动态强对比光影，高细节。' },
  ] },
  { label: 'Q版', options: [
    { label: '萌宠', value: 'chibi-pet', desc: 'Q版3D卡通风格，可爱圆润造型，大眼短肢比例。萌宠日常，毛茸茸质感、爪子肉垫、歪头杀、打滚撒娇，明亮饱和色调，高细节。' },
    { label: '搞笑', value: 'chibi-comedy', desc: 'Q版3D卡通风格，可爱圆润造型，大眼短肢比例。搞笑沙雕，夸张表情包、翻白眼、石化裂开、汗滴特效，趣味撞色画风，高细节。' },
    { label: '儿童', value: 'chibi-kids', desc: 'Q版3D卡通风格，可爱圆润造型，大眼短肢比例。儿童故事，积木玩具、彩虹气球、动物朋友、睡前故事，温馨柔和色调，高细节。' },
    { label: '轻喜剧', value: 'chibi-sitcom', desc: 'Q版3D卡通风格，可爱圆润造型，大眼短肢比例。轻松喜剧，办公室摸鱼、外卖日常、室友互怼、猫狗大战，柔和明快画风，高细节。' },
  ] },
]

export const PROJECT_RATIO_OPTIONS = [
  { label: '21:9', value: '21:9', shape: 'ultrawide' },
  { label: '16:9', value: '16:9', shape: 'landscape' },
  { label: '4:3', value: '4:3', shape: 'classic' },
  { label: '1:1', value: '1:1', shape: 'square' },
  { label: '3:4', value: '3:4', shape: 'portrait3' },
  { label: '9:16', value: '9:16', shape: 'portrait9' },
]

function legacyGetProjectStyleDescription(style) {
  for (const group of LEGACY_PROJECT_STYLE_GROUPS) {
    const option = group.options.find(item => item.value === style)
    if (option) return option.desc
  }
  if (style === '3d-xuanhuan') {
    return '3D国漫玄幻CG风格，3D国漫玄幻风格，东方修真世界观，仙府楼阁、丹药法宝、飞剑御空、渡劫天雷，电影级光影，8K画质，UE5渲染，细节丰富。'
  }
  return ''
}

function legacyGetProjectStyleName(style) {
  for (const group of LEGACY_PROJECT_STYLE_GROUPS) {
    const option = group.options.find(item => item.value === style)
    if (option) return `${group.label} · ${option.label}`
  }
  if (style === '3d-xuanhuan') return '3D国漫 · 修仙玄幻'
  return style || '3D国漫'
}

export function getProjectTypeOption(type) {
  return PROJECT_TYPE_OPTIONS.find(item => item.value === type) || PROJECT_TYPE_OPTIONS[0]
}

function legacyGetProjectStylePrefix(style) {
  const map = {
    'tech-future': '商业科技大片质感，极简深灰冷调，光纤流动与发光HUD光效，4K超清画质',
    'luxury-high': '高端奢华广告摄影，高级暖光与侧逆光，细腻光影雕琢，4K电影级调色',
    'lifestyle-warm': '现代生活广告质感，自然阳光漫射，温暖通透氛围，轻松明快摄影',
    'epic-brand': '大片级宏大宣传片质感，壮阔航拍大广角，天光破云，丁达尔光束，4K宽银幕',
    'documentary-real': '人文纪录片质感，自然环境光，低饱和纪实影调，深刻真实纹理',
    '3d-xiuxian': '3D国漫玄幻CG风格，3D国漫玄幻风格，电影级光影，8K画质，UE5渲染',
    '3d-wuxia': '3D国漫武侠CG风格，3D国漫武侠风格，电影级光影，8K画质，UE5渲染',
    '3d-myth': '3D国漫神话CG风格，3D国漫神话风格，电影级光影，8K画质，UE5渲染',
    '3d-xuanhuan': '3D国漫玄幻CG风格，3D国漫玄幻风格，电影级光影，8K画质，UE5渲染',
    'real-urban': '真人写实都市摄影，电影级质感，自然光影',
    'real-era': '真人写实年代复古摄影，胶片电影质感',
    'real-mystery': '真人写实悬疑暗黑摄影，电影级冷色调光影',
    'real-rebirth': '真人写实摄影，电影级细腻画质',
    'anime-school': '二次元动画风格，日系赛璐璐上色，明亮通透色调',
    'anime-isekai': '二次元奇幻冒险动画风格，日系赛璐璐上色',
    'anime-romance': '二次元唯美恋爱动画风格，柔和光影',
    'anime-action': '二次元热血战斗动画风格，动态强对比光影',
    'chibi-pet': 'Q版3D萌宠卡通风格，可爱圆润建模',
    'chibi-comedy': 'Q版3D搞笑卡通风格，趣味表情建模',
    'chibi-kids': 'Q版3D儿童卡通风格，温馨柔和建模',
    'chibi-sitcom': 'Q版3D轻喜剧卡通风格，明快建模',
  }
  return map[style] || ''
}

// Visual treatment and story subject are independent. Legacy combined values
// remain readable without changing existing projects or generated assets.
export const DEFAULT_PROJECT_STYLE = '3d-anime'

// 专属于短剧创作的画面风格分组（已剔除墨柴工坊的火柴人与通用视频的商业视觉，只保留短剧所需风格）
export const PROJECT_STYLE_GROUPS = [
  { label: '3D 动画', options: [
    { value: '3d-anime', label: '3D 动漫', desc: '3D动漫CG画面，自然人物比例，细致建模与材质，电影感光影；服装、场景、年代和天气按剧本设定。', prefix: '3D动漫CG风格，自然人物比例，细致建模与材质，电影感光影' },
    { value: '3d-cartoon', label: '3D 卡通', desc: '风格化3D卡通画面，简洁鲜明的造型、柔和材质与有层次的配色，适用于各类故事。', prefix: '风格化3D卡通，简洁鲜明造型，柔和材质，层次清晰的配色' },
    { value: '3d-realistic', label: '写实 CG', desc: '写实3D CG画面，可信的人体与物理材质，细致纹理和自然的电影感光影。', prefix: '写实3D CG，可信人体比例与物理材质，细致纹理，电影感光影' },
    { value: 'chibi-cartoon', label: 'Q版 3D', desc: 'Q版3D卡通，圆润造型与大头短身比例，画面清晰；具体表演强度按剧情安排。', prefix: 'Q版3D卡通，圆润造型，大头短身比例，清晰细腻的材质' },
  ] },
  { label: '2D 动画', options: [
    { value: 'anime-cel', label: '赛璐璐动漫', desc: '2D赛璐璐动画，清晰线稿与分层色块，角色造型稳定，光色随剧情环境变化。', prefix: '2D赛璐璐动画，清晰线稿，分层色块，稳定角色造型' },
    { value: 'anime-chinese', label: '国风 2D', desc: '国风2D动画，讲究线条与构图，融入东方美术语言；不预设古代或修仙题材。', prefix: '国风2D动画，精致线条，东方美术语言，讲究构图与色彩层次' },
    { value: 'anime-retro', label: '复古手绘动画', desc: '复古2D手绘动画，温润笔触与手绘纹理，保留自然的线条变化。', prefix: '复古2D手绘动画，温润笔触，手绘纹理，自然线条变化' },
  ] },
  { label: '写实影像', options: [
    { value: 'real-cinematic', label: '真人电影感', desc: '真人写实电影摄影，人物肤质与空间尺度自然，细致影调；具体年代、光照与天气由剧情决定。', prefix: '真人写实电影摄影，自然肤质与空间尺度，细致电影影调' },
    { value: 'real-documentary', label: '纪实摄影', desc: '纪实摄影，可信的生活纹理与自然环境光，克制构图，保持现场感。', prefix: '纪实摄影，自然环境光，可信生活纹理，克制构图与现场感' },
  ] },
  { label: '绘画与手作', options: [
    { value: 'ink-painting', label: '水墨', desc: '水墨画面，墨色层次、干湿笔触与留白；人物和场景保持统一的水墨表现。', prefix: '水墨画面，墨色层次，干湿笔触，讲究留白与构图' },
    { value: 'watercolor', label: '水彩', desc: '水彩插画，透明叠色、纸张肌理与柔和笔触，造型和配色保持统一。', prefix: '水彩插画，透明叠色，纸张肌理，柔和笔触' },
    { value: 'storybook', label: '绘本插画', desc: '绘本插画，统一的手绘造型、细腻纹理与清晰叙事构图。', prefix: '绘本插画，统一手绘造型，细腻纹理，清晰叙事构图' },
    { value: 'stop-motion', label: '黏土／定格', desc: '手工黏土与定格动画质感，可见材料纹理，统一角色造型与微缩场景尺度。', prefix: '手工黏土定格动画质感，可见材料纹理，微缩场景，统一角色造型' },
    { value: 'pixel-art', label: '像素风', desc: '像素美术，清晰像素网格、统一像素尺度与有限调色板，保持角色和场景的像素语言。', prefix: '像素美术，清晰像素网格，统一像素尺度，有限调色板' },
  ] },
  { label: '自定义', options: [{ value: 'custom-style', label: '自定义画面风格', desc: '描述你要的画面表现、材质、线条或参考方向，故事内容单独选择。', prefix: '' }] },
]

// 兼容其它模块（墨柴火柴人、通用视频商业视觉）用于历史项目反查，不影响短剧新建选择
export const OTHER_STYLE_GROUPS = [
  { label: '墨柴火柴人', options: [
    { value: 'stickman-explainer', label: '角色解说', desc: 'B5标准角色人物解说，右下角极简IP出镜讲话，左侧火柴人舞台图解，因果物理喜剧。', prefix: 'B5角色人物解说，右下角极简卡通IP形象出镜解说，左侧黑色墨线火柴人舞台高能图解，暖纸墨线红点缀，动态大标题' },
    { value: 'stickman-survival', label: '末日求生', desc: 'B4官方求生短剧风，丧尸末日、危机悬疑与绝境逃生。', prefix: 'B4求生短剧风，丧尸末日与危机悬疑，白圆头黑骨骼白手套，细腻全彩2D手绘末日废墟环境，冷峻悬疑压迫感' },
    { value: 'stickman-action', label: '热血格斗', desc: '经典黑白火柴人体术格斗，黑白极简高对比，带半透明速度线与冲击波特效，高帧率丝滑连贯物理运动，行云流水无顿挫。', prefix: '经典黑白火柴人动作格斗，纯白背景高对比，粗黑线条，动态武术体术，夸张速度线与打击冲击波，局部高光特效' },
    { value: 'stickman-classic', label: '经典极简', desc: '纯白底高对比黑线条火柴人，极简肢体语言与符号化表情，干净利落，流畅动作。', prefix: '经典极简黑白火柴人动画，纯白背景，纯黑流畅线条，生动肢体语言，极简线条美学，4K画质' },
    { value: 'stickman-comedy', label: '爆笑沙雕', desc: '魔性搞笑火柴人，夸张失重姿态与搞笑表情包，无厘头滑稽动作，单色亮彩道具点缀。', prefix: '魔性爆笑火柴人搞笑动画，夸张幽默肢体姿态，粗黑线条，单色亮彩道具点缀，白净背景，沙雕卡通物理' },
    { value: 'stickman-cyber', label: '赛博霓虹', desc: '暗黑模式赛博火柴人，纯黑夜背景，发光蓝粉霓虹线条，光轨残影，高科技能量光刃。', prefix: '暗黑赛博朋克火柴人，纯黑背景，发光青蓝与紫红霓虹线条，能量残影，高科技光刃，电影级暗色调' },
    { value: 'stickman-wuxia', label: '水墨武侠', desc: '传统中国写意水墨火柴人，微黄宣纸底色，草书行笔挥毫，剑走龙蛇，泼墨剑气。', prefix: '传统中国水墨风火柴人，写意泼墨背景，书法草书笔触线条，武侠体术与剑气，飘逸空灵意境，动作连续流动' },
  ] },
  { label: '商业视觉', options: LEGACY_PROJECT_STYLE_GROUPS[0].options },
]

export const ALL_PROJECT_STYLE_GROUPS = [
  ...PROJECT_STYLE_GROUPS,
  ...OTHER_STYLE_GROUPS,
]

export const PROJECT_GENRE_OPTIONS = [
  ...MANJU_GENRES.map(g => ({
    value: g.id,
    label: g.name,
    category: g.category,
    icon: g.icon,
    desc: g.desc,
    pacing: g.pacing,
    folder: g.folder,
    isOfficial: true,
  })),
  { value: 'xianxia', label: '修仙玄幻', alias: 'xuanhuan' },
  { value: 'apocalypse', label: '末日废土', alias: 'moshi' },
  { value: 'rebirth', label: '重生', alias: 'chongsheng' },
  { value: 'time-travel', label: '穿越', alias: 'chuanyue' },
  { value: 'urban', label: '都市', alias: 'dushi' },
  { value: 'period', label: '年代', alias: 'niandai' },
  { value: 'school', label: '校园', alias: 'xiaoyuan' },
  { value: 'romance', label: '恋爱', alias: 'tianchong' },
  { value: 'suspense', label: '悬疑', alias: 'xuanyi' },
  { value: 'business', label: '商战', alias: 'shangzhan' },
  { value: 'family', label: '家庭', alias: 'jiating' },
  { value: 'sci-fi', label: '科幻', alias: 'xingji' },
  { value: 'fantasy', label: '奇幻', alias: 'xihuan' },
  { value: 'historical', label: '古装历史', alias: 'quanmou' },
  { value: 'growth', label: '成长', alias: 'dushi' },
  { value: 'adventure', label: '冒险', alias: 'xihuan' },
  { value: 'action', label: '热血战斗', alias: 'xuanhuan' },
  { value: 'isekai', label: '异世界', alias: 'xihuan' },
  { value: 'pets', label: '萌宠' },
  { value: 'kids', label: '儿童故事' },
  { value: 'science', label: '科普' },
  { value: 'humanities', label: '人文纪实' },
  { value: 'brand', label: '品牌故事' },
  { value: 'product', label: '产品展示' },
]

const LEGACY_PROFILE = {
  '3d-xiuxian': ['3d-anime', 'xianxia'], '3d-xuanhuan': ['3d-anime', 'xianxia'],
  '3d-wuxia': ['3d-anime', 'wuxia'], '3d-myth': ['3d-anime', 'myth'],
  'real-urban': ['real-cinematic', 'urban'], 'real-era': ['real-cinematic', 'period'],
  'real-mystery': ['real-cinematic', 'suspense'], 'real-rebirth': ['real-cinematic', 'rebirth'],
  'anime-school': ['anime-cel', 'school'], 'anime-isekai': ['anime-cel', 'isekai'],
  'anime-romance': ['anime-cel', 'romance'], 'anime-action': ['anime-cel', 'action'],
  'chibi-pet': ['chibi-cartoon', 'pets'], 'chibi-comedy': ['chibi-cartoon', 'comedy'],
  'chibi-kids': ['chibi-cartoon', 'kids'], 'chibi-sitcom': ['chibi-cartoon', 'comedy'],
}
const profileOf = value => value && typeof value === 'object' ? value : { style: value }
const styleCode = value => String(profileOf(value).style || '').trim()
const visualOption = value => ALL_PROJECT_STYLE_GROUPS.flatMap(group => group.options).find(option => option.value === styleCode(value))
export const isLegacyProjectStyle = value => Boolean(LEGACY_PROFILE[styleCode(value)])
export const getProjectVisualChoice = value => LEGACY_PROFILE[styleCode(value)]?.[0] || styleCode(value) || DEFAULT_PROJECT_STYLE

export function getProjectGenres(project) {
  const profile = profileOf(project)
  const raw = Array.isArray(profile.storyGenres) ? profile.storyGenres : LEGACY_PROFILE[styleCode(profile)]?.slice(1) || []
  return [...new Set(raw.filter(value => typeof value === 'string').map(value => value.trim()).filter(Boolean))]
}
export const getProjectGenreName = value => PROJECT_GENRE_OPTIONS.find(option => option.value === value)?.label || String(value || '')

export function projectStyleFields(project = {}) {
  return { style: styleCode(project) || DEFAULT_PROJECT_STYLE, storyGenres: getProjectGenres(project),
    styleNotes: String(profileOf(project).styleNotes || '').trim() }
}

export function validateProjectStyle(project) {
  if (styleCode(project) === 'custom-style' && !String(profileOf(project).styleNotes || '').trim()) {
    throw new Error('请描述自定义画面风格，或选择一个预设画面风格')
  }
}

export function getProjectStyleName(project) {
  const style = styleCode(project)
  if (isLegacyProjectStyle(style)) return legacyGetProjectStyleName(style)
  return visualOption(style)?.label || style || '未指定画面风格'
}

export function getProjectStyleDescription(project) {
  const profile = profileOf(project), style = styleCode(profile), notes = String(profile.styleNotes || '').trim()
  const base = style === 'custom-style' ? '' : isLegacyProjectStyle(style)
    ? legacyGetProjectStyleDescription(style) : visualOption(style)?.desc || style
  return [base, notes].filter(Boolean).join('；')
}

export function getProjectStylePrefix(project) {
  const profile = profileOf(project), style = styleCode(profile), option = visualOption(style)
  const base = style === 'custom-style' ? '' : isLegacyProjectStyle(style)
    ? legacyGetProjectStylePrefix(style) : option?.prefix || (option ? legacyGetProjectStylePrefix(style) : style)
  return [base, String(profile.styleNotes || '').trim()].filter(Boolean).join('，')
}

export function getProjectStyleSummary(project) {
  const name = getProjectStyleName(project)
  return [name, ...getProjectGenres(project).map(getProjectGenreName).filter(label => !name.includes(label))].join(' · ')
}

export function getProjectGenreInstruction(project) {
  const genres = getProjectGenres(project)
  const genreNames = genres.map(getProjectGenreName)
  const officialItems = genres.map(v => OFFICIAL_MANJU_GENRES.find(g => g.id === v || g.name === v)).filter(Boolean)
  const pacingHints = officialItems.map(g => `【${g.name}节奏律】${g.pacing}`).join('；')
  
  let text = `故事题材：${genreNames.join('、') || '按项目简介与用户要求确定'}。画面风格：${getProjectStyleDescription(project) || '按项目要求确定'}。`
  if (pacingHints) {
    text += ` 漫剧导演节奏律：${pacingHints}。`
  }
  text += `画面表现与故事题材分别执行，题材不改变所选画风，具体内容以项目简介和剧本为准。`
  return text
}
