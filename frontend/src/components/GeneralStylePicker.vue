<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Object, required: true }
})
const emit = defineEmits(['update:modelValue'])

const GENERAL_STYLE_GROUPS = [
  {
    label: '商业视觉',
    options: [
      { value: 'tech-future', label: '科技未来', desc: '商业科技大片质感，深灰冷调，光纤微光与发光数字光效，精密质感，4K超清。', prefix: '商业科技质感，极简深灰冷调，光纤流动，发光HUD数字光效，精密机械微距，金属反光，4K超清画质，无水印文字。' },
      { value: 'luxury-high', label: '高级奢华', desc: '高端品牌广告质感，高级暖光与侧逆光，细腻光影雕琢，丝绸与金属材质。', prefix: '高端奢华广告质感，高级暖光与侧逆光，细腻光影雕琢，微距景深，丝绸与贵金属材质，电影级调色，高贵典雅，4K画质。' },
      { value: 'lifestyle-warm', label: '现代生活', desc: '现代商业生活广告质感，自然阳光漫射，温暖通透氛围，轻松明快，人物自然生动。', prefix: '现代商业生活广告质感，自然阳光漫射，温暖通透氛围，轻松明快，自然笑容，生动生活气息，浅景深摄影。' },
      { value: 'epic-brand', label: '恢弘史诗', desc: '大片级宏大宣传片质感，壮阔航拍大广角，天光破云，丁达尔光束，震撼视界。', prefix: '大片级宏大宣传片质感，壮阔航拍大广角，天光破云，丁达尔光束，慢门流光，震撼视界，电影宽银幕质感，4K画质。' },
      { value: 'documentary-real', label: '纪实人文', desc: '人文纪录片质感，自然环境光，深沉低饱和纪实影调，真实纹理与厚重视效。', prefix: '人文纪录片质感，自然环境光，深沉低饱和纪实影调，胶片颗粒，真实纹理，深刻厚重视觉呈现，4K无水印。' },
    ]
  },
  {
    label: '极简与动效',
    options: [
      { value: 'keynote-dark', label: '发布会 UI', desc: '大厂发布会暗黑质感，深邃背景，发光毛玻璃卡片弹性推入，高光立体UI。', prefix: '大厂发布会级UI动效质感，暗黑微光背景，毛玻璃卡片弹性推入，高光立体界面，极简科技美学，4K' },
      { value: 'kinetic-type', label: '动态大字', desc: '纯色高饱和撞色，动态大字排版，节奏卡点，视觉冲击力强。', prefix: '动态大字排版动效，纯色撞色背景，极简高饱和几何元素，高冲击力文字节奏，现代设计风格，4K' },
      { value: 'whiteboard-clean', label: '思维白板', desc: '纯白底白板手绘草图，纯黑线条，流程图与箭头连贯推导，逻辑清晰。', prefix: '极简思维导图白板草图风格，纯白背景，黑色单线手绘，清晰流程与逻辑箭头，清爽干净' },
      { value: 'vox-collage', label: '杂志拼贴', desc: 'Vox 风格桌面剪贴画，纸质质感，截图便签与红线穿引，荧光笔重点标记。', prefix: 'Vox风格杂志拼贴视效，质感桌面，便签纸与截图元素，红线关联图谱，荧光笔高光批注' },
    ]
  },
  {
    label: '3D 空间立体',
    options: [
      { value: '3d-studio', label: '3D 摄影棚', desc: '三维光影摄影棚，产品悬浮展示，环绕连续运镜与细腻光照材质。', prefix: '三维光影摄影棚，三维连续运镜，悬浮产品立体展示，柔和摄影棚光照，细腻材质与景深' },
      { value: '3d-realistic', label: '写实 CG', desc: '写实3D CG画面，可信的人体与物理材质，细致纹理和自然的电影感光影。', prefix: '写实3D CG，可信人体比例与物理材质，细致纹理，电影感光影' },
      { value: 'ui-space', label: '界面层级', desc: '3D 悬浮界面拆解，面板在空间中多层错落飞掠，纵深立体感强烈。', prefix: '3D界面层级空间悬浮，UI多层拆解，空间飞掠穿梭运镜，现代科技立体空间，4K' },
    ]
  },
  {
    label: '写实影像',
    options: [
      { value: 'real-cinematic', label: '真人电影感', desc: '真人写实电影摄影，人物肤质与空间尺度自然，细致影调，电影级视效。', prefix: '真人写实电影摄影，自然肤质与空间尺度，细致电影影调' },
      { value: 'real-documentary', label: '纪实摄影', desc: '纪实摄影，可信的生活纹理与自然环境光，克制构图，现场感强。', prefix: '纪实摄影，自然环境光，可信生活纹理，克制构图与现场感' },
    ]
  },
  {
    label: '设计与手作',
    options: [
      { value: 'ink-painting', label: '水墨写意', desc: '东方水墨画面，墨色层次、干湿笔触与留白，高雅空灵意境。', prefix: '水墨画面，墨色层次，干湿笔触，讲究留白与构图' },
      { value: 'watercolor', label: '水彩插画', desc: '透明叠色、纸张肌理与柔和笔触，色彩温润通透。', prefix: '水彩插画，透明叠色，纸张肌理，柔和笔触' },
      { value: 'storybook', label: '绘本插画', desc: '统一的手绘造型、细腻纹理与清晰叙事构图。', prefix: '绘本插画，统一手绘造型，细腻纹理，清晰叙事构图' },
      { value: 'kurzgesagt-flat', label: '扁平科普', desc: 'Kurzgesagt 风格发光扁平矢量插画，色彩鲜明，宇宙与科技感。', prefix: 'Kurzgesagt风格扁平矢量插画，色彩鲜艳，微光发光粒子，现代科普图解' },
    ]
  },
  {
    label: '自定义',
    options: [
      { value: 'custom-style', label: '自定义画面风格', desc: '自由描述你期望的画面基调、视觉材质、光影与调色。', prefix: '' }
    ]
  }
]

const currentStyle = computed(() => props.modelValue.style || 'tech-future')
const activeGroup = computed(() => {
  return GENERAL_STYLE_GROUPS.find(g => g.options.some(o => o.value === currentStyle.value)) || GENERAL_STYLE_GROUPS[0]
})

const currentOption = computed(() => {
  for (const g of GENERAL_STYLE_GROUPS) {
    const found = g.options.find(o => o.value === currentStyle.value)
    if (found) return found
  }
  return GENERAL_STYLE_GROUPS[0].options[0]
})

function selectGroup(g) {
  emit('update:modelValue', { ...props.modelValue, style: g.options[0].value })
}

function selectStyle(val) {
  emit('update:modelValue', { ...props.modelValue, style: val })
}

function updateNotes(text) {
  emit('update:modelValue', { ...props.modelValue, styleNotes: text })
}
</script>

<template>
  <section class="general-style-picker" aria-label="通用视频画面风格">
    <fieldset>
      <legend>画面视觉基调 <span>决定视频的视觉气质与排版美学 · 单选</span></legend>
      <div class="visual-groups" aria-label="画面风格大类">
        <button
          v-for="g in GENERAL_STYLE_GROUPS"
          :key="g.label"
          type="button"
          :class="{ selected: activeGroup.label === g.label }"
          @click="selectGroup(g)"
        >
          {{ g.label }}
        </button>
      </div>

      <div v-if="activeGroup && activeGroup.label !== '自定义'" class="style-options" aria-label="具体风格选项">
        <button
          v-for="opt in activeGroup.options"
          :key="opt.value"
          type="button"
          :class="{ selected: currentStyle === opt.value }"
          @click="selectStyle(opt.value)"
        >
          <span v-if="currentStyle === opt.value" aria-hidden="true">✓ </span>{{ opt.label }}
        </button>
      </div>
    </fieldset>

    <label v-if="currentStyle === 'custom-style'" class="notes-label">
      自定义画面风格描述 <span>必填</span>
      <textarea
        :value="modelValue.styleNotes || ''"
        rows="3"
        maxlength="1000"
        placeholder="例如：科技蓝冷调微光，毛玻璃卡片悬浮，动态大字排版，现代极简大厂发布会质感……"
        @input="updateNotes($event.target.value)"
      ></textarea>
    </label>
    <details v-else class="style-notes" :open="Boolean(modelValue.styleNotes)">
      <summary>补充画面视觉要求 <span>选填</span></summary>
      <textarea
        :value="modelValue.styleNotes || ''"
        rows="2"
        maxlength="1000"
        placeholder="例如：低饱和冷灰调、柔和边缘轮廓光、高对比度排版……"
        @input="updateNotes($event.target.value)"
      ></textarea>
    </details>

    <div class="style-preview-box">
      <div class="style-preview-header">
        <span>当前风格：</span>
        <strong>{{ currentOption.label }}</strong>
        <small>({{ activeGroup.label }})</small>
      </div>
      <p>{{ currentOption.desc }}</p>
    </div>
  </section>
</template>

<style scoped>
.general-style-picker {
  display: grid;
  gap: 16px;
  min-width: 0;
  margin: 14px 0;
  color: var(--theme-text-primary);
}

fieldset {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

legend {
  width: 100%;
  margin-bottom: 10px;
  padding: 0;
  font-size: 13px;
  font-weight: 700;
}

legend span, .notes-label > span, summary span {
  margin-left: 8px;
  color: var(--theme-text-secondary);
  font-size: 12px;
  font-weight: 400;
}

.visual-groups, .style-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.visual-groups {
  padding: 4px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 10px;
  background: var(--theme-bg-surface);
  margin-bottom: 10px;
}

.visual-groups button {
  flex: 1 0 auto;
  border: 1px solid transparent;
  background: transparent;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
  color: var(--theme-text-secondary);
  cursor: pointer;
  line-height: 1.4;
  transition: all 0.15s ease;
}

.visual-groups button:hover {
  color: var(--theme-text-primary);
  background: rgba(255, 255, 255, 0.05);
}

.visual-groups button.selected {
  color: var(--theme-accent-text);
  background: var(--theme-accent-soft);
  font-weight: 700;
  border-color: var(--theme-accent);
}

.style-options button {
  padding: 8px 14px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 8px;
  background: var(--theme-bg-input, var(--theme-bg-surface));
  color: var(--theme-text-primary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  line-height: 1.4;
  transition: all 0.15s ease;
}

.style-options button:hover {
  border-color: var(--theme-accent);
  background: var(--theme-accent-soft);
}

.style-options button.selected {
  color: var(--theme-accent-text);
  border-color: var(--theme-accent-border, var(--theme-accent));
  background: var(--theme-accent-soft);
  font-weight: 600;
}

.notes-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
}

.notes-label textarea, .style-notes textarea {
  width: 100%;
  box-sizing: border-box;
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 8px;
  background: var(--theme-bg-input, var(--theme-bg-elevated));
  color: var(--theme-text-primary);
  font: inherit;
  font-size: 12px;
  line-height: 1.7;
}

.style-notes summary {
  font-size: 12px;
  color: var(--theme-text-secondary);
  cursor: pointer;
}

.style-preview-box {
  padding: 12px 14px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 10px;
  background: var(--theme-bg-elevated);
}

.style-preview-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  margin-bottom: 6px;
}

.style-preview-header strong {
  color: var(--theme-accent);
}

.style-preview-header small {
  color: var(--theme-text-secondary);
}

.style-preview-box p {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--theme-text-secondary);
}
</style>
