<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import UiSelect from './UiSelect.vue'
import HUASHU_DEFAULT_TEMPLATES from '../utils/huashuTemplates.json'
import HuashuMotionStudio from './HuashuMotionStudio.vue'
import { STICKMAN_STYLES, STICKMAN_CATEGORIES, getStickmanStyleConfig } from '../utils/stickmanStyles.js'
import { desktopBackendRequest } from '../utils/desktopApi.js'

const props = defineProps({
  projectId: { type: String, required: true },
  mode: { type: String, default: 'stickman' }, // 'stickman' | 'general'
  token: String,
  apiBase: String,
  storageBase: String,
  selectedAccountId: String,
  videoModel: String,
})

const emit = defineEmits(['back', 'request-model-settings'])

const loading = ref(true)
const busy = ref('')
const error = ref('')
const message = ref('')

const project = ref(null)
const prompt = ref('')
const duration = ref(15)
const ratio = ref('16:9')
const selectedStyle = ref('commercial')
const videoModels = ref([])
const textModels = ref([])
const selectedModel = ref('')
const referenceImage = ref(null)

const effectiveStorageBase = ref(props.storageBase || '')
const effectiveApiBase = ref(props.apiBase || '')
const aiExpanding = ref(false)

const generating = ref(false)
const taskProgress = ref(0)
const taskStatusText = ref('')
const currentTaskId = ref('')
const currentVideoUrl = ref('')
const currentResult = ref(null)
const historyVersions = ref([])
let pollTimer = null

const activeEngine = ref('ai_video')

const isStickman = computed(() => {
  return props.mode === 'stickman' || project.value?.workspace === 'stickman' || project.value?.type === 'stickman'
})

// 花叔模版绑定与套用状态
const selectedHuashuTemplateId = ref('object-3d')
const autoPackageHuashu = ref(true)
const packagingHuashu = ref(false)

const selectedHuashuTemplate = computed(() => {
  return HUASHU_DEFAULT_TEMPLATES.find(t => t.id === selectedHuashuTemplateId.value) || HUASHU_DEFAULT_TEMPLATES[0]
})

const currentHuashuTemplateName = computed(() => {
  return selectedHuashuTemplate.value?.name || '3D 空间立体产品展示'
})

// 画面风格看板与分类
const stickmanCategories = STICKMAN_CATEGORIES
const activeStyleCategory = ref('all')
const showStyleGrid = ref(false)
const selectedPresetKey = ref('')

const generalStyles = [
  { value: 'commercial', label: '商业高级', tag: '产品特写 / 光影律动 / 简约大气', catLabel: '商业视觉' },
  { value: 'tech-future', label: '科技未来', tag: '全息光影 / 数据流 / 现代质感', catLabel: '科技数码' },
  { value: 'science', label: '知识科普', tag: '步骤解构 / 图解说明 / 动态演示', catLabel: '科普演示' },
  { value: 'cinematic', label: '影视纪实', tag: '电影画质 / 情绪镜头 / 自然光影', catLabel: '影视质感' },
]

const stickmanStyles = STICKMAN_STYLES

const filteredStickmanStyles = computed(() => {
  if (activeStyleCategory.value === 'all') return stickmanStyles
  return stickmanStyles.filter(s => s.category === activeStyleCategory.value)
})

const currentStyleConfig = computed(() => {
  if (isStickman.value) {
    return getStickmanStyleConfig(selectedStyle.value)
  }
  return generalStyles.find(s => s.value === selectedStyle.value) || generalStyles[0]
})

const styleSelectOptions = computed(() => {
  const list = isStickman.value ? filteredStickmanStyles.value : generalStyles
  return list.map(s => ({
    value: s.value,
    label: `${s.label} · ${s.tag || ''} ${s.catLabel ? '(' + s.catLabel + ')' : ''}`,
  }))
})

function onChooseStyle(styleVal) {
  selectedStyle.value = styleVal
  if (isStickman.value) {
    const oldConf = getStickmanStyleConfig(selectedStyle.value)
    const newConf = getStickmanStyleConfig(styleVal)
    if (!prompt.value.trim() || prompt.value.trim() === oldConf?.defaultPrompt?.trim()) {
      if (newConf?.defaultPrompt) {
        prompt.value = newConf.defaultPrompt
      }
    }
  }
}

watch(() => props.storageBase, (val) => {
  if (val) {
    effectiveStorageBase.value = val
    if (currentResult.value) {
      currentVideoUrl.value = resolveVideoUrl(currentResult.value)
    }
  }
})

watch(() => props.apiBase, (val) => {
  if (val) effectiveApiBase.value = val
})

function getStorageBase() {
  return String(effectiveStorageBase.value || props.storageBase || '').replace(/\/+$/, '')
}

function resolveVideoUrl(v) {
  if (!v) return ''
  let u = String(v.url || '').trim()
  let fid = String(v.fileId || '').trim()

  const m = u.match(/\/file\/([^/?#]+)/)
  if (m) {
    fid = fid || m[1]
  }

  const base = getStorageBase()

  if (fid) {
    return base ? `${base}/file/${fid}/download` : `/file/${fid}/download`
  }

  if (u.includes('/file/')) {
    const rel = u.substring(u.indexOf('/file/'))
    return base ? `${base}${rel}` : rel
  }

  if (u.startsWith('/')) {
    return base ? `${base}${u}` : u
  }

  return u
}

async function onVideoError(e) {
  console.warn('视频加载异常，尝试刷新当前存活存储服务地址:', currentVideoUrl.value, e)
  if (window.pywebview?.api?.get_app_info) {
    try {
      const info = await window.pywebview.api.get_app_info()
      if (info?.storageBase && info.storageBase !== effectiveStorageBase.value) {
        effectiveStorageBase.value = info.storageBase
        if (currentResult.value) {
          currentVideoUrl.value = resolveVideoUrl(currentResult.value)
        }
      }
    } catch (_) {}
  }
}

function getHuashuTemplatePrompt(tId, name) {
  const pName = name || '品牌高端产品'
  switch (tId) {
    case 'object-3d':
      return `大厂发布会旗舰级商业大片：围绕【${pName}】的多机位电影工业运镜：\n1.【0-3s 极速微距飞掠】：微距探针镜头以极浅景深贴壁疾速掠过产品瓶身与金属金线细节，侧逆强光横扫表面，鎏金高光拉出耀眼光芒；\n2.【3-8s 360度低角度环绕】：摄影机以微仰低角度展开疾速而平滑的360度环绕旋转，深空暗黑展台上高光沿产品轮廓与浮雕Logo剧烈流淌，强光影明暗交错，做工与质感纤毫毕现；\n3.【8-12s 悬浮动态光爆发】：主体在空中悬浮微震，一道璀璨的暖金体积光穿透背景斜切而下，激荡起微小的金色光尘粒子，极具戏剧张力；\n4.【12-15s 电影感大气定格】：镜头缓缓平滑拉远，产品稳稳落定在极简深色镜面展台正中央，倒影清晰璀璨，顶级大厂发布会压轴质感。`
    case 'keynote-ui':
      return `大厂发布会级高能UI快剪短片：围绕【${pName}】的极致工业级动态呈现：\n1.【0-3s 暗黑高光开篇】：纯黑哑光背景中，核心产品界面化作半透明深色玻璃面板从屏幕深处疾速向前破空飞出，侧边缘亮蓝流光闪烁；\n2.【3-8s 多层卡片弹性切入】：毛玻璃质感功能卡片伴随强节奏弹性切入画面，界面数据图表与高亮指标连环跳动，镜头随卡片快速左右穿梭；\n3.【8-12s 科技光束穿透】：一道耀眼青蓝光束横扫所有界面，流光线条纵横交织，微小发光数据粒子沿路径急速流动，科技爆发力拉满；\n4.【12-15s 发布会完美定格】：所有界面瞬间平滑聚拢融合为产品主视图，高光自中心向外掠过，像素级锐利清晰，顶级科技发布会压轴质感。`
    case 'talking-head':
      return `电影级商业发布会大片底片：围绕【${pName}】展开多层次工业级光影叙事：\n1.【0-4s 沉浸微距启幕】：暗调光影空间中，强束晨光缓缓扫过主体局部与精湛做工，慢动作捕捉微距细节与材质纹理，光斑温润流转；\n2.【4-9s 动态特写穿梭】：摄影机平滑向侧方推进并环绕微仰，强反差轮廓光沿产品边缘流淌，高光微动光晕，彰显非凡传世沉淀；\n3.【9-15s 殿堂级视觉升华】：镜头平滑拉远至中全景，产品端坐于展台中央，顶部柔和体积光倾泻而下，大气沉稳，与60fps动效包装完美咬合。`
    case 'ui-space':
      return `三维空间界面飞掠工业级大片：围绕【${pName}】展开极致空间纵深巡礼：\n1.【0-4s 空间多层悬浮】：真实产品界面拆解为多层透明浮动悬浮面板，在三维深邃空间中如水晶般晶莹排列，纵深感强烈；\n2.【4-10s 3D穿梭飞掠运镜】：3D摄影机疾速穿入各层面板缝隙，沿流光数据轴向前贴近飞掠，精准聚焦高光弹窗与核心数据模块；\n3.【10-15s 悬浮归位与定格】：摄影机由内向外倒飞拉远，多层空间平滑压缩归位为完整平面，高光自上而下扫过，科技未来感十足。`
    case 'kinetic-type':
      return `视觉冲击大字排版快剪大片：围绕【${pName}】展开顶级视觉快节奏攻势：\n1.【0-3s 极速大字破屏】：纯黑背景下，巨大粗黑无衬线排版大字伴随强节奏骤然撞向镜头，速度线与边缘红蓝震颤闪烁；\n2.【3-8s 荧光笔高亮扫视】：荧光金黄笔刷一道划过核心结论，动态高反差几何色块与排版线条在画面两侧以一拍一页的节奏飞速重组；\n3.【8-15s 金句定格震荡】：核心观点与震撼标语居中定格，微弱电流与发光粒子在文字轮廓上跳动，视觉冲击力极强，现代大厂快节奏感。`
    case 'vox-collage':
      return `Vox杂志风深度纪实大片：围绕【${pName}】展开电影级调查解说：\n1.【0-4s 复古桌面平移】：镜头微俯滑行掠过温润的复古纸质桌面，高清截图、老照片与便签纸层叠散落，质感丰富真实；\n2.【4-10s 动态红线与图钉穿针引线】：鲜红的图钉扎入桌面，动态红线如光迹般疾速弹射穿梭连接核心证据链，荧光黄色笔迹圈出关键数据；\n3.【10-15s 全局事实解密定格】：镜头缓缓升起纵观全貌，整条调查网络清晰震撼，兼具严谨事实说服力与顶级视觉趣味。`
    case 'finance-chart':
      return `经济学人级商业增长与数据图表大片：围绕【${pName}】展开高端商务呈现：\n1.【0-4s 纯净坐标轴铺开】：优雅极简深色背景上，精准的白色细线坐标轴与微距网格自左向右平滑展开，刻度微动发光；\n2.【4-10s 数据柱与曲线平滑攀升】：发光金色与天蓝数据柱如摩天大楼般平滑拔地而起，平滑折线随光迹疾速向上攀升，穿越关键阻力位；\n3.【10-15s 关键转折点高光定格】：在最高峰值处迸发柔和高光光晕，弹出大字涨幅注释，令人信服的大厂商业领袖质感。`
    case 'kurzgesagt':
      return `Kurzgesagt风前沿科学科普大片：围绕【${pName}】展开宏大到微观的机理解构：\n1.【0-4s 宏观天体轨道运转】：色彩鲜活深邃的宇宙背景中，发光的核心概念天体周围环绕着精密运行的卫星节点与发光轨道；\n2.【4-10s 极致变焦钻入微观】：摄影机以极速推进穿透天体外壳，直击微观分子结构与流动能量管道，几何原理解构动画层层递进；\n3.【10-15s 理性智慧定格】：镜头回到宏观全局，色彩纯净饱满，极富智慧感与宇宙震撼力，温和理性的科学解说大片。`
    case 'math-3b1b':
      return `3Blue1Brown风格科学与数学大片：围绕【${pName}】展开纯粹几何美学：\n1.【0-4s 纯黑底色手写展开】：纯黑背景下，优雅的粉蓝与青色发光数学公式与几何符号在虚空中缓缓书写展开，无一丝多余杂质；\n2.【4-10s 三维空间旋转与函数流形】：高维坐标轴在虚空中优雅旋转，彩色函数曲线平滑流动形变，向量场动态流动映射；\n3.【10-15s 几何和谐完美定格】：复杂推演化简为最纯粹的核心几何结构，发光定格，展现极致的科学严谨与数学崇高美感。`
    case 'whiteboard':
    default:
      return `极简思维白板手绘大片：围绕【${pName}】展开生动因果拆解：\n1.【0-4s 实时手绘开篇】：黑色白板笔伴随节奏在纯白画面上飞速勾勒出核心主题圆圈，线条生动自然，笔锋刚劲；\n2.【4-10s 箭头与图标连环推导】：引出动态连线与箭头，层层展开关键分支小图标与因果逻辑，抽丝剥茧一气呵成；\n3.【10-15s 镜头拉远纵观全貌】：镜头缓缓拉远，整幅思维模型全貌一目了然呈现在白板中央，清晰易懂、说服力拉满。`
  }
}

const stickmanQuickPresets = [
  // --- 知识科普与商业思维 (4款) ---
  {
    style: 'stickman-explainer',
    label: '🎙️ B5 角色解说 · IP形象出镜与舞台因果大标题',
    text: 'B5角色解说风格：画面右下角为极简卡通角色作为专属主播，配合清晰有力的解说节奏做出微仰头、抬手与生动的讲解口型；左侧主舞台为纯黑极简火柴人正针对核心认知展开高能图解：空中瞬间拉出醒目的红色能量时间轴，巨大齿轮与能量方块弹性碰撞翻转；火柴人以夸张的肢体拉扯巨大数据柱状图，顶部弹出高光大标题字幕，音画因果卡点丝滑连贯，全片充满极具感染力的科普解说节奏。'
  },
  {
    style: 'stickman-science',
    label: '🧠 科学图解 · 大脑多巴胺机制与原理解构',
    text: '纯白极简空间中，一名黑色极简火柴人正在解说大脑多巴胺机制：火柴人头顶浮现发光的灯泡与跳动的能量齿轮；随后火柴人抬手拉动一条虚线进度条，周围浮现多个递增的能量小方块；火柴人迈着自信步伐向前走去，身后留下一串平滑流淌的金色光点轨迹，图解元素与人物动作平滑连续、生动自然。'
  },
  {
    style: 'stickman-minimal',
    label: '📊 极简白板 · 商业增长金字塔与流程图解',
    text: '极简白板手绘风格：火柴人手持一支黑色白板笔，在纯白画面上快速画出一个金字塔分层结构图；火柴人顺着箭头一层层向上攀爬指引，每到一层，该层方框就闪烁一下并展开延伸数据线，动作生动流畅，思维模型层层递进一气呵成。'
  },
  {
    style: 'stickman-pop',
    label: '🎈 现代波普 · 亮黄小帽与几何空间穿梭',
    text: '现代波普风格：一名头戴亮黄色小圆帽的极简黑白火柴人穿行在极简立体的几何空间中，手中托着一枚发光的小蓝球；蓝球随着火柴人的步伐轻盈跳跃，火柴人快步穿过一扇扇极简几何拱门，色彩对比醒目强烈，运镜平滑跟进。'
  },

  // --- 故事日常与人文情怀 (4款) ---
  {
    style: 'stickman-survival',
    label: '☣️ B4 末日求生 · 丧尸围城与天台绝境拉闸',
    text: 'B4末日求生风格：倾盆暴雨与幽蓝冷光下的废弃都市天台，一名纯黑细线骨骼、白圆头佩戴白色手套的火柴人正紧贴避难所铁门急促喘息；镜头自低角度斜切推进，下方昏暗街头无数影影绰绰的黑色丧尸火柴人群正推翻铁丝网咆哮涌来；主角火柴人眼神紧绷，一把拉下紧急电闸，电火花炸裂带出高反差光影，全片极具窒息紧迫感与电影级张力。'
  },
  {
    style: 'stickman-cozy',
    label: '☕ 治愈日常 · 雨天书桌与暖热咖啡小确幸',
    text: '治愈手绘日常：温暖柔和的书桌旁，窗外飘着细雨，一只圆头细肢的火柴人静静坐在木椅上，双手端起冒着袅袅热气的咖啡杯轻啜一口；随后火柴人翻开身前的素描本，嘴角微微上扬，微风轻拂窗帘，镜头温和推近，画面充满治愈感。'
  },
  {
    style: 'stickman-history',
    label: '📜 趣味历史 · 古代国君踱步与长卷谋士献策',
    text: '趣味历史漫画：微黄羊皮纸背景上，一名头戴滑稽冠冕、身披简易披风的古代火柴人国君在大殿来回焦急踱步；一位身背竹简的谋士火柴人一路小跑进殿，激动地展开巨幅长卷竹简献策，国君夸张地拍手大笑，动作神态诙谐生动。'
  },
  {
    style: 'stickman-cave',
    label: '🔥 原始穴居 · 钻木取火与烤肉木棒炫耀',
    text: '石器时代原始洞穴：身穿粗糙兽皮短裙的原始火柴人正双手飞速搓动木棍钻木取火，突然火星引燃干草冒出一缕小火苗；火柴人惊喜得原地滑稽手舞足蹈，兴奋地举起烤肉木棒向同伴炫耀，动作连贯搞笑，充满原始野趣。'
  },

  // --- 高能动作与娱乐对决 (5款) ---
  {
    style: 'stickman-action',
    label: '⚔️ Alan Becker · 双人高能体术与凌空连环踢',
    text: '纯白极简空间中，两名纯黑极简线条火柴人展开高能对决：黑衣火柴人极速贴地冲刺暴起飞踢，白衣火柴人沉稳十字格挡向后滑行；白衣人借力后翻跃起，凌空施展连续回旋踢反击，黑衣人俯身下潜扫堂腿化解；随后两人同时跃至半空极速拳脚交锋，高速拳脚带有自然平滑运动残影与速度线，动作高帧率丝滑连贯，行云流水一气呵成。'
  },
  {
    style: 'stickman-classic',
    label: '🤸 经典纯粹 · 障碍冲刺滑行与单杠大回环',
    text: '经典纯黑白极简空间：一名火柴人全速冲刺跳跃越过障碍物，空中伸展肢体轻盈翻滚落地，紧接着连续前手翻起跳抓住上方单杠，大回环旋转两周后稳稳落地摆出胜利姿势，动作一气呵成。'
  },
  {
    style: 'stickman-comedy',
    label: '🤣 爆笑沙雕 · 疯狂麻花自转与魔性滑跪摔飞',
    text: '两只火柴人魔性搞笑大乱斗：一拳挥空把自己像麻花一样疯狂自转三圈，另一只火柴人魔性滑跪偷袭却踩到香蕉皮滑稽摔飞；两人立刻在地上像面条一样扭动缠打，滑稽追逐翻滚，全程魔性搞笑动作连绵不断，动作轨迹连贯流淌，一气呵成。'
  },
  {
    style: 'stickman-cyber',
    label: '⚡ 赛博霓虹 · 暗夜雨幕双色光剑极速对刀',
    text: '赛博朋克火柴人雨夜屋顶激战：两名火柴人手持荧光青蓝与粉紫光剑，在倾盆雨夜的天台上高速冲刺交锋；光剑剧烈碰撞炸裂刺目火花，一人被震退数米后踩踏墙壁借力反折突进，另一人高难度侧滑闪避并回身横斩，两人在霓虹雨幕中展开不间断的极速对刀缠斗，动作全程丝滑无断档。'
  },
  {
    style: 'stickman-wuxia',
    label: '🎋 写意水墨 · 竹林踏竹轻功与纵横剑气',
    text: '水墨风火柴人高能武侠对决：两名极简火柴人手持细剑，在水墨竹林间踏竹高速飞跃追击；黑衣人凌空挽剑花直刺，白衣人贴身缠刃格挡并旋身反刺，两人落地后行云流水连续展开，水墨剑气纵横飞舞，紧接着在竹林间展开连续十招行云流水的高速剑法对拼，墨迹飘逸，全程全片高动态丝滑连贯，一气呵成。'
  },
]

const huashuQuickPresets = computed(() => {
  const pName = (project.value?.name || '品牌高端产品').trim()
  return HUASHU_DEFAULT_TEMPLATES.map(t => ({
    templateId: t.id,
    label: `${t.icon || '✨'} ${t.name}`,
    tag: t.tag,
    duration: t.duration || 15,
    energy: t.energy,
    text: getHuashuTemplatePrompt(t.id, pName)
  }))
})

const quickPresets = computed(() => {
  if (isStickman.value) {
    return stickmanQuickPresets
  }
  return huashuQuickPresets.value
})

const presetSelectOptions = computed(() => {
  const defaultLabel = isStickman.value
    ? `💡 选择火柴人灵感模版快速载入 (${quickPresets.value.length}款可选)...`
    : `✨ 选择花叔商业发布片模版快速载入 (${quickPresets.value.length}款大厂流派)...`
  return [
    { value: '', label: defaultLabel },
    ...quickPresets.value.map((p, idx) => ({
      value: String(idx),
      label: p.label,
    }))
  ]
})

function onSelectPreset(val) {
  if (!val && val !== 0 && val !== '0') return
  const idx = Number(val)
  const item = quickPresets.value[idx]
  if (item) {
    prompt.value = item.text
    if (!isStickman.value && item.templateId) {
      selectedHuashuTemplateId.value = item.templateId
      message.value = `已载入【${item.label}】并绑定花叔模版！`
    } else {
      message.value = `已载入灵感模版：${item.label}`
    }
    setTimeout(() => { if (message.value.startsWith('已载入')) message.value = '' }, 3000)
  }
  selectedPresetKey.value = ''
}



const durationOptions = [5, 10, 15, 30, 50]
const ratioOptions = [
  { label: '9:16 竖屏（手机短视频）', value: '9:16' },
  { label: '16:9 横屏（电脑大屏）', value: '16:9' },
  { label: '1:1 方形', value: '1:1' },
]

const modelSelectOptions = computed(() => videoModels.value.map(m => ({
  value: String(m.id || m.modelName),
  label: m.name || m.modelName,
})))

async function request(method, path, body = null) {
  return desktopBackendRequest(method, path, props.token, body, 0)
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    if (!effectiveStorageBase.value && window.pywebview?.api?.get_app_info) {
      try {
        const info = await window.pywebview.api.get_app_info()
        if (info?.storageBase) effectiveStorageBase.value = info.storageBase
        if (info?.apiBase) effectiveApiBase.value = info.apiBase
      } catch (_) {}
    }
    const [p, models, textM] = await Promise.all([
      request('GET', `/project/${encodeURIComponent(props.projectId)}`),
      request('GET', '/api/admin/models/public/list?modelType=video').catch(() => []),
      request('GET', '/api/admin/models/public/list?modelType=text').catch(() => []),
    ])
    project.value = p
    videoModels.value = Array.isArray(models) ? models : []
    textModels.value = Array.isArray(textM) ? textM : []
    if (videoModels.value.length) {
      selectedModel.value = String(videoModels.value[0].id || videoModels.value[0].modelName)
    }

    // 恢复历史直出状态
    const directMeta = p.workflow?.directVideo || {}
    const pName = p?.name?.trim() || ''
    const isSpecificProject = pName && !pName.includes('新火柴人项目') && !pName.includes('未命名')
    activeEngine.value = 'ai_video'
    if (directMeta.huashuTemplateId) {
      selectedHuashuTemplateId.value = directMeta.huashuTemplateId
    } else if (p.workflow?.huashu?.templateId) {
      selectedHuashuTemplateId.value = p.workflow.huashu.templateId
    }

    // 先恢复基础配置（必须先确定 style，再生成 prompt）
    if (directMeta.style) selectedStyle.value = directMeta.style
    else if (p.style) selectedStyle.value = p.style
    else if (Array.isArray(p.storyGenres) && p.storyGenres[0]) selectedStyle.value = p.storyGenres[0]

    if (!isStickman.value && (selectedStyle.value.startsWith('stickman') || !selectedStyle.value)) {
      selectedStyle.value = p.style || 'commercial'
    }

    if (directMeta.duration) duration.value = directMeta.duration
    if (directMeta.ratio) ratio.value = directMeta.ratio

    if (directMeta.prompt) {
      let pmt = String(directMeta.prompt || '')
      if (!isStickman.value) {
        // 通用视频模块智能清洗：若意外混入了火柴人/打架/丧尸等内容，彻底清洗并重新生成纯正的商业/科普提示词
        const hasStickmanTrash = pmt.includes('火柴人') || pmt.includes('Alan Becker') || pmt.includes('体术对决') || pmt.includes('黑衣人') || pmt.includes('白衣人') || pmt.includes('丧尸') || pmt.includes('僵尸') || pmt.includes('求生') || pmt.includes('极简线条')
        if (hasStickmanTrash) {
          pmt = generateGeneralSmartPrompt(pName, selectedStyle.value)
        }
      } else {
        // 火柴人模块的清理
        const isOldTemplate = pmt.includes('大脑多巴胺机制') || pmt.includes('多巴胺分泌水平') || pmt.includes('极简舞台高速对决')
        const isMismatchedFight = (pmt.includes('飞踢') || pmt.includes('回旋踢') || pmt.includes('对决')) && /生命|起源|宇宙|科学|科普|细胞|物理|化学|生物|医学/.test(pName)
        const isShortOldPrompt = pmt.includes('【生命的起源】') && pmt.length < 180
        
        if (isSpecificProject && (isOldTemplate || isMismatchedFight || isShortOldPrompt)) {
          pmt = generateSmartPrompt(pName, selectedStyle.value)
        } else {
          if (pmt.includes('Hitstop') || pmt.includes('打击停顿')) {
            pmt = pmt.replace(/瞬移/g, '极速贴地冲刺')
                     .replace(/打击停顿[（(]Hitstop[)）]/gi, '高速冲击波与连续追击')
                     .replace(/Hitstop/gi, '高速连击')
                     .replace(/打击停顿/g, '高速追打')
                     .replace(/落地定格/g, '滑行反击')
          }
        }
      }
      prompt.value = pmt
    } else if (isStickman.value) {
      if (isSpecificProject) {
        prompt.value = generateSmartPrompt(pName, selectedStyle.value)
      } else {
        prompt.value = quickPresets.value[0]?.text || ''
      }
    } else {
      if (isSpecificProject) {
        prompt.value = generateGeneralSmartPrompt(pName, selectedStyle.value)
      } else {
        prompt.value = quickPresets.value[0]?.text || ''
      }
    }
    if (Array.isArray(directMeta.history)) {
      const seen = new Set()
      const deduped = []
      for (const h of directMeta.history) {
        const k = h.id || h.url || h.fileId
        if (k && !seen.has(k)) {
          seen.add(k)
          deduped.push(h)
        } else if (!k) {
          deduped.push(h)
        }
      }
      historyVersions.value = deduped
      if (historyVersions.value.length) {
        selectVersion(historyVersions.value[0])
      }
    }
    if (!prompt.value) {
      if (isStickman.value) {
        prompt.value = quickPresets.value[0]?.text || ''
        ratio.value = '9:16'
        selectedStyle.value = project.value.style || 'stickman-action'
      } else {
        prompt.value = quickPresets.value[0]?.text || ''
        ratio.value = project.value?.ratio || '16:9'
        selectedStyle.value = project.value?.style || 'commercial'
      }
    }
  } catch (err) {
    error.value = String(err.message || err || '加载项目失败')
  } finally {
    loading.value = false
  }
}

async function persistDirectState() {
  if (!project.value) return
  try {
    const directData = {
      prompt: prompt.value,
      duration: duration.value,
      ratio: ratio.value,
      style: selectedStyle.value,
      huashuTemplateId: selectedHuashuTemplateId.value,
      history: historyVersions.value,
    }
    const updatedWorkflow = {
      ...(project.value.workflow || {}),
      directVideo: directData,
    }
    await request('PUT', `/project/${encodeURIComponent(project.value.id)}`, {
      workflow: updatedWorkflow,
    })
  } catch (err) {
    console.warn('保存直出配置失败:', err)
  }
}


function generateGeneralSmartPrompt(name, styleKey) {
  const cleanName = (name || '').trim() || '商业宣传'
  
  // 智能识别主题关键词（品牌/酒水奢华、前沿科技、科普演示、质感生活、3D摄影等）
  const isAlcoholOrLuxury = /酒|茅台|酱香|典雅|奢华|高端|腕表|珠宝|香水|品味|国潮/.test(cleanName)
  const isTech = /科技|AI|智能|系统|软件|平台|芯片|数据|数智|云|算法|数字|未来/.test(cleanName)
  const isScience = /科普|原理|为什么|生命|起源|宇宙|科学|细胞|物理|化学|生物|医学|自然|光合/.test(cleanName)
  const isLifeOrFood = /咖啡|生活|日常|美食|饮品|清晨|治愈|旅行|探店|茶|慢调/.test(cleanName)
  
  if (isAlcoholOrLuxury || styleKey === 'commercial' || styleKey === 'luxury') {
    return `围绕【${cleanName}】打造的高端品牌电影级商业宣传视效短片：\n` +
           `1.【意境开篇】：深邃典雅的极简暗调空间中，温润晨光与柔和微光如丝缎般流淌，微距聚焦产品纯净质感与精细工艺；\n` +
           `2.【匠心特写】：镜头平滑推近，多角度展示器型轮廓与典雅材质，柔和摄影棚高光在表面平滑流转，细节纤毫毕现；\n` +
           `3.【视觉高潮】：核心元素以慢动作优雅舒展与凝固升腾，配合环境微弱自然流光，呈现品牌传世沉淀的非凡气韵；\n` +
           `4.【华彩定格】：镜头缓缓拉远，主体在极简展台上沉稳定格，光影柔和收敛，画面高级内敛，彰显经典风范与奢华质感。`
  }

  if (isTech || styleKey === 'tech-future' || styleKey === 'keynote-ui') {
    return `围绕【${cleanName}】打造的前沿科技感商业发布视效短片：\n` +
           `1.【全息启动】：极简深色未来感空间中，幽蓝与青色光子脉冲在中心汇聚，瞬间激活三维数据矩阵；\n` +
           `2.【多层展开】：多层悬浮全息界面与精细技术拓扑图平滑向外延展，数据光流穿梭流动，呈现硬核前沿技术架构；\n` +
           `3.【高能推演】：镜头以极速推拉运镜穿梭于立体界面与芯片光路之间，粒子爆发光芒，展现极致算力与未来体验；\n` +
           `4.【震撼定格】：所有数据光轨向中心极速汇聚成标志性产品形态，光芒收束定格，现代科技感与大厂质感拉满。`
  }

  if (isScience || styleKey === 'science') {
    return `围绕【${cleanName}】展开的高清知识科普动态视觉演示：\n` +
           `1.【宏观引入】：纯净空间中平滑引入探索主题，由远及近缓缓推入微观世界或宏观结构，引发探知好奇；\n` +
           `2.【步骤解构】：核心结构以三维立体方式清晰分层展开，各关键组件平滑分离，伴随动态指示线与清晰数据标注；\n` +
           `3.【动态推演】：微观运动与反应机制以清晰明了的高帧率动画演示，物理/生物化学反应过程生动直观、层层递进；\n` +
           `4.【总结定格】：各部分结构完美嵌合回归整体，全景总结图解呈现，画面干净严谨、极具启发性与科普美感。`
  }

  if (isLifeOrFood || styleKey === 'modern-life') {
    return `围绕【${cleanName}】展开的高品质慢调质感生活纪录：\n` +
           `1.【晨光初现】：温暖柔和的自然光透过窗棂洒在木质纹理表面，微风轻拂，微距特写捕捉微小而美好的生活细节；\n` +
           `2.【细腻过程】：镜头以电影级浅景深缓缓运镜，动作节奏沉静舒缓，捕捉日常交互中的纯粹温度与质感；\n` +
           `3.【情绪升温】：自然光影在空间中流淌变化，柔和色彩与细腻胶片颗粒感交融，情绪宁静治愈；\n` +
           `4.【美好定格】：镜头缓缓拉远定格于温馨而富有生活美学的构图之中，留白充分，带来悠长的松弛与愉悦感。`
  }

  if (styleKey === '3d-studio') {
    return `围绕【${cleanName}】打造的极简 3D 摄影棚立体展示大片：\n` +
           `1.【空间悬浮】：纯色极简摄影棚空间，主体悬浮在几何展台上方，极具空间层次与悬浮感；\n` +
           `2.【光影流转】：顶部柔光箱与侧向轮廓灯缓缓移动，金属、玻璃与哑光材质表面的反光与阴影随运镜优雅变换；\n` +
           `3.【360度巡展】：摄影机环绕主体展开 360 度平滑旋转特写，精准捕捉产品每一个精密转角与衔接细节；\n` +
           `4.【完美定焦】：运镜停靠在最佳视点，景深虚化背景，主体以极具设计美学的姿态完美定格。`
  }

  if (styleKey === 'cinematic') {
    return `围绕【${cleanName}】展开的电影级纪实人文视觉短片：\n` +
           `1.【电影序曲】：宽银幕比例，情绪化冷暖对比光影勾勒出具有故事感的场景轮廓，氛围感拉满；\n` +
           `2.【移步换景】：镜头平滑推进跟随视线穿梭，浅景深虚化背景，特写与全景有机交替，呈现强烈的真实纪实质感；\n` +
           `3.【视觉叙事】：光影与镜头运动节奏紧密配合，画面富含胶片质感与光影韵律，传达深刻的人文与品牌内涵；\n` +
           `4.【沉浸收尾】：镜头在开阔大气的景别中缓缓推远，定格在耐人寻味的电影画卷之中，余音绕梁。`
  }

  // 默认通用商业视觉
  return `围绕【${cleanName}】打造的高水准专业视觉短片：\n` +
         `1.【精妙开场】：极简高质感背景中，光芒自暗部缓缓浮现，引出【${cleanName}】核心主体形象；\n` +
         `2.【细节呈现】：高精度微距运镜平滑推拉，材质质感、工艺线条与光影流动呈现极高完成度；\n` +
         `3.【动感升维】：主体配合自然动效与优雅运镜展开多维展示，光影节奏鲜明，画面充满视觉张力；\n` +
         `4.【经典定格】：镜头平稳收拢定格于完美构图，光彩内敛沉淀，呈现出纯正的专业品牌气度。`
}

function generateSmartPrompt(name, styleKey) {
  if (!isStickman.value) {
    return generateGeneralSmartPrompt(name, styleKey)
  }
  const cleanName = (name || '').trim() || '火柴人创意演示'
  
  // 智能语义识别：自动识别角色解说、科普、日常、历史、魔性等主题，杜绝非格斗主题误套打架
  const isExplainer = /解说|主播|出镜|角色|IP|评测|博主|说车|讲故事|知识/.test(cleanName)
  const isSurvival = /丧尸|末日|求生|僵尸|感染|围城|废土|惊悚|逃生|异变|灾变|生化/.test(cleanName)
  const isScience = /生命|起源|宇宙|大爆炸|细胞|进化|演化|地球|科学|物理|化学|生物|医学|大脑|多巴胺|神经|机制|图解|模型|科普|商业|增长/.test(cleanName)
  const isHistory = /历史|古代|原始|穴居|石器|文明|朝代|三国|大唐|古人|发现火种/.test(cleanName)
  const isCozy = /咖啡|雨天|书店|温暖|日常|治愈|生活|小确幸|散步|黄昏|清晨/.test(cleanName)
  const isComedy = /沙雕|搞笑|魔性|倒霉|翻车|打脸|滑稽/.test(cleanName)
  
  if (styleKey === 'stickman-survival' || (isSurvival && !['stickman-action', 'stickman-classic', 'stickman-cyber', 'stickman-wuxia'].includes(styleKey))) {
    return `围绕【${cleanName}】展开的标准B4末日求生与丧尸惊悚（Survival Thriller）全景分镜：\n` +
           `1.【危机降临与悬疑开局】：昏暗压抑的末日避难空间中，雨水顺着破碎窗户淌落，主角火柴人（白圆头细黑肢体戴白手套）手持对讲机紧贴水泥墙面屏息凝神，阴影中隐约传来金属刮擦与丧尸低吼；\n` +
           `2.【威胁逼近与视觉升级】：镜头陡然拉低，铁丝网外无数狂暴的丧尸火柴人影子飞速扑来，红光警报闪烁，主角在3秒内迅猛完成反锁安全门、装填防身道具的连贯求生动作；\n` +
           `3.【生死搏杀与惊险突围】：大门被撞开一道裂缝，丧尸狂暴手臂探入，主角果断推翻沉重铁柜死死抵住通道，随后借力翻滚越向天台边缘索道；\n` +
           `4.【悬念高潮定格】：主角挂上滑索回望下方的汹涌尸潮，夜空雷暴撕裂苍穹，画面定格在极具末日史诗感的全景对峙中。\n` +
           `全片符合B4官方求生规范，光影冷峻压迫，动作紧凑丝滑，音画卡点极具沉浸感。`
  }
  if (styleKey === 'stickman-explainer' || (isExplainer && !['stickman-action', 'stickman-classic', 'stickman-cyber', 'stickman-wuxia'].includes(styleKey))) {
    return `围绕【${cleanName}】展开的标准B5角色人物解说（Character Explainer）全景分镜：\n` +
           `1.【开篇立论与IP出镜】：画面右下角为极简卡通角色主播，目光炯炯配合生动口型展开第一句黄金钩子；左侧舞台以暖纸质感为底，黑色极简火柴人推着巨大醒目的红色问号滑行登场，顶端浮现震撼动态大标题；\n` +
           `2.【因果演化与物理喜剧】：右下角主播微仰头手势引导，左侧火柴人遭遇夸张的现实反差难题，身体弹性受挫拉伸，随后手绘拉出发光时间轴与递增数据柱，齿轮与方块发生清脆的因果碰撞连锁反应；\n` +
           `3.【深度破局与图解升华】：镜头微推，左侧火柴人一跃而起切碎复杂困境，主视觉模型层层展开如水流般自然平滑重组，红色高光点缀核心要素；\n` +
           `4.【总结定格与互动号召】：主播微笑挥手示意，左侧火柴人与核心架构图完美闭环定格，大标题字幕与讨论金句卡点弹出。\n` +
           `全片60fps丝滑动画，音画因果严密卡点，节奏张弛有度，一气呵成。`
  }
  if (isScience || styleKey === 'stickman-science' || styleKey === 'stickman-whiteboard' || styleKey === 'stickman-pop') {
    if (/生命|起源|演化|进化|细胞|生物/.test(cleanName)) {
      return `纯白极简无界空间中，黑色极简火柴人作为科学导师展开【${cleanName}】深度全景图解演化：\n` +
             `1.【开篇起势】：火柴人手绘拉出一条发光时间轴，头顶浮现原始地球、火山喷发与深海热泉热液喷口的动态简笔线框；\n` +
             `2.【微观演化递进】：火柴人侧身抬手轻点虚空，时间轴平滑流转，有机分子、氨基酸链条与RNA单链以流畅线条逐层凝聚分裂；\n` +
             `3.【生命爆发跃迁】：镜头平滑推移，单细胞原核生物分裂递进为复杂生命树图谱，火柴人轻快前行引导演化脉络，周围漂浮发光的进化光点与数据图表；\n` +
             `4.【宏大收尾】：火柴人转身挥手划出一道极具流动感的弧线，整个极简演化生态汇聚收拢，镜头拉远展示完整的生命史诗框架。\n` +
             `全程60fps高帧率连贯运镜，线条平滑富有生命力，行云流水一气呵成。`
    }
    return `纯白极简空间中，黑色极简火柴人进行【${cleanName}】全流程深度解构：\n` +
           `1.【结构展开】：火柴人抬手在虚空中快速绘制核心认知图谱，自左向右动态延展出发光的脉络箭头；\n` +
           `2.【动态演示】：火柴人迈步走进图表中心，双手拉伸展开关键变量模型，周围平滑浮现数据进度条、分层漏斗与联动齿轮动效；\n` +
           `3.【深层推演】：镜头缓缓推近特写，火柴人以生动的肢体语言逐一轻点核心支点，图解线条如泉水般流淌重组；\n` +
           `4.【总结定格】：火柴人后撤一步展开双臂，全局图谱完美闭环并发光高亮。\n` +
           `全片线条极简纯粹，讲解节奏张弛有度，高帧率动态丝滑流畅。`
  }
  if (isHistory || styleKey === 'stickman-history' || styleKey === 'stickman-cave') {
    return `复古质感空间中，围绕【${cleanName}】展开深度趣味历史画卷：\n` +
           `1.【时代序幕】：一名极简火柴人手持竹简推开历史大门，背景以手绘黑白线条动态勾勒出古建筑、战车与时代风貌；\n` +
           `2.【文明演进】：火柴人穿梭于不同时代场景之间，以生动幽默的肢体动作触发重大历史转折点，场景自左向右如水墨画卷般无缝平滑推移；\n` +
           `3.【历史沉淀】：镜头升至俯瞰全景，多个火柴人角色以群体动画展现时代生活百态与文明变迁；\n` +
           `4.【时光定格】：主角火柴人跃上时代高台，指向前方延伸的历史长河。\n` +
           `全片富有叙事节奏感，手绘线条生动流畅，一气呵成。`
  }
  if (isCozy || styleKey === 'stickman-cozy') {
    return `温暖治愈手绘空间中，围绕【${cleanName}】展开细腻连贯的生活日常：\n` +
           `1.【晨光初现】：窗外微风拂过，圆头细肢的极简火柴人静坐在书桌前，双手端起热气腾腾的马克杯轻啜，热气化作优雅的白色线条升腾；\n` +
           `2.【温馨互动】：火柴人起身踱步到窗边推开窗户，落叶与微风带有柔和的动态轨迹，火柴人嘴角微扬展开素描画本描摹；\n` +
           `3.【岁月静好】：镜头伴随柔和推移，火柴人靠在椅背上静静翻书，窗帘轻抚，空间光影缓慢流转。\n` +
           `全程节奏宁静舒缓，线条柔和富有呼吸感，画面充满治愈力。`
  }
  if (isComedy || styleKey === 'stickman-comedy') {
    return `纯白空间中围绕【${cleanName}】展开的魔性极简火柴人高能搞笑反转短剧：\n` +
           `1.【自信登场】：火柴人霸气迈步出场摆出绝世高人造型，正欲大展身手却意外触发魔性滑稽物理效果；\n` +
           `2.【神级反转】：火柴人身体如橡皮筋般夸张弹性拉伸，踩到意外道具滑跪翻滚，引发一连串多米诺骨牌般的搞笑连锁反应；\n` +
           `3.【疯狂连击】：另一只火柴人加入混战，两人展开面条般夸张的魔性缠斗与幽默追逐，夸张的肢体拉扯与受击反馈连绵不断；\n` +
           `4.【爆笑收尾】：火柴人以不可思议的姿势卡在画框边缘滑稽挠头。\n` +
           `全片60fps魔性高能，动感丝滑，笑点密集。`
  }
  return `围绕【${cleanName}】展开的Alan Becker经典高能火柴人终极体术对决：\n` +
         `1.【迅猛开局】：黑衣火柴人极速贴地冲刺带出平滑速度线，暴起凌空飞踢，白衣火柴人沉稳十字格挡向后长距离滑行借力；\n` +
         `2.【空中连击】：白衣火柴人借势反弹跃上半空，施展连续旋风腿突刺，黑衣人俯身下潜扫堂腿化解后顺势翻滚借力暴起；\n` +
         `3.【高潮交锋】：两人同时跃入半空展开极致高频拳脚交锋，拳风与冲击波以极简气浪扩散，带出自然平滑运动残影；\n` +
         `4.【终局对撞】：两人自两端疾速冲刺对撞，冲击波震荡全场后各自帅气滑行稳稳受身。\n` +
         `全片动作高帧率丝滑连贯，打击感与速度感兼备，行云流水一气呵成。`
}

async function expandPromptWithAI() {
  if (aiExpanding.value) return
  aiExpanding.value = true
  error.value = ''
  const pName = (topicName.value || project.value?.name || (isStickman.value ? '火柴人动画' : '商业宣传片')).trim()
  const curTpl = selectedHuashuTemplate.value || HUASHU_DEFAULT_TEMPLATES[0]
  message.value = isStickman.value
    ? `正在根据「${pName}」深度扩写火柴人分镜提示词…`
    : `正在根据主题「${pName}」及【${curTpl.name}】深度扩写商业分镜提示词…`

  try {
    const basePmt = prompt.value.trim() || (isStickman.value ? generateSmartPrompt(pName, selectedStyle.value) : curTpl.generatePrompt(pName))

    const sysPrompt = isStickman.value
      ? '你是一位顶尖的火柴人动画导演与分镜提示词专家。你的任务是为AI视频模型编写画面感极强、分镜清晰分段、动作行云流水连贯的火柴人视频生成提示词（Prompt）。严禁包含任何文字开场白或解释，直接输出 250~400 字的完整中文视频生成 Prompt。'
      : `你是一位顶尖的商业大片与大厂发布会视效导演。你的核心任务是根据品牌/主题「${pName}」和选定的花叔流派【${curTpl.name}】（风格特征：${curTpl.tag}），为底层 AI 视频模型编写极具视觉张力、镜头运动澎湃、多机位快切的电影级分镜提示词（Prompt）。
硬性要求：
1. 坚决杜绝静止微动的慢吞吞描述！必须使用具体的摄影机运镜指令（如：探针微距飞掠、360度低角度环绕旋转、快速推拉穿梭、体积光横扫）；
2. 画面必须包含明确的4个阶段递进：【0-3s 极速微距切入】、【3-8s 动态环绕/穿梭展开】、【8-12s 视觉高潮/光影爆发】、【12-15s 殿堂级定格】；
3. 展现顶级材质细节、高反差做工与光影反差，与花叔 60fps 动效包装形成绝妙卡点共振；
4. 严禁输出任何火柴人、小人、客套问候或说明，直接输出 250~350 字的完整中文视频生成 Prompt！`

    const chatBody = {
      messages: [
        { role: 'system', content: sysPrompt },
        {
          role: 'user',
          content: isStickman.value
            ? `请为项目【${pName}】深度扩写一段极具画面感的火柴人视频生成提示词。\n当前基础参考：\n${basePmt}`
            : `请根据名称【${pName}】与花叔模版【${curTpl.name}】深度扩写一段极具视觉质感的商业视频生成提示词。\n当前参考：\n${basePmt}`
        }
      ]
    }
    if (textModels.value.length) {
      chatBody.model = String(textModels.value[0].id || textModels.value[0].modelName)
    }

    const res = await request('POST', '/ai/chat', chatBody)

    let reply = ''
    if (res?.choices && Array.isArray(res.choices) && res.choices.length) {
      reply = res.choices[0]?.message?.content || res.choices[0]?.text || ''
    } else if (res?.content) {
      reply = typeof res.content === 'string' ? res.content : JSON.stringify(res.content)
    }
    reply = String(reply || '').replace(/^```[a-zA-Z]*\n?/, '').replace(/\n?```$/, '').trim()
    reply = reply.replace(/^(?:提示词|Prompt|分镜描述|优化后提示词)[：:\s]*/i, '').trim()

    if (!isStickman.value && (reply.includes('火柴人') || reply.includes('黑衣人') || reply.includes('体术对决') || reply.includes('丧尸'))) {
      reply = ''
    }

    if (reply && reply.length > 30) {
      prompt.value = reply
      await persistDirectState()
      message.value = `✨ 已根据名称「${pName}」深度扩写出【${curTpl.name}】大片级提示词！`
    } else {
      prompt.value = isStickman.value ? generateSmartPrompt(pName, selectedStyle.value) : curTpl.generatePrompt(pName)
      await persistDirectState()
      message.value = `✨ 已根据名称「${pName}」载入【${curTpl.name}】专属提示词！`
    }
  } catch (err) {
    console.warn('AI 文本模型扩写调用异常，使用内置智能模版:', err)
    const curTpl = selectedHuashuTemplate.value || HUASHU_DEFAULT_TEMPLATES[0]
    prompt.value = isStickman.value ? generateSmartPrompt(pName, selectedStyle.value) : curTpl.generatePrompt(pName)
    await persistDirectState()
    message.value = `✨ 已根据名称「${pName}」载入【${curTpl.name}】专属提示词`
  } finally {
    aiExpanding.value = false
    setTimeout(() => { if (message.value.startsWith('✨')) message.value = '' }, 4000)
  }
}

function applySmartPrompt() {
  const pName = project.value?.name
  prompt.value = isStickman.value ? generateSmartPrompt(pName, selectedStyle.value) : generateGeneralSmartPrompt(pName, selectedStyle.value)
  const styleLabel = isStickman.value ? getStickmanStyleConfig(selectedStyle.value).label : currentStyleConfig.value.label
  message.value = `✨ 已根据项目「${pName}」与【${styleLabel}】生成专属提示词`
  setTimeout(() => { if (message.value.startsWith('✨')) message.value = '' }, 4000)
}

function applyPreset(preset) {
  prompt.value = preset.text
}

async function pickReferenceImage() {
  try {
    if (!window.pywebview?.api?.select_local_reference_file) {
      error.value = '请在桌面客户端中使用文件选择'
      return
    }
    const chosen = await window.pywebview.api.select_local_reference_file()
    if (!chosen) return
    if (chosen.mediaType !== 'image') {
      error.value = '请选择图片文件作为参考'
      return
    }
    const uploadRes = await window.pywebview.api.upload_local_file(props.token, chosen.path)
    const fileId = String(uploadRes.id || uploadRes.fileId || '')
    referenceImage.value = {
      fileId,
      name: chosen.name || '参考图',
      url: `${props.storageBase || 'http://127.0.0.1:18081'}/file/${fileId}/download`,
    }
  } catch (err) {
    error.value = '选择参考图失败: ' + String(err.message || err)
  }
}

function removeReferenceImage() {
  referenceImage.value = null
}

async function startDirectGeneration() {
  if (generating.value) return
  error.value = ''
  message.value = ''
  if (!prompt.value.trim()) {
    error.value = '请输入视频动作或剧情描述'
    return
  }

  generating.value = true
  taskProgress.value = 5
  taskStatusText.value = '正在构建直出提示词与模型参数…'

  try {
    // 注入风格与动作规范，清洗任何可能导致大模型冻结定格的遗留词汇
    let cleaned = prompt.value.trim()
      .replace(/瞬移/g, '极速贴地冲刺')
      .replace(/打击停顿[（(]Hitstop[)）]/gi, '高速冲击波与连续追击')
      .replace(/Hitstop/gi, '高速连击')
      .replace(/打击停顿/g, '高速追打')
      .replace(/落地定格/g, '滑行反击')
      .replace(/定格/g, '滑行动作')
      .replace(/停顿/g, '连贯推进')
      .replace(/停滞/g, '连绵流淌')
    prompt.value = cleaned
    let finalPrompt = cleaned
    if (isStickman.value) {
      const styleConf = getStickmanStyleConfig(selectedStyle.value)
      finalPrompt = `【墨柴火柴人·超流畅直出】风格：${styleConf.label}（${selectedStyle.value}）。${finalPrompt}\n` +
        styleConf.constraint
    }

    const content = [{ type: 'text', text: finalPrompt }]
    if (referenceImage.value?.url) {
      content.push({
        type: 'image_url',
        image_url: { url: referenceImage.value.url },
        role: 'first_frame',
      })
    }

    const isLongVideo = Number(duration.value || 10) > 10
    const payload = {
      model: selectedModel.value,
      project_id: String(project.value.id),
      prompt: finalPrompt,
      content,
      ratio: ratio.value,
      duration: Number(duration.value || 10),
      production_mode: isLongVideo ? 'scene' : 'shot',
      generate_audio: true,
      resolution: '720p',
    }

    taskStatusText.value = isLongVideo ? '已启用 Muse 全片组装模式，正在提交长视频任务…' : '已提交视频直出任务…'
    const submitRes = await request('POST', '/ai/video', payload)
    const taskId = String(submitRes.taskId || submitRes.id || '')
    if (!taskId) throw new Error('未返回任务 ID')

    currentTaskId.value = taskId
    taskStatusText.value = isLongVideo ? 'Muse 正在多段生成并自动剪辑组装长视频中（预计2-3分钟）…' : '已进入队列，实时生成高动态视频中…'
    taskProgress.value = 15

    // 开始轮询
    startPolling(taskId)
  } catch (err) {
    generating.value = false
    error.value = '启动直出生成失败: ' + String(err.message || err)
  }
}

let isPollingTick = false
function startPolling(taskId) {
  if (pollTimer) clearTimeout(pollTimer)
  let attempts = 0
  
  const tick = async () => {
    if (isPollingTick) return
    isPollingTick = true
    attempts++
    try {
      const poll = await request('GET', `/ai/video/${encodeURIComponent(taskId)}?model=${encodeURIComponent(selectedModel.value)}`)
      const status = String(poll?.status || '').toLowerCase()
      
      // 模拟与真实进度
      if (poll?.progress) {
        taskProgress.value = Math.max(taskProgress.value, Number(poll.progress))
      } else {
        taskProgress.value = Math.min(92, 15 + Math.floor(attempts * 2.5))
      }

      if (status === 'succeeded' || status === 'completed' || poll?.fileId || poll?.url) {
        generating.value = false
        taskProgress.value = 100
        taskStatusText.value = '成片直出成功！'
        
        const fileId = String(poll.fileId || poll.resultFileId || '')
        let rawUrl = poll.video_url || poll.url || (fileId ? `/file/${fileId}/download` : '')
        let relativeUrl = rawUrl.includes('/file/') ? rawUrl.substring(rawUrl.indexOf('/file/')) : rawUrl
        if (!relativeUrl && fileId) {
          relativeUrl = `/file/${fileId}/download`
        }
        
        const newVersion = {
          id: taskId,
          fileId,
          url: relativeUrl,
          prompt: prompt.value,
          duration: duration.value,
          ratio: ratio.value,
          style: selectedStyle.value,
          createdAt: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
        }

        currentResult.value = newVersion
        currentVideoUrl.value = resolveVideoUrl(newVersion)
        // 去重判断，防止并发轮询时重复推入相同任务
        if (!historyVersions.value.some(h => (h.id && h.id === taskId) || (relativeUrl && h.url === relativeUrl))) {
          historyVersions.value.unshift(newVersion)
        }
        message.value = '完整成片已直出！可在大屏监视器中预览播放或直接导出。'
        await persistDirectState()
        return
      } else if (status === 'failed' || status === 'error') {
        generating.value = false
        error.value = '生成失败: ' + String(poll?.message || poll?.error || '视频引擎返回异常')
        return
      } else {
        taskStatusText.value = poll?.message || `正在渲染动态帧… (${taskProgress.value}%)`
      }
    } catch (err) {
      console.warn('轮询视频直出异常:', err)
    } finally {
      isPollingTick = false
      if (generating.value) {
        pollTimer = setTimeout(tick, 2000)
      }
    }
  }

  pollTimer = setTimeout(tick, 1500)
}

function selectVersion(v) {
  currentResult.value = v
  currentVideoUrl.value = resolveVideoUrl(v)
}


async function packageWithHuashuTemplate() {
  if (packagingHuashu.value) return
  packagingHuashu.value = true
  const tmpl = selectedHuashuTemplate.value
  const tmplName = tmpl?.name || '3D 空间立体产品展示'
  const tmplId = tmpl?.id || 'object-3d'
  message.value = `正在将当前 AI 视频套入【${tmplName}】60fps 模版包装中，通常耗时 20~35 秒…`
  error.value = ''
  try {
    const api = window.pywebview?.api
    // 1. Force initialize project with chosen template and authentic video binding
    if (api?.huashu_init_project) {
      await api.huashu_init_project(props.projectId, tmplId, project.value?.name || '', prompt.value || '', true)
    } else {
      await request('POST', '/api/huashu/init', {
        projectId: props.projectId,
        templateId: tmplId,
        title: project.value?.name || '',
        scriptText: prompt.value || '',
        force: true
      })
    }
    // 2. Render 60fps packaged video
    let renderRes
    if (api?.huashu_render_project) {
      renderRes = await api.huashu_render_project(props.projectId, false, tmplId)
    } else {
      renderRes = await request('POST', '/api/huashu/render', {
        projectId: props.projectId,
        templateId: tmplId,
        blur: false
      })
    }
    message.value = `🎉 恭喜！已成功套用【${tmplName}】生成 60fps 商业大厂发布片！`
    // 3. Switch to huashu tab smoothly to view the finished render
    activeEngine.value = 'huashu'
  } catch (err) {
    error.value = '套用模版包装失败: ' + (err?.message || err)
  } finally {
    packagingHuashu.value = false
  }
}

async function exportCurrentVideo() {
  if (!currentResult.value?.fileId && !currentResult.value?.url) return
  try {
    const filename = `${project.value?.name || '视频'}_直出_${currentResult.value.duration || duration.value}s.mp4`
    if (window.pywebview?.api?.save_server_video_as && currentResult.value.fileId) {
      await window.pywebview.api.save_server_video_as(props.token, currentResult.value.fileId, filename)
      message.value = '成片已成功保存导出！'
    } else {
      // 浏览器环境 fallback 下载
      const a = document.createElement('a')
      a.href = currentVideoUrl.value
      a.download = filename
      a.target = '_blank'
      a.click()
    }
  } catch (err) {
    error.value = '导出失败: ' + String(err.message || err)
  }
}

onMounted(() => {
  loadData()
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="direct-studio-shell">
    <!-- 顶部导航栏 -->
    <header class="direct-header">
      <div class="direct-header-left">
        <button class="back-pill-btn" @click="emit('back')">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
          返回列表
        </button>
        <div class="direct-title-box">
          <span class="direct-badge">{{ isStickman ? '墨柴工坊 · 火柴人动作直出' : '通用视频 · 商业与科普制作' }}</span>
          <h2>{{ project?.name || '加载中...' }}</h2>
        </div>
      </div>



      <div class="direct-header-right">
        <span class="mode-tag">{{ isStickman ? '⚡ 墨柴工坊 · 火柴人动作直出' : '✨ 60fps 商业大片 · 模版直出工作台' }}</span>
        <button class="settings-btn" @click="emit('request-model-settings')">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          模型配置
        </button>
      </div>
    </header>

    <!-- 错误 / 提示消息 -->
    <div v-if="error" class="banner-box error-banner">{{ error }}</div>
    <div v-if="message" class="banner-box message-banner">{{ message }}</div>

    <!-- AI 视频模型直出与花叔模版工作台 -->
    <div class="direct-workspace-grid">
      <!-- 左栏：控制与提示词输入 -->
      <section class="direct-controls-panel">
        <!-- 画面风格：紧凑下拉 + 可选网格看板 -->
        <div v-if="isStickman" class="control-block style-compact-block">
          <div class="block-title-row">
            <div class="title-left-group">
              <label class="block-title">画面风格</label>
              <span class="active-style-badge">{{ currentStyleConfig.label }} · {{ currentStyleConfig.catLabel || '风格' }}</span>
            </div>
            <button
              type="button"
              class="toggle-grid-btn"
              @click="showStyleGrid = !showStyleGrid"
              :title="showStyleGrid ? '折叠为紧凑下拉' : '展开全部风格卡片看板'"
            >
              {{ showStyleGrid ? '收起卡片 ⯏' : `展开${filteredStickmanStyles.length}款风格看板 ⊞` }}
            </button>
          </div>

          <!-- 默认紧凑下拉选择器 -->
          <div v-if="!showStyleGrid" class="style-select-wrapper">
            <UiSelect
              v-model="selectedStyle"
              :options="styleSelectOptions"
              aria-label="画面风格选择"
              @change="onChooseStyle"
            />
          </div>

          <!-- 展开全景卡片看板 -->
          <div v-else class="style-grid-container">
            <div v-if="isStickman" class="studio-cat-tabs">
              <button
                v-for="cat in stickmanCategories"
                :key="cat.value"
                type="button"
                class="studio-cat-tab"
                :class="{ active: activeStyleCategory === cat.value }"
                @click="activeStyleCategory = cat.value"
              >
                {{ cat.label }}
              </button>
            </div>
            <div class="style-cards-grid">
              <button
                v-for="s in filteredStickmanStyles"
                :key="s.value"
                type="button"
                class="style-card-btn"
                :class="{ active: selectedStyle === s.value }"
                @click="onChooseStyle(s.value)"
              >
                <div class="st-card-top-row">
                  <strong>{{ s.label }}</strong>
                  <span v-if="s.catLabel" class="st-mini-tag">{{ s.catLabel }}</span>
                </div>
                <small>{{ s.tag }}</small>
              </button>
            </div>
          </div>
        </div>

        <!-- 动作与剧情描述 -->
        <div class="control-block prompt-compact-block">
          <div class="block-title-row">
            <div class="title-left-group">
              <label class="block-title">{{ isStickman ? '动作与剧情描述 (Prompt)' : '视频画面与内容描述 (Prompt)' }}</label>
            </div>
            <div class="prompt-action-btns">
              <button
                v-if="isStickman && project?.name"
                type="button"
                class="smart-prompt-btn"
                @click="applySmartPrompt"
                title="根据项目名称智能填充详细的多阶段火柴人分镜动作提示词"
              >
                ✨ 按项目「{{ project.name }}」智能填充
              </button>
              <button
                type="button"
                class="ai-expand-prompt-btn"
                :disabled="aiExpanding"
                @click="expandPromptWithAI"
                :title="isStickman ? '调用后台 AI 文本大模型深度扩写火柴人分镜 Prompt' : `根据项目名称「${project?.name || ''}」结合选中的花叔模版深度扩写商业分镜 Prompt`"
              >
                <span v-if="aiExpanding" class="spinner-small"></span>
                <span>{{ aiExpanding ? '🤖 正在深度扩写…' : (isStickman ? '🤖 AI 文本模型深度扩写' : `🤖 根据名称「${project?.name || '当前项目'}」智能扩写`) }}</span>
              </button>
            </div>
          </div>

          <!-- 快捷灵感预设：下拉形式合并，不占大面积纵向高度 -->
          <div class="preset-dropdown-row">
            <span class="preset-label">{{ isStickman ? "💡 快捷灵感：" : "✨ 花叔模版：" }}</span>
            <div class="preset-select-wrapper">
              <UiSelect
                v-model="selectedPresetKey"
                :options="presetSelectOptions"
                :placeholder="isStickman ? `💡 选择火柴人灵感模版快速载入 (${quickPresets.length}款可选)...` : `✨ 选择花叔商业发布片模版快速载入 (${quickPresets.length}款大厂流派)...`"
                @change="onSelectPreset"
              />
            </div>
          </div>

          <textarea
            v-model="prompt"
            class="prompt-textarea"
            rows="7"
            :placeholder="isStickman ? '描述火柴人的高能连招、打击感、极速冲刺、武器对决或搞笑滑稽动作...' : '描述宣传片或科普视频的完整展示过程、核心视效与光影运镜...'"
          ></textarea>
          <!-- 通用视频：当前已选花叔模版提示与快捷切换 -->
          <div v-if="!isStickman && selectedHuashuTemplate" class="huashu-active-badge">
            <span class="badge-icon">{{ selectedHuashuTemplate.icon }}</span>
            <div class="badge-body">
              <span class="badge-name">当前绑定模版：<strong>{{ selectedHuashuTemplate.name }}</strong></span>
              <span class="badge-tag">（{{ selectedHuashuTemplate.tag }} · 预设约 {{ selectedHuashuTemplate.duration }} 秒）</span>
            </div>
            <span class="badge-tip">生成后一键套用 60fps 动效</span>
          </div>
        </div>

        <!-- 核心规格设置：时长与画幅并排整合 -->
        <div class="control-block specs-compact-card">
          <div class="specs-compact-row">
            <div class="spec-compact-group">
              <span class="spec-label">时长：</span>
              <div class="duration-chips-sm">
                <button
                  v-for="d in durationOptions"
                  :key="d"
                  type="button"
                  class="chip-btn-sm"
                  :class="{ active: duration === d, 'is-recommended': d === 10, 'is-assemble': d > 10 }"
                  @click="duration = d"
                >
                  {{ d }}秒
                  <span v-if="d === 10" class="mini-badge-dot">单镜</span>
                  <span v-else-if="d > 10" class="mini-badge-dot assemble">组装</span>
                </button>
              </div>
            </div>
            <div class="spec-compact-group">
              <span class="spec-label">比例：</span>
              <div class="duration-chips-sm">
                <button
                  v-for="r in ratioOptions"
                  :key="r.value"
                  type="button"
                  class="chip-btn-sm"
                  :class="{ active: ratio === r.value }"
                  @click="ratio = r.value"
                >
                  {{ r.value }}
                </button>
              </div>
            </div>
          </div>
          <div v-if="duration > 10" class="duration-mini-tip">
            ✨ 已启用 Muse 全片组装模式（超过 10 秒 AI 后台自动多段生成并剪辑为 {{ duration }} 秒整片）
          </div>
        </div>

        <!-- 可选参考图与模型选择并排一行 -->
        <div class="control-block ref-and-model-row">
          <div class="ref-compact-box">
            <span class="spec-label">参考底图：</span>
            <div v-if="referenceImage" class="ref-mini-preview">
              <img :src="referenceImage.url" :alt="referenceImage.name" />
              <span class="ref-mini-name">{{ referenceImage.name }}</span>
              <button type="button" class="del-mini-btn" @click="removeReferenceImage">✕</button>
            </div>
            <button v-else type="button" class="upload-mini-btn" @click="pickReferenceImage">
              <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
              <span>上传/选择一张参考底图 (选填)</span>
            </button>
          </div>
          <div v-if="modelSelectOptions.length > 1" class="model-compact-box">
            <span class="spec-label">模型：</span>
            <UiSelect v-model="selectedModel" :options="modelSelectOptions" aria-label="生成模型" />
          </div>
        </div>

        <!-- 一键生成主按钮（始终在首屏，无需向下滚动） -->
        <div class="control-block submit-compact-block">
          <button
            type="button"
            class="direct-submit-btn"
            :disabled="generating || !prompt.trim()"
            @click="startDirectGeneration"
          >
            <span v-if="generating" class="spinner-dot"></span>
            <span v-else>🚀</span>
            <strong>{{ generating ? '正在调用视频模型生成中…' : (isStickman ? '一键直出完整视频' : `一键生成并套用【${currentHuashuTemplateName}】60fps商业大片`) }}</strong>
          </button>
          <div v-if="!isStickman" class="auto-huashu-row">
            <label class="auto-huashu-label">
              <input type="checkbox" v-model="autoPackageHuashu" class="auto-huashu-check" />
              <span>✨ 视频生成后自动套入【{{ currentHuashuTemplateName }}】渲染 60fps 商业大片 (质的飞跃)</span>
            </label>
          </div>
          <p class="submit-note">💡 直接调用底层视频模型生成整片，无需分镜拆分与衔接点调试。</p>
        </div>
      </section>

      <!-- 右栏：大屏监视器 & 抽卡历史 -->
      <section class="direct-monitor-panel">
        <div class="monitor-wrapper">
          <!-- 视频播放器 -->
          <div v-if="currentVideoUrl" class="player-container">
            <video
              :key="currentVideoUrl"
              :src="currentVideoUrl"
              controls
              autoplay
              loop
              class="active-video-player"
              @error="onVideoError"
            ></video>
            <div class="monitor-overlay-meta">
              <span>{{ currentResult?.style || selectedStyle }} · {{ currentResult?.duration || duration }}秒 · {{ currentResult?.ratio || ratio }}</span>
            </div>
          </div>

          <!-- 生成中状态 -->
          <div v-else-if="generating" class="monitor-empty-state is-generating">
            <div class="gen-progress-circle">
              <div class="circle-inner">{{ taskProgress }}%</div>
            </div>
            <h3>{{ taskStatusText || '正在渲染视频…' }}</h3>
            <p>视频直出中，成片渲染完成将自动在此大屏监视器播放</p>
          </div>

          <!-- 初始空状态 -->
          <div v-else class="monitor-empty-state">
            <div class="empty-icon">🎬</div>
            <h3>成片直出监视器</h3>
            <p>在左侧设定动作提示词与时长后，点击【一键直出完整视频】，无需分镜，成片直接呈现于此。</p>
          </div>
        </div>

        <!-- 监视器控制工具条 -->
        <div v-if="currentVideoUrl" class="monitor-toolbar">
          <button type="button" class="action-btn export-btn" @click="exportCurrentVideo">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
            导出完整视频 MP4
          </button>
          <button
            v-if="!isStickman"
            type="button"
            class="action-btn huashu-package-btn"
            :disabled="packagingHuashu"
            @click="packageWithHuashuTemplate"
          >
            <span v-if="packagingHuashu" class="spinner-dot"></span>
            <span v-else>✨</span>
            <strong>{{ packagingHuashu ? '正在套用模版包装中…' : `一键套用【${currentHuashuTemplateName}】60fps大厂动效包装` }}</strong>
          </button>
          <button type="button" class="action-btn re-roll-btn" :disabled="generating" @click="startDirectGeneration">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            效果不满意？再抽一次
          </button>
        </div>

        <!-- 抽卡历史版本列表 -->
        <div v-if="historyVersions.length" class="history-section">
          <div class="history-head">
            <strong>抽卡历史版本 ({{ historyVersions.length }})</strong>
            <small>可自由回看切换不同抽卡成片</small>
          </div>
          <div class="history-cards-scroll">
            <button
              v-for="(ver, idx) in historyVersions"
              :key="ver.id || idx"
              type="button"
              class="history-card"
              :class="{ active: currentResult?.id === ver.id }"
              @click="selectVersion(ver)"
            >
              <div class="h-index">#{{ historyVersions.length - idx }}</div>
              <div class="h-info">
                <strong>{{ ver.duration }}秒 · {{ ver.ratio }}</strong>
                <small>{{ ver.createdAt || '刚刚' }}</small>
              </div>
              <span v-if="currentResult?.id === ver.id" class="h-playing-pill">播放中</span>
            </button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* 紧凑排版优化样式 */
.direct-controls-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 18px;
  border-right: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-card);
  overflow-y: auto;
}

.active-style-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--theme-accent);
  background: var(--theme-accent-soft);
  padding: 2px 8px;
  border-radius: 4px;
}

.toggle-grid-btn {
  background: transparent;
  border: 1px dashed var(--theme-border-subtle);
  color: var(--theme-text-secondary);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.toggle-grid-btn:hover {
  color: var(--theme-accent);
  border-color: var(--theme-accent);
}

.style-select-wrapper {
  position: relative;
  width: 100%;
}

.preset-dropdown-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.preset-label {
  font-size: 12px;
  color: var(--theme-text-secondary);
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}
.preset-select-wrapper {
  flex: 1;
  min-width: 0;
}

.prompt-textarea {
  resize: vertical;
  min-height: 130px;
  height: 180px;
  max-height: 360px;
  font-size: 13px;
  line-height: 1.55;
  padding: 10px 12px;
}

.specs-compact-card {
  background: var(--theme-bg-surface);
  border: 1px solid var(--theme-border-subtle);
  border-radius: 8px;
  padding: 8px 12px;
  gap: 6px;
}
.specs-compact-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.spec-compact-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.spec-label {
  font-size: 12px;
  color: var(--theme-text-secondary);
  font-weight: 600;
  white-space: nowrap;
}
.duration-chips-sm {
  display: flex;
  align-items: center;
  gap: 4px;
}
.chip-btn-sm {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 8px;
  border-radius: 5px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-elevated);
  color: var(--theme-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.chip-btn-sm:hover {
  color: var(--theme-text-primary);
  border-color: var(--theme-accent);
}
.chip-btn-sm.active {
  background: var(--theme-accent);
  color: #fff;
  border-color: var(--theme-accent);
  font-weight: 600;
}
.mini-badge-dot {
  font-size: 9px;
  padding: 1px 3px;
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.08);
  font-weight: normal;
}
.chip-btn-sm.active .mini-badge-dot {
  background: rgba(255, 255, 255, 0.25);
  color: #fff;
}
.mini-badge-dot.assemble {
  color: #8b5cf6;
}
.chip-btn-sm.active .mini-badge-dot.assemble {
  color: #fff;
}

.duration-mini-tip {
  font-size: 11px;
  color: #7c3aed;
  background: #f5f3ff;
  border-radius: 4px;
  padding: 3px 6px;
  line-height: 1.4;
}

.ref-and-model-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.ref-compact-box {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}
.upload-mini-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px dashed var(--theme-border-subtle);
  background: var(--theme-bg-surface);
  color: var(--theme-text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}
.upload-mini-btn:hover {
  color: var(--theme-accent);
  border-color: var(--theme-accent);
}
.ref-mini-preview {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 6px;
  border-radius: 6px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-surface);
}
.ref-mini-preview img {
  width: 22px;
  height: 22px;
  object-fit: cover;
  border-radius: 3px;
}
.ref-mini-name {
  font-size: 11px;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.del-mini-btn {
  background: transparent;
  border: 0;
  color: #ef4444;
  font-size: 11px;
  cursor: pointer;
  padding: 0 2px;
}

.model-compact-box {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.submit-compact-block {
  margin-top: 2px;
  gap: 4px;
}
.submit-compact-block .direct-submit-btn {
  padding: 10px 16px;
  font-size: 14px;
}
.submit-compact-block .submit-note {
  font-size: 11px;
  margin: 0;
  color: var(--theme-text-secondary);
  text-align: center;
}

.direct-studio-shell {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 48px);
  background: var(--theme-bg-surface);
  color: var(--theme-text-primary);
  overflow: hidden;
}

/* 顶部 */
.direct-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  border-bottom: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-card);
  flex-shrink: 0;
}
.direct-header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.back-pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-elevated);
  color: var(--theme-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}
.back-pill-btn:hover {
  color: var(--theme-text-primary);
  border-color: var(--theme-accent);
}
.direct-title-box {
  display: flex;
  flex-direction: column;
}
.direct-badge {
  font-size: 11px;
  font-weight: 700;
  color: var(--theme-accent);
  letter-spacing: 0.5px;
}
.direct-title-box h2 {
  margin: 2px 0 0;
  font-size: 16px;
  font-weight: 600;
}
.direct-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.mode-tag {
  padding: 4px 10px;
  border-radius: 20px;
  background: color-mix(in srgb, #10b981 15%, transparent);
  color: #10b981;
  font-size: 11px;
  font-weight: 600;
}
.settings-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-elevated);
  color: var(--theme-text-secondary);
  font-size: 12px;
  cursor: pointer;
}

/* Banner */
.banner-box {
  padding: 8px 24px;
  font-size: 13px;
}
.error-banner {
  background: #fef2f2;
  color: #b91c1c;
  border-bottom: 1px solid #fecaca;
}
.message-banner {
  background: #f0fdf4;
  color: #15803d;
  border-bottom: 1px solid #bbf7d0;
}

/* 双栏主体 */
.direct-workspace-grid {
  display: grid;
  grid-template-columns: 460px minmax(0, 1fr);
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 左栏 */
.direct-controls-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 20px 24px;
  border-right: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-card);
  overflow-y: auto;
}
.control-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.block-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--theme-text-primary);
}
.block-title small {
  font-size: 11px;
  color: var(--theme-text-secondary);
  font-weight: normal;
}
.block-title-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.sub-hint {
  font-size: 11px;
  color: var(--theme-accent);
}

/* 风格卡片 */
.studio-cat-tabs {
  display: flex;
  gap: 4px;
}
.studio-cat-tab {
  padding: 2px 7px;
  border-radius: 5px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-elevated);
  color: var(--theme-text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}
.studio-cat-tab:hover {
  color: var(--theme-text-primary);
  border-color: var(--theme-accent);
}
.studio-cat-tab.active {
  background: var(--theme-accent-soft);
  border-color: var(--theme-accent);
  color: var(--theme-accent);
  font-weight: 600;
}
.st-card-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.st-mini-tag {
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--theme-accent) 15%, transparent);
  color: var(--theme-accent);
}
.style-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 8px;
}
.style-card-btn {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 9px 11px;
  border-radius: 8px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-elevated);
  color: var(--theme-text-primary);
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}
.style-card-btn:hover {
  border-color: var(--theme-accent);
}
.style-card-btn.active {
  border-color: var(--theme-accent);
  background: var(--theme-accent-soft);
}
.style-card-btn strong {
  font-size: 12px;
}
.style-card-btn small {
  font-size: 10px;
  color: var(--theme-text-secondary);
  line-height: 1.3;
}

/* 灵感标签 */
.preset-pills {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.preset-label {
  font-size: 11px;
  color: var(--theme-text-secondary);
}
.preset-pill {
  padding: 3px 8px;
  border-radius: 12px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-elevated);
  color: var(--theme-text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}
.preset-pill:hover {
  border-color: var(--theme-accent);
  color: var(--theme-accent);
}

.prompt-textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-input, var(--theme-bg-elevated));
  color: var(--theme-text-primary);
  font: inherit;
  font-size: 13px;
  line-height: 1.55;
  height: 180px;
  min-height: 130px;
  max-height: 360px;
  resize: vertical;
  outline: none;
}
.prompt-textarea:focus {
  border-color: var(--theme-accent);
}

/* 规格设置 */
.specs-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.spec-col {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.duration-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip-btn {
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-elevated);
  color: var(--theme-text-primary);
  font-size: 12px;
  cursor: pointer;
}
.chip-btn.active {
  border-color: var(--theme-accent);
  background: var(--theme-accent-soft);
  color: var(--theme-accent);
  font-weight: 600;
}

/* 参考图 */
.ref-image-area {
  display: flex;
  align-items: center;
  gap: 10px;
}
.upload-ref-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 12px;
  border-radius: 8px;
  border: 1px dashed var(--theme-border-subtle);
  background: var(--theme-bg-elevated);
  color: var(--theme-text-secondary);
  font-size: 12px;
  cursor: pointer;
}
.upload-ref-btn:hover {
  border-color: var(--theme-accent);
  color: var(--theme-accent);
}
.ref-thumb-box {
  position: relative;
  width: 90px;
  height: 90px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--theme-border-subtle);
}
.ref-thumb-box img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.del-thumb-btn {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(0,0,0,0.6);
  color: white;
  border: none;
  font-size: 11px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ref-thumb-box span {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 2px 4px;
  background: rgba(0,0,0,0.5);
  color: white;
  font-size: 9px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 提交按钮 */
.submit-block {
  margin-top: 6px;
  padding-top: 12px;
  border-top: 1px solid var(--theme-border-subtle);
}
.model-select-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--theme-text-secondary);
  margin-bottom: 10px;
}
.direct-submit-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 14px;
  border-radius: 10px;
  border: none;
  background: var(--theme-accent);
  color: white;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 4px 14px var(--theme-shadow);
  transition: all 0.2s;
}
.direct-submit-btn:hover:not(:disabled) {
  opacity: 0.95;
  transform: translateY(-1px);
}
.direct-submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.submit-note {
  font-size: 11px;
  color: var(--theme-text-secondary);
  margin: 8px 0 0;
  text-align: center;
}

/* 右栏大屏监视器 */
.direct-monitor-panel {
  display: flex;
  flex-direction: column;
  padding: 20px 24px;
  background: var(--theme-bg-surface);
  overflow-y: auto;
  gap: 16px;
}
.monitor-wrapper {
  flex: 1;
  min-height: 380px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 16px;
  background: #000;
  overflow: hidden;
  box-shadow: 0 10px 30px rgba(0,0,0,0.25);
  position: relative;
}
.player-container {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}
.active-video-player {
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
  object-fit: contain;
}
.monitor-overlay-meta {
  position: absolute;
  top: 14px;
  left: 14px;
  padding: 4px 10px;
  border-radius: 6px;
  background: rgba(0,0,0,0.6);
  color: white;
  font-size: 11px;
}

.monitor-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 30px;
  color: #888;
}
.empty-icon {
  font-size: 44px;
  margin-bottom: 12px;
}
.monitor-empty-state h3 {
  font-size: 16px;
  color: #ddd;
  margin: 0 0 6px;
}
.monitor-empty-state p {
  font-size: 12px;
  max-width: 380px;
  margin: 0;
  line-height: 1.6;
}

/* 生成中圆环 */
.gen-progress-circle {
  width: 68px;
  height: 68px;
  border-radius: 50%;
  border: 4px solid #222;
  border-top-color: var(--theme-accent);
  animation: spin 1.2s linear infinite;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
}
.circle-inner {
  font-size: 12px;
  font-weight: 700;
  color: white;
  animation: counter-spin 1.2s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
@keyframes counter-spin {
  to { transform: rotate(-360deg); }
}

/* 监视器操作栏 */
.monitor-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-radius: 10px;
  background: var(--theme-bg-card);
  border: 1px solid var(--theme-border-subtle);
}
.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 15px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.export-btn {
  background: var(--theme-accent);
  color: white;
  border: 1px solid var(--theme-accent);
}
.re-roll-btn {
  background: var(--theme-bg-elevated);
  color: var(--theme-text-primary);
  border: 1px solid var(--theme-border-subtle);
}
.re-roll-btn:hover {
  border-color: var(--theme-accent);
}

/* 抽卡历史 */
.history-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.history-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 12px;
}
.history-head small {
  color: var(--theme-text-secondary);
}
.history-cards-scroll {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.history-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-card);
  color: var(--theme-text-primary);
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}
.history-card:hover {
  border-color: var(--theme-accent);
}
.history-card.active {
  border-color: var(--theme-accent);
  background: var(--theme-accent-soft);
}
.h-index {
  font-size: 12px;
  font-weight: 700;
  color: var(--theme-accent);
}
.h-info {
  display: flex;
  flex-direction: column;
  text-align: left;
}
.h-info strong {
  font-size: 12px;
}
.h-info small {
  font-size: 10px;
  color: var(--theme-text-secondary);
}
.h-playing-pill {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--theme-accent);
  color: white;
}

.title-left-group {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.prompt-action-btns {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ai-expand-prompt-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%);
  color: #7c3aed;
  border: 1px solid #c4b5fd;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  box-shadow: 0 1px 2px rgba(124, 58, 237, 0.08);
  transition: all 0.15s ease;
}

.ai-expand-prompt-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%);
  border-color: #8b5cf6;
  transform: translateY(-1px);
}

.ai-expand-prompt-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.spinner-small {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(124, 58, 237, 0.2);
  border-radius: 50%;
  border-top-color: #7c3aed;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.smart-prompt-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  color: #2563eb;
  border: 1px solid #93c5fd;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  box-shadow: 0 1px 2px rgba(37, 99, 235, 0.08);
  transition: all 0.2s ease;
}

.smart-prompt-btn:hover {
  background: #dbeafe;
  border-color: #93c5fd;
  transform: translateY(-1px);
}

.title-with-warn {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.duration-warn-pill {
  font-size: 11px;
  color: #d97706;
  background: #fef3c7;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.chip-btn.is-recommended {
  position: relative;
}

.best-badge {
  font-size: 10px;
  color: #16a34a;
  background: #dcfce7;
  padding: 1px 4px;
  border-radius: 3px;
  margin-left: 3px;
}

.duration-hint-text {
  margin: 6px 0 0 0;
  font-size: 11.5px;
  color: #64748b;
  line-height: 1.4;
}

.duration-mode-pill {
  font-size: 11px;
  color: #6366f1;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  padding: 1px 7px;
  border-radius: 4px;
  font-weight: 600;
}

.duration-mode-pill.is-shot {
  color: #16a34a;
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.assemble-badge {
  font-size: 10px;
  color: #4f46e5;
  background: #e0e7ff;
  padding: 1px 4px;
  border-radius: 3px;
  margin-left: 3px;
}

.engine-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f1f5f9;
  padding: 3px 6px;
  border-radius: 9999px;
  border: 1px solid #e2e8f0;
}

.engine-tab-btn {
  border: none;
  background: transparent;
  padding: 5px 13px;
  border-radius: 9999px;
  font-size: 12.5px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s ease;
}

.engine-tab-btn:hover {
  color: #0f172a;
}

.engine-tab-btn.active {
  background: #ffffff;
  color: #0284c7;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.huashu-embed-container {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: #ffffff;
}

/* 花叔模版绑定胶囊与包装按钮 */
.huashu-active-badge {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 10px;
  padding: 8px 14px;
  background: rgba(197, 160, 89, 0.08);
  border: 1px solid rgba(197, 160, 89, 0.28);
  border-radius: 8px;
  font-size: 12px;
  color: var(--theme-text-primary);
}
.badge-icon {
  font-size: 16px;
}
.badge-body {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
}
.badge-name strong {
  color: #dfba73;
}
.badge-tag {
  color: var(--theme-text-muted);
}
.badge-tip {
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(197, 160, 89, 0.16);
  color: #dfba73;
  font-size: 11px;
  font-weight: 600;
}
.auto-huashu-row {
  margin-top: 8px;
  margin-bottom: 2px;
}
.auto-huashu-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: #c5a059;
  font-weight: 500;
  cursor: pointer;
  user-select: none;
}
.auto-huashu-check {
  accent-color: #c5a059;
  width: 15px;
  height: 15px;
  cursor: pointer;
}
.huashu-package-btn {
  background: linear-gradient(135deg, #c5a059 0%, #dfba73 50%, #b8934b 100%);
  color: #12100e !important;
  font-weight: 700;
  border: 1px solid #dfba73;
  box-shadow: 0 2px 10px rgba(197, 160, 89, 0.35);
  transition: all 0.2s ease;
}
.huashu-package-btn:hover:not(:disabled) {
  filter: brightness(1.1);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(197, 160, 89, 0.5);
}


/* 步骤数字徽标 */
.step-num-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: linear-gradient(135deg, #c5a059 0%, #dfba73 100%);
  color: #12100e;
  font-weight: 800;
  font-size: 11px;
  box-shadow: 0 1px 4px rgba(197, 160, 89, 0.4);
}

/* 步骤一：主题名称与扩写行 */
.huashu-topic-block {
  padding-bottom: 12px;
}
.topic-hint-tag {
  font-size: 11px;
  color: var(--theme-text-muted);
}
.topic-input-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.topic-input {
  flex: 1;
  height: 38px;
  padding: 0 12px;
  background: var(--theme-bg-input, rgba(0, 0, 0, 0.25));
  border: 1px solid var(--theme-border-color, rgba(255, 255, 255, 0.1));
  border-radius: 8px;
  color: var(--theme-text-primary);
  font-size: 13px;
  transition: border-color 0.2s ease;
}
.topic-input:focus {
  outline: none;
  border-color: #dfba73;
  box-shadow: 0 0 0 2px rgba(223, 186, 115, 0.2);
}
.topic-expand-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 38px;
  padding: 0 16px;
  background: linear-gradient(135deg, #c5a059 0%, #dfba73 100%);
  color: #12100e;
  border: none;
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  box-shadow: 0 2px 8px rgba(197, 160, 89, 0.3);
  transition: all 0.2s ease;
}
.topic-expand-btn:hover:not(:disabled) {
  filter: brightness(1.1);
  transform: translateY(-1px);
}
.topic-expand-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* 步骤二：花叔模版卡片选择网格 */
.huashu-templates-block {
  padding-bottom: 12px;
}
.tpl-toggle-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.active-tpl-pill {
  font-size: 11.5px;
  color: #dfba73;
  font-weight: 600;
  background: rgba(197, 160, 89, 0.12);
  padding: 2px 8px;
  border-radius: 4px;
}
.toggle-tpl-grid-btn {
  background: none;
  border: none;
  color: var(--theme-text-muted);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 6px;
}
.toggle-tpl-grid-btn:hover {
  color: var(--theme-text-primary);
}

.huashu-grid-container {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-top: 10px;
  max-height: 250px;
  overflow-y: auto;
  padding-right: 4px;
}
.huashu-grid-container.compact-view {
  max-height: 125px;
}
.huashu-tpl-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 10px 12px;
  background: var(--theme-bg-card, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--theme-border-color, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
}
.huashu-tpl-card:hover {
  border-color: rgba(223, 186, 115, 0.4);
  background: rgba(223, 186, 115, 0.04);
}
.huashu-tpl-card.active {
  border-color: #dfba73;
  background: rgba(197, 160, 89, 0.12);
  box-shadow: 0 0 0 1px #dfba73, 0 2px 10px rgba(197, 160, 89, 0.25);
}
.tpl-card-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.tpl-card-icon {
  font-size: 15px;
}
.tpl-card-title {
  font-size: 12.5px;
  color: var(--theme-text-primary);
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.huashu-tpl-card.active .tpl-card-title {
  color: #dfba73;
}
.tpl-card-tags {
  font-size: 11px;
  color: var(--theme-text-muted);
  line-height: 1.3;
  margin-bottom: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tpl-card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 10.5px;
}
.tpl-energy-badge {
  color: #dfba73;
  background: rgba(197, 160, 89, 0.18);
  padding: 1px 6px;
  border-radius: 3px;
  font-weight: 600;
}
.tpl-card-duration {
  color: var(--theme-text-muted);
}
.tpl-check-mark {
  color: #dfba73;
  font-weight: 800;
}

/* 步骤三：Prompt 元信息行 */
.prompt-meta-group {
  display: flex;
  align-items: center;
  gap: 10px;
}
.prompt-len-tag {
  font-size: 11px;
  color: var(--theme-text-muted);
}
.clear-prompt-btn {
  background: none;
  border: none;
  color: #dfba73;
  font-size: 11.5px;
  cursor: pointer;
  padding: 0;
}
.clear-prompt-btn:hover {
  text-decoration: underline;
}

</style>
