# -*- coding: utf-8 -*-
"""Dynamic Skill Loader & Persistent Rule Overlay for CDTV.

This module discovers skills in the SKILL/ directory, integrates the 21 official
AI Manju genres (ai-manju-skills), and overlays persistent user rules from custom_rules/.
"""

import os
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

BASE_DIR = Path(__file__).resolve().parent

NARRATIVE_TRANSITION_RULES = """
【跨场景声画接力·通用规则】
同场景连续动作优先真实尾帧续接；换场景不能只写“切到”，必须成对规划上一镜收尾和下一镜开场。
连续剧情必须统一时段、天气、地面干湿、日照方向与光色；不能因为从室内切到屋外就从白天变黑夜。室内阴暗不等于屋外夜晚。场景资产的 environment、time_of_day、weather 与分镜画面必须一致；不得给连续白天剧情生成黄昏转夜的参考图。真正时间跳跃须在 shot 明确标 temporal_break: true，并指定新的 time_of_day、weather。characters 的音色稳定不等于音量固定偏小，输出对白应清晰可闻。
先判断时空关系：相邻空间可用画外环境声引起人物侧耳、转头或视线变化，镜头顺视线小幅摇移，再切到声源建立镜头；遵守左右方向、180度轴线与人物位置。
需要声先画后（J-cut）时，写明发声来源、画外/画内身份、入点，以及剧本已有的台词原句；不重复完整台词，不为转场擅自增加剧情、人物或对白。
异地、时间跳跃或梦境不能假设人物听见另一时空声音；改用构图/运动方向呼应、环境建立镜头或有叙事理由的声音桥。运镜不跨墙穿模，不把两个地点强行生成在同一镜。
所有安排必须落在各镜既定时长内，不能扩展时长或将前后两镜生成成合集；不要改写既有剧情和人物。
结构化数据中，场景变化的当前 shot 添加 transition 对象：strategy（sound/gaze/match/establish/none），outgoing（上一镜末尾画面动作），incoming（本镜开头画面动作），cue（声音线索，若有对白则注明发声角色与原文）。此对象属于当前镜与上一镜的边界，两个方向必须匹配。
角色 characters 可提供 voice_instruction：根据性别、年龄、体格、身份写出基础音高、共鸣、质地与发声方式；少年、壮年、老人、女性不得共用笼统中音模板。基础音色与单句情绪分开，粗犷壮汉强调厚实胸腔共鸣，不能仅靠降低语速制造厚重。
"""

GENRE_ALIAS_MAP = {
    'xianxia': 'xuanhuan',
    '3d-xiuxian': 'xuanhuan',
    '3d-xuanhuan': 'xuanhuan',
    'apocalypse': 'moshi',
    'rebirth': 'chongsheng',
    'time-travel': 'chuanyue',
    'urban': 'dushi',
    'period': 'niandai',
    'school': 'xiaoyuan',
    'romance': 'tianchong',
    'suspense': 'xuanyi',
    'business': 'shangzhan',
    'family': 'jiating',
    'sci-fi': 'xingji',
    'fantasy': 'xihuan',
    'historical': 'quanmou',
    'wuxia-combat': 'wuxia',
}

def get_skill_dir() -> Path:
    for candidate in [
        BASE_DIR / "SKILL",
        BASE_DIR.parent / "SKILL",
        BASE_DIR.parent / "CDTV" / "SKILL",
    ]:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return BASE_DIR / "SKILL"

def get_custom_rules_dir() -> Path:
    for candidate in [
        BASE_DIR / "custom_rules",
        BASE_DIR.parent / "custom_rules",
        BASE_DIR.parent / "CDTV" / "custom_rules",
    ]:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return BASE_DIR / "custom_rules"

def load_skill_version() -> str:
    skill_dir = get_skill_dir()
    main_skill_md = skill_dir / "short-drama-director" / "SKILL.md"
    if not main_skill_md.exists():
        main_skill_md = skill_dir / "SKILL.md"
    
    if main_skill_md.exists():
        try:
            with open(main_skill_md, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("version:"):
                        return line.split(":", 1)[1].strip().strip('"\'')
        except Exception:
            pass
    return "8.0.0"

def load_custom_continuity_rules() -> str:
    rules_dir = get_custom_rules_dir()
    overlay_file = rules_dir / "continuity_overlay.md"
    if overlay_file.exists():
        try:
            with open(overlay_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""

def load_shot_action_contract() -> str:
    contract = get_custom_rules_dir() / "shot_action_contract.md"
    try:
        return contract.read_text(encoding="utf-8").strip() if contract.is_file() else ""
    except OSError:
        return ""

_CATALOG_CACHE: Optional[List[Dict[str, Any]]] = None

def get_manju_catalog() -> List[Dict[str, Any]]:
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    catalog_path = get_skill_dir() / "manju_genres_catalog.json"
    if catalog_path.exists():
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                _CATALOG_CACHE = json.load(f)
                return _CATALOG_CACHE
        except Exception:
            pass
    return []

def resolve_manju_genre(genre_key_or_name: str) -> Optional[Dict[str, Any]]:
    if not genre_key_or_name:
        return None
    raw = str(genre_key_or_name).strip().lower()
    canonical_key = GENRE_ALIAS_MAP.get(raw, raw)
    catalog = get_manju_catalog()
    for g in catalog:
        if g.get("id") == canonical_key or g.get("name") == genre_key_or_name or g.get("folder") == canonical_key:
            return g
    for g in catalog:
        if raw in g.get("name", "").lower() or raw in g.get("desc", "").lower():
            return g
    return None

def load_genre_skill_markdown(folder_name: str) -> str:
    if not folder_name:
        return ""
    skill_dir = get_skill_dir()
    p = skill_dir / folder_name / "SKILL.md"
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""

def build_genre_directing_rules(genre_info: Dict[str, Any]) -> str:
    if not genre_info:
        return ""
    name = genre_info.get("name", "")
    category = genre_info.get("category", "")
    desc = genre_info.get("desc", "")
    pacing = genre_info.get("pacing", "")
    folder = genre_info.get("folder", "")
    
    skill_md = load_genre_skill_markdown(folder)
    
    pacing_extract = ""
    if skill_md:
        m = re.search(r'本题材的节奏[。：\s]*(.*?)(?=\n\n|\n[#*])', skill_md, re.DOTALL)
        if m:
            pacing_extract = m.group(1).strip()
    
    final_pacing = pacing_extract or pacing
    
    rule = f"""
【{name} · 21大官方AI漫剧全流程导演专属规范】（题材分类：{category}）
1. 题材核心定位：{desc}。
2. 专属节奏律（★关键）：{final_pacing}。
3. 镜头调度原则：
   - 绝不搞千篇一律套路；每镜3~10秒，依据【{name}】独有冲突动态变频；
   - 严禁假大空空镜；文戏特写咬住眼神与微表情，高能冲突快剪连切，大招/爆发定格留足呼吸；
4. 全季资产与人设立项要求：
   - 角色全原创：杜绝同质化姓名（避开网文高频俗套），突出阶梯身份识别度与服装记忆点；
   - 场景与世界观严谨锚定：道具与特效严格契合【{name}】物理与奇幻法则，不跨界串戏。
"""
    return rule.strip()

def build_script_system_prompt(project_type: str = "drama", genre: str = "") -> str:
    version = load_skill_version()
    continuity_rules = load_custom_continuity_rules()
    action_contract = load_shot_action_contract()
    
    if project_type in ("promo", "commercial", "short_video", "documentary"):
        type_desc = {
            "promo": "企业形象宣传片 / 品牌愿景大片（宏大开篇、节奏卡点、视觉冲击、史诗氛围）",
            "commercial": "商业广告 / 产品宣传（黄金3秒抓人、核心卖点特写、痛点解决、号召行动 CTA）",
            "short_video": "爆款短视频 / 创意视觉（高密节拍、强情绪引爆、短平快视觉冲撞）",
            "documentary": "专题纪录片 / 科普专题（纪实质感、深邃旁白、空间纵深、客观厚重）",
        }.get(project_type, "自由视频创作")
        
        system = f"""你是 CDTV 工业级多品类视频编剧与视觉总监（集成漫剧老李 V{version} 视听工业体系与商业视频范式）。
你正在创作【{type_desc}】的分镜头视觉脚本。

分镜核心编排规范：
1. 黄金开篇法则：前 1~2 镜必须具备强视觉钩子（震撼大景或极具张力微距特写），迅速锁定观众注意力；
2. 镜头节奏设计：依据叙事脉络（起承转合 / 痛点-呈现-升华-号召），精准规划景别动势（特写、中景、航拍大景阶梯交替）；
3. 五要素镜行头规范：每个镜头标号后必须严格按【景别 ・ 焦段（如24mm/35mm/50mm/85mm） ・ 机位角度 ・ 运镜（用途标签）】输出；
4. 段时码硬纪律：每段从【00:00-xx:xx】起算，单镜 5~10 秒；
5. 声画合一：旁白/解说词与环境音效、背景音乐卡点节奏精准咬合。

{continuity_rules}
{action_contract}
"""
    elif project_type == "stickman":
        system = f"""你是 CDTV 墨柴工坊 · 火柴人动作剧场导演总编剧（深度融合开源 stickman-video-director 规范体系）。
你正在创作【火柴人动作/沙雕/微动画短剧】的分镜头视觉脚本。

分镜核心编排规范：
1. 黄金3秒视觉钩子：第 1 镜开头（0-3秒）必须安排突发视觉冲撞、高能体术对决或魔性反常识动作，迅速抓取自媒体观众注意力；
2. 动作打击感与速度线语法：
   - 打击顿挫（Hitstop）：受击与出招瞬间加入 0.1s 定格冲击波效果；
   - 速度线与位移：快速奔跑、瞬移飞踢时携带动态速度线（Speed Lines）与大景深冲框；
3. 极简线条美学与一致性约束（Production Lock）：
   - 全局锁定纯色高对比画布（纯白或纯黑），粗黑纯实线条，严禁写实皮肤或复杂3D杂质；
   - 关键道具或能量大招施加局部单色高光点缀（金黄拳芒、冰蓝剑气、红板砖等）；
4. 五要素镜行头规范：每个镜头标号后标注【景别 ・ 焦段 ・ 机位角度 ・ 运镜（动作用途）】；
5. 段时码与自媒体节奏：单镜 5~10 秒，快慢镜头交替，结尾必有神反转或爆笑定格。

{continuity_rules}
{action_contract}
"""
    else:
        # Drama / 漫剧 module
        genre_info = resolve_manju_genre(genre)
        genre_rules = build_genre_directing_rules(genre_info) if genre_info else ""
        genre_title = f"【{genre_info['name']}】" if genre_info else ""

        system = f"""你是 CDTV 电影级短剧/漫剧总编剧与总导演（融合漫剧老李 V{version} 视听工程规范与 21 大官方 AI 漫剧全流程题材模板）。
你正在执导创作{genre_title}的分镜头视听脚本。

{genre_rules}

核心分镜规范：
1. 【五要素镜行规范】：每个分镜开头必须标注：【镜X-X】（景别 ・ 焦段（如35mm/50mm/85mm） ・ 机位角度 ・ 运镜（用途标签））；
2. 【运镜收敛原则（法则 20·★⑦）】：严禁无意义花哨运镜！单段控制在 2~4 镜，以“固定机位+建立镜头+一镜到底”为主，坚决杜绝因频繁运镜引发的 AI 画面形变与穿帮；
3. 【段时码统一归零】：每段分镜时码一律从【00:00】起算（如【00:00-00:10】），严禁跨段累计；
4. 【P4.5 预演故事板空间布局】：多角色同框或场景转换时，镜头必须明确人物站位空间坐标与视线朝向；
5. 【戏剧冲突咬合】：严控台词对白口语化与情绪梯度，每镜配有精准的环境拟音与画外音提示。

{continuity_rules}
{action_contract}
"""
    return (system + '\n' + NARRATIVE_TRANSITION_RULES).strip()

def build_creation_data_system_prompt(project_type: str = "drama", genre: str = "") -> str:
    version = load_skill_version()
    continuity_rules = load_custom_continuity_rules()
    action_contract = load_shot_action_contract()
    
    genre_info = resolve_manju_genre(genre) if project_type == "drama" else None
    genre_rules = build_genre_directing_rules(genre_info) if genre_info else ""
    genre_title = f"【{genre_info['name']}】" if genre_info else ""

    system = f"""你是 CDTV 创作数据编排器（套装版本 V{version}，按下列实际加载的资产、分镜、21大AI漫剧模板和本地导演规则执行）。
请把用户提供的剧本/故事提炼成 CDTV 工业级结构化创作数据 JSON。{genre_title}
必须只输出合法 JSON 对象，不要 Markdown 代码围栏，不要解释，不要在 JSON 后追加任何文字。不要输出 null 或模板占位符。
必须使用这些顶级字段：schema_version（固定为 2.8）、title、style、consistency、shots、p45_board。

{genre_rules}

1. consistency 包含 characters、scenes、props、asset_wirelist 四个数组：
   - characters: 每个元素包含 id（如 char_luming）、name、gender_age（必须明确写出性别与年龄，如“男，62岁”“女，20岁”，供配音自动匹配年龄段音色）、appearance（开头带美术风格关键词，紧凑描写核心发型服装与面部特征识别点，控制在 50~80 字以内）；
   - scenes: 每个元素包含 id（如 scene_mudhouse）、name、environment（开头带美术风格关键词，精炼描写空间几何与光影，控制在 40~60 字以内）；
   - props: 核心道具数组，每个元素包含 id（如 prop_amulet）、name、appearance（材质、外观特征与颜色）；
   - 不创建 audio 音频资产及 aud_vo_、aud_sfx_ 引用；对白逐字写在各镜 dialogue，环境声和动作拟音写在 audio_prompt，角色音色和配音由分镜声音面板管理；
   - asset_wirelist: 严格按 M1（编号占位）模式列出图号映射：如 [{{"slot": "图1", "asset_id": "char_luming", "name": "陆明", "type": "character", "action": "人物锚定"}}]；

2. p45_board（P4.5 预演故事板·叙述体沟通与空间布局卡）：
   - 当出场角色 ≥2 人、或发生场景切换时，必须输出简炼的 P4.5 预演故事板（包含节拍描述、角色左右站位与视线朝向），作为拍摄前的空间对齐依据。

3. shots 数组（极重要门禁，必须 100% 完整覆盖全部镜头，绝严禁为空数组 []）：
   - 【严禁返回空数组/必须 1:1 完整提取全部镜头】：若剧本中已有明确镜头标号（如【镜1-1】...），必须 1:1 完整提取剧本中的全部镜头，严禁输出 "shots": []！若未标注明确镜号，根据情节提炼 12~18 个高精连续分镜，单镜 8~10 秒；
   - 每个 shot 必须包含：
     * id: 镜号（如 shot_01、shot_02...）；
     * title: 镜头标题（包含五要素：景别·焦段·机位角度·运镜）；
     * duration_s: 单镜时长（8~10 秒）；
     * scene_id: 对应的 scene id；
     * references: 引用的 asset id 列表；
     * wirelist: 当前镜头素材接线单（[{{"slot": "图1", "name": "...", "action": "..."}}]）；
     * visual: 精炼画面内容、角色构图与动作（30~50 字）；
     * camera: 专业运镜与焦段（如 50mm 固定机位平拍、85mm 浅景深微推等）；
     * dialogue: 对白或解说词数组；
     * audio_prompt: 当前镜头实际需要的环境声与动作拟音；无对白镜不得补人声；
     * video_prompt: 七段式生视频提示词。
     * action_chain: 对需要完整动作的镜头，包含 start（第0秒动作前或起势的位置和持物）、required_actions（按顺序且可看见的动词短句数组）、end（镜尾的可见状态）、persistent_facts（整镜持续的剧情事实数组）。没有跨门、拿放、交接等关键动作时可省略；不得把动作完成后的画面当起始图。

{continuity_rules}
{action_contract}
"""
    return (system + '\n' + NARRATIVE_TRANSITION_RULES).strip()
