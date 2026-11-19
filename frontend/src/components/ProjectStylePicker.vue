<script setup>
import { computed, ref } from 'vue'
import {
  PROJECT_STYLE_GROUPS,
  PROJECT_GENRE_OPTIONS,
  PROJECT_GENRE_CATEGORIES,
  OFFICIAL_MANJU_GENRES,
  getProjectVisualChoice,
  getProjectGenres,
  getProjectGenreName,
  getProjectStyleSummary,
  getProjectStyleDescription,
  isLegacyProjectStyle
} from './projectFormOptions.js'

const props = defineProps({ modelValue: { type: Object, required: true } })
const emit = defineEmits(['update:modelValue'])
const query = ref('')
const activeGenreCategory = ref('all')
const visual = computed(() => getProjectVisualChoice(props.modelValue))
const group = computed(() => PROJECT_STYLE_GROUPS.find(item => item.options.some(option => option.value === visual.value)) || PROJECT_STYLE_GROUPS[0])
const genres = computed(() => getProjectGenres(props.modelValue))

const options = computed(() => {
  const term = query.value.trim().toLowerCase()
  if (term) {
    return PROJECT_GENRE_OPTIONS.filter(option =>
      option.label.toLowerCase().includes(term) ||
      (option.desc && option.desc.toLowerCase().includes(term)) ||
      (option.category && option.category.toLowerCase().includes(term))
    )
  }
  if (activeGenreCategory.value !== 'all') {
    return PROJECT_GENRE_OPTIONS.filter(option => option.category === activeGenreCategory.value)
  }
  // 默认全部时优先展示 21 款官方漫剧题材
  return PROJECT_GENRE_OPTIONS.filter(option => option.isOfficial || genres.value.includes(option.value))
})

const customGenres = computed(() => genres.value.filter(value => !PROJECT_GENRE_OPTIONS.some(option => option.value === value)))
const customCandidate = computed(() => {
  const term = query.value.trim()
  return term && !PROJECT_GENRE_OPTIONS.some(option => option.label === term) && !genres.value.includes(term) ? term : ''
})

const selectedOfficialGenres = computed(() => {
  return genres.value
    .map(val => OFFICIAL_MANJU_GENRES.find(g => g.id === val || g.name === val))
    .filter(Boolean)
})

function update(fields) { emit('update:modelValue', { ...props.modelValue, ...fields }) }
function selectVisual(value) { update({ style: value, storyGenres: genres.value }) }
function toggleGenre(value) {
  update({
    style: isLegacyProjectStyle(props.modelValue) ? visual.value : props.modelValue.style,
    storyGenres: genres.value.includes(value) ? genres.value.filter(item => item !== value) : [...genres.value, value]
  })
}
function addGenre() {
  const term = query.value.trim()
  const known = PROJECT_GENRE_OPTIONS.find(option => option.label === term)
  const value = known?.value || customCandidate.value
  if (value && !genres.value.includes(value)) toggleGenre(value)
  query.value = ''
}
</script>

<template>
  <section class="project-style-picker" aria-label="项目画面风格与故事题材">
    <!-- 画面风格选择 -->
    <fieldset>
      <legend>画面风格 <span>决定画面长什么样 · 单选</span></legend>
      <div class="visual-groups" aria-label="画面类别">
        <button
          v-for="item in PROJECT_STYLE_GROUPS"
          :key="item.label"
          type="button"
          :aria-pressed="group === item"
          :class="{ selected: group === item }"
          @click="selectVisual(item.options[0].value)"
        >
          {{ item.label }}
        </button>
      </div>
      <div v-if="group && group.label !== '自定义'" class="style-options" aria-label="具体画风">
        <button
          v-for="option in group.options"
          :key="option.value"
          type="button"
          :aria-pressed="visual === option.value"
          :class="{ selected: visual === option.value }"
          @click="selectVisual(option.value)"
        >
          <span v-if="visual === option.value" aria-hidden="true">✓ </span>{{ option.label }}
        </button>
      </div>
      <p v-if="isLegacyProjectStyle(modelValue)" class="style-hint">已保留原项目风格。重新选择画风或题材后，将使用新的组合设置。</p>
      <p v-else-if="!group" class="style-hint">已保留原风格：{{ modelValue.style }}。可选择新的画风进行调整。</p>
    </fieldset>

    <!-- 故事题材选择（21大官方AI漫剧全流程模板） -->
    <fieldset class="genre-field">
      <legend>故事题材 <span>21大官方AI漫剧题材库 · 可多选、可自定义</span></legend>
      
      <!-- 题材类别筛选 Tab -->
      <div class="genre-category-tabs" aria-label="题材分类筛选">
        <button
          v-for="cat in PROJECT_GENRE_CATEGORIES"
          :key="cat.id"
          type="button"
          class="cat-tab-btn"
          :class="{ active: activeGenreCategory === cat.id }"
          @click="activeGenreCategory = cat.id"
        >
          {{ cat.label }}
        </button>
      </div>

      <!-- 题材按钮列表 -->
      <div class="genre-options" aria-label="故事题材">
        <button
          v-for="option in options"
          :key="option.value"
          type="button"
          :aria-pressed="genres.includes(option.value)"
          :class="{ selected: genres.includes(option.value) }"
          :title="option.desc || option.label"
          @click="toggleGenre(option.value)"
        >
          <span v-if="genres.includes(option.value)" aria-hidden="true">✓ </span>
          <span v-if="option.icon" class="genre-icon">{{ option.icon }} </span>
          {{ option.label }}
        </button>
        <button
          v-for="value in customGenres"
          :key="value"
          type="button"
          class="selected custom-genre"
          :aria-label="`移除题材：${getProjectGenreName(value)}`"
          @click="toggleGenre(value)"
        >
          {{ getProjectGenreName(value) }} ×
        </button>
      </div>

      <!-- 搜索与自定义题材添加 -->
      <div class="genre-search">
        <input
          v-model="query"
          aria-label="搜索或添加题材"
          placeholder="搜索 21 种漫剧题材（如：修仙、重生、民俗、机甲、商战）或输入自定义题材..."
          maxlength="40"
          @keydown.enter.prevent="addGenre"
        />
        <button v-if="customCandidate" type="button" @click="addGenre">添加「{{ customCandidate }}」</button>
      </div>

      <!-- 已选官方漫剧题材的专属导演节奏与视听指导卡 -->
      <div v-if="selectedOfficialGenres.length" class="genre-pacing-preview">
        <div v-for="g in selectedOfficialGenres" :key="g.id" class="pacing-card">
          <div class="pacing-title">
            <span>{{ g.icon }}</span>
            <strong>{{ g.name }}</strong>
            <span class="pacing-tag">{{ g.category }}漫剧</span>
          </div>
          <p class="pacing-desc">{{ g.desc }}</p>
          <div class="pacing-rule">
            <span class="rule-label">🎬 导演节奏律：</span>
            <span>{{ g.pacing }}</span>
          </div>
        </div>
      </div>
      <p v-else class="style-hint">点击上方选择 1~2 种漫剧题材，系统将自动注入对应的分镜快慢剪辑律与人物资产规范。</p>
    </fieldset>

    <!-- 画面描述与补充 -->
    <label v-if="visual === 'custom-style'" class="notes-label">画面风格描述 <span>必填</span>
      <textarea
        :value="modelValue.styleNotes || ''"
        aria-label="画面风格描述"
        rows="3"
        maxlength="2000"
        placeholder="例如：东方暗黑玄幻国漫，电影级2.5D动画，体积光，重粒子光晕……"
        @input="update({ styleNotes: $event.target.value })"
      ></textarea>
    </label>
    <details v-else class="style-notes" :open="Boolean(modelValue.styleNotes)">
      <summary>补充画面要求 <span>选填</span></summary>
      <textarea
        :value="modelValue.styleNotes || ''"
        aria-label="补充画面要求"
        rows="2"
        maxlength="2000"
        placeholder="例如：低饱和色彩、柔和轮廓光、服装材质更细腻、特写突出眼神交锋……"
        @input="update({ styleNotes: $event.target.value })"
      ></textarea>
    </details>

    <!-- 风格与题材总览预览卡 -->
    <div class="style-combination-preview" aria-live="polite">
      <span>当前视听配置</span><strong>{{ getProjectStyleSummary(modelValue) }}</strong>
      <p>{{ getProjectStyleDescription(modelValue) }}</p>
    </div>
  </section>
</template>

<style scoped>
.project-style-picker {
  display: grid;
  gap: 20px;
  min-width: 0;
  margin: 18px 0;
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
  margin-bottom: 11px;
  padding: 0;
  font-size: 14px;
  font-weight: 700;
}
legend span,
.notes-label > span,
summary span {
  margin-left: 8px;
  color: var(--theme-text-secondary);
  font-size: 12px;
  font-weight: 400;
}
.visual-groups,
.style-options,
.genre-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
button {
  padding: 8px 12px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 8px;
  background: var(--theme-bg-input, var(--theme-bg-surface));
  color: var(--theme-text-primary);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  line-height: 1.4;
  transition: all 0.15s ease;
}
button:hover {
  border-color: var(--theme-accent);
  background: var(--theme-accent-soft);
}
button:focus-visible,
input:focus-visible,
textarea:focus-visible,
summary:focus-visible {
  outline: 2px solid var(--theme-accent);
  outline-offset: 2px;
}
button.selected {
  color: var(--theme-accent-text);
  border-color: var(--theme-accent-border, var(--theme-accent));
  background: var(--theme-accent-soft);
  font-weight: 600;
}
.visual-groups {
  padding: 4px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 10px;
  background: var(--theme-bg-surface);
}
.visual-groups button {
  flex: 1 0 auto;
  border-color: transparent;
  background: transparent;
  padding: 8px 10px;
}
.visual-groups button.selected {
  background: var(--theme-bg-elevated);
  border-color: var(--theme-accent-border, var(--theme-border-subtle));
  box-shadow: 0 1px 4px var(--theme-shadow);
}
.style-options {
  margin-top: 10px;
}
.style-hint {
  margin: 9px 0 0;
  color: var(--theme-text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

/* 21大题材分类 Tab 切换器 */
.genre-category-tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.cat-tab-btn {
  padding: 4px 10px;
  font-size: 12px;
  border-radius: 6px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-surface);
  color: var(--theme-text-secondary);
  cursor: pointer;
}
.cat-tab-btn.active {
  background: var(--theme-accent-soft);
  border-color: var(--theme-accent);
  color: var(--theme-accent-text);
  font-weight: 600;
}

.genre-options {
  margin-top: 6px;
}
.genre-icon {
  margin-right: 4px;
}
.genre-search {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.genre-search input {
  flex: 1;
  min-width: 170px;
}
.genre-search button {
  max-width: 100%;
  overflow-wrap: anywhere;
}
input,
textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 8px;
  color: var(--theme-text-primary);
  background: var(--theme-bg-input, var(--theme-bg-surface));
  font: inherit;
  font-size: 13px;
  line-height: 1.6;
}
.project-style-picker textarea {
  display: block;
  min-height: 72px;
  height: auto;
  margin-top: 9px;
  resize: vertical;
}
.notes-label {
  font-size: 13px;
  font-weight: 600;
}
summary {
  font-size: 13px;
  cursor: pointer;
  color: var(--theme-text-secondary);
}

/* 题材节奏律专属卡片 */
.genre-pacing-preview {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}
.pacing-card {
  padding: 10px 14px;
  border-radius: 8px;
  background: rgba(var(--theme-accent-rgb, 124, 58, 237), 0.05);
  border: 1px solid rgba(var(--theme-accent-rgb, 124, 58, 237), 0.15);
}
.pacing-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.pacing-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--theme-accent-soft);
  color: var(--theme-accent-text);
}
.pacing-desc {
  margin: 4px 0 6px;
  font-size: 12px;
  color: var(--theme-text-secondary);
  line-height: 1.5;
}
.pacing-rule {
  font-size: 12px;
  color: var(--theme-text-primary);
  line-height: 1.5;
  background: var(--theme-bg-surface);
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px dashed var(--theme-border-subtle);
}
.rule-label {
  color: var(--theme-accent-text);
  font-weight: 600;
}

.style-combination-preview {
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--theme-accent-soft);
  border: 1px solid var(--theme-border-subtle);
  overflow-wrap: anywhere;
}
.style-combination-preview > span {
  margin-right: 10px;
  font-size: 11px;
  color: var(--theme-text-secondary);
}
.style-combination-preview strong {
  font-size: 13px;
}
.style-combination-preview p {
  margin: 7px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--theme-text-secondary);
}
@media (max-width: 540px) {
  legend span {
    display: block;
    margin: 5px 0 0;
  }
  .visual-groups button {
    flex-basis: 27%;
  }
}
</style>
