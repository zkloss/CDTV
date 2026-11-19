"""Bounded, data-only Remotion rendering for the general-video workspace.

No model-generated source, shell commands or old-project mutations.
Explicit automatic narration uses the user's selected existing TTS provider.
Each render snapshots its plan and local media and publishes a new file/version.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid
import wave

_gate = threading.Lock()
_processes = {}
KINDS = {'title', 'statement', 'steps', 'comparison', 'image', 'diagram', 'outro'}
ILLUSTRATIONS = {'', 'leaf', 'chloroplast', 'energy', 'cycle', 'flow'}
SIZES = {'16:9': (1920,1080), '9:16': (1080,1920), '1:1': (1080,1080), '4:3': (1440,1080), '3:4': (1080,1440), '21:9': (1920,824)}

def runtime_root():
    here = Path(__file__).resolve().parent
    for base in (here, here.parent):
        candidate = base/'motion_runtime'
        if (candidate/'render.mjs').is_file(): return candidate
    raise ValueError('整片渲染组件尚未同步，请重启更新后的程序')

def node_binary():
    root = runtime_root()
    candidates = [root/'node.exe']
    found = shutil.which('node')
    if found: candidates.append(Path(found))
    for p in candidates:
        if p.is_file(): return str(p)
    raise ValueError('未找到本机 Node.js，请在模型配置外安装整片运行环境后重试')

def browser_binary():
    root = runtime_root()
    for p in [root.parent/'runtime/chrome-win64/chrome.exe', root.parent/'_internal/runtime/chrome-win64/chrome.exe', Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'), Path('C:/Program Files/Google/Chrome/Application/chrome.exe')]:
        if p.is_file(): return str(p)
    raise ValueError('未找到本机浏览器渲染环境')

def storage_of(api):
    server = getattr(api, '_local_storage_server', None)
    if server is None: raise ValueError('本地存储服务未就绪')
    return server.storage

def number(value, default):
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (ValueError,TypeError): return default

def text(value, limit=240): return str(value or '').strip()[:limit]

def model_label(storage, ident):
    return next((text(m.get('name') or m.get('modelName'),100) for m in storage.list_documents('ai_models') if str(m.get('id'))==str(ident)),text(ident,100))

def narration_text(scene):
    if 'narration' in scene:
        value=str(scene.get('narration') or '').strip()
        if len(value)>500:raise ValueError('单段旁白超过500字，请分成更多段落；不会截断原文')
        return value
    parts=[scene.get('title'),scene.get('subtitle'),*(scene.get('items') or [])]
    value='。'.join(dict.fromkeys(str(x).strip(' 。') for x in parts if str(x or '').strip()))
    if len(value)>500:raise ValueError('旧方案单段文字过长，请更新整片方案并填写简洁旁白')
    return value

def validate_plan(raw, ratio='16:9', duration=None):
    if not isinstance(raw,dict): raise ValueError('整片方案格式不正确')
    scenes = raw.get('scenes')
    if not isinstance(scenes,list) or not 1 <= len(scenes) <= 60: raise ValueError('整片需要1到60个内容段落')
    fps=30; parsed=[]
    for i,s in enumerate(scenes):
        if not isinstance(s,dict): raise ValueError('内容段落格式不正确')
        kind=text(s.get('kind'),30)
        if kind not in KINDS: raise ValueError(f'第{i+1}段使用了不支持的版式')
        title=text(s.get('title'),64)
        if not title: raise ValueError(f'第{i+1}段缺少标题')
        items=s.get('items') or []
        if not isinstance(items,list) or len(items)>6: raise ValueError(f'第{i+1}段最多6条内容')
        parsed.append({'kind':kind,'title':title,'subtitle':text(s.get('subtitle'),180),'items':[text(x,96) for x in items],
          'caption':text(s.get('caption'),180),'assetId':text(s.get('assetId'),100),'seconds':max(1, min(40,number(s.get('seconds'),4))),
          'recipe':text(s.get('recipe'),100),'narration':narration_text(s),
          'illustration':s.get('illustration') if s.get('illustration') in ILLUSTRATIONS else ''})
        if s.get('imageRequired') is True: parsed[-1]['imageRequired']=True
        if s.get('templateSlot') in {'morning','card1','table','macro','card2','chart','cardWbr','wbr','card3','outro'}:
            parsed[-1]['templateSlot']=s['templateSlot']
            parsed[-1]['details']=[text(v,180) for v in (s.get('details') or [])[:120]]
    total=number(duration,number(raw.get('duration'),sum(s['seconds'] for s in parsed)))
    if not 5<=total<=180: raise ValueError('整片时长请设为5到180秒')
    total_frames=round(total*fps)
    weights=[s['seconds'] for s in parsed]; weight_sum=sum(weights)
    boundaries=[0]+[round(sum(weights[:i])*total_frames/weight_sum) for i in range(1,len(parsed))]+[total_frames]
    if any(boundaries[i+1]-boundaries[i]<24 for i in range(len(parsed))): raise ValueError('内容过多，部分段落不足0.8秒，请延长时长或减少段落')
    for i,s in enumerate(parsed):
        s['from']=boundaries[i];s['frames']=boundaries[i+1]-boundaries[i];s['seconds']=s['frames']/fps
    width,height=SIZES.get(ratio,SIZES['16:9'])
    colors=raw.get('colors') if isinstance(raw.get('colors'),dict) else {}
    colors={k:v for k,v in colors.items() if k in {'paper','ink','accent','muted'} and isinstance(v,str) and re.fullmatch('#[a-fA-F0-9]{6}',v)}
    result={'title':text(raw.get('title'),100),'fps':fps,'width':width,'height':height,'duration':total_frames/fps,'durationInFrames':total_frames,'ratio':ratio,'scenes':parsed,'colors':colors,
            'rendererVersion':2,'theme':raw.get('theme') if raw.get('theme') in {'botanical','editorial','technology','paper'} else 'editorial',
            'plannerModel':text(raw.get('plannerModel'),200),'plannerModelName':text(raw.get('plannerModelName'),100)}
    if raw.get('templateId')=='ink-press':
        result['templateId']='ink-press'
        if isinstance(raw.get('templateSourceScenes'),list):result['templateSourceScenes']=validate_plan({'scenes':raw['templateSourceScenes'],'duration':max(60,total)},ratio)['scenes']
    if isinstance(raw.get('imageWarnings'),list):result['imageWarnings']=[text(v,240) for v in raw['imageWarnings'][:60]]
    return result

def project_context(api, body):
    storage=storage_of(api); pid=text(body.get('projectId'),100); cid=text(body.get('chapterId'),100)
    project=storage.get_document('projects',pid)
    if project.get('workspace')!='general' and project.get('type') not in {'commercial','promo','science','lifestyle','documentary','short_video'}: raise ValueError('整片动效只用于通用视频')
    chapter=storage.get_document('chapters',cid)
    if str(chapter.get('projectId'))!=pid: raise ValueError('制作方案不属于当前作品')
    return storage,project,chapter

def assets_for(storage,project,chapter):
    vid=(chapter.get('workflow') or {}).get('videoProjectId')
    videos=storage.list_documents('video_projects')
    target=next((v for v in videos if str(v.get('id'))==str(vid) and str(v.get('projectId'))==str(project['id'])),None)
    if not target: target=next((v for v in videos if str(v.get('projectId'))==str(project['id']) and f"章节 ID {chapter['id']}" in v.get('description','')),None)
    assets=(target or {}).get('assets') or []
    return [a for a in assets if isinstance(a,dict) and a.get('id')]


def ready_image_assets(storage, assets):
    """Only actual image files in this chapter may be offered to the planner."""
    ready={}
    for asset in assets:
        fid=asset.get('fileId') or asset.get('coverId')
        if not fid: continue
        try:
            meta=storage.find_file(str(fid))
            path=storage.file_directory(meta['bucket'],str(fid))/'content.bin'
            if not str(meta.get('contentType','')).startswith('image/') or not path.is_file() or not path.stat().st_size:continue
        except (ValueError,KeyError,OSError):continue
        # StorageError is not a ValueError in older frozen storage versions.
        except Exception as exc:
            from local_storage import StorageError
            if isinstance(exc,StorageError):continue
            raise
        ready[str(asset['id'])]=asset
    return ready


def resolve_plan_images(plan, storage, assets, template_id=''):
    """Normalize optional planner references, preserving required real imagery.

    An explicit supported illustration is already renderable. A missing logo,
    screenshot or photo without such an illustration remains a blocking error.
    This never generates images, guesses another project's asset or drops text.
    """
    plan=copy.deepcopy(plan);ready=ready_image_assets(storage,assets)
    catalog={str(a['id']):a for a in assets};aliases={}
    for ident,asset in ready.items():
        for value in [asset.get('name'),asset.get('fileId'),asset.get('coverId')]:
            if value:aliases.setdefault(str(value),set()).add(ident)
    botanical=bool(template_id and re.search('光合作用|叶绿|植物|类囊体',json.dumps(plan['scenes'],ensure_ascii=False))) or plan.get('theme')=='botanical'
    notices=[]
    for index,scene in enumerate(plan['scenes'],1):
        reference=scene['assetId'];original=reference
        if reference.casefold() in {'none','null','undefined','n/a','-'}:reference=''
        if reference not in ready and len(aliases.get(reference,set()))==1:reference=next(iter(aliases[reference]))
        if reference in ready:
            scene['assetId']=reference
            continue
        illustration=scene.get('illustration')
        drawable=bool((illustration in {'leaf','chloroplast','energy','cycle'} and botanical) or (illustration=='flow' and scene['items']))
        must_image=scene.get('imageRequired') is True or (scene['kind']=='image' and not drawable)
        label=text((catalog.get(original) or {}).get('name') or original or '所需图片',70)
        if must_image:
            raise ValueError(f'第{index}段「{scene["title"]}」需要真实图片「{label}」，但图片未就绪；请在素材与生图中生成或上传该图。原片已保留')
        if scene['kind']=='image':
            scene['kind']='diagram'
            notices.append(f'第{index}段「{scene["title"]}」使用内置原理示意，无需外部图片；不会替代成真实照片')
        elif original and original.casefold() not in {'none','null','undefined','n/a','-'}:
            notices.append(f'第{index}段「{scene["title"]}」的可选图片「{label}」未就绪，继续使用本段文字与图解')
        scene['assetId']=''
    plan['imageWarnings']=list(dict.fromkeys([*plan.get('imageWarnings',[]),*notices]))[:60]
    return plan

def prepare(api,body):
    storage,project,chapter=project_context(api,body)
    script=str(body.get('script') or chapter.get('script') or '')
    if not script.strip(): raise ValueError('请先填写或生成单片脚本')
    model=text(body.get('model'),200)
    if not model: raise ValueError('请先选择用于整理整片内容的文本模型')
    brief=body.get('brief') if isinstance(body.get('brief'),dict) else project.get('productionBrief') or {}
    from inkpress_template import selected_template,bind
    template_id=selected_template(brief)
    assets=assets_for(storage,project,chapter)
    ready_images=ready_image_assets(storage,assets)
    system='''你是整片动效排版导演，将用户已有脚本转成安全的JSON整片时间轴，输出单个JSON，不输出代码。
这是用文字、图形和本地图片统一渲染的完整视频，不是逐镜请求视频模型。只写观众应该看到的内容，不把运镜代码、帧号、音效提示或实施说明当作字幕。
必须忠实原脚本文案和事实，不复制技能模板的品牌或标语、不擅自加入购买号召。没有图片可用时，用清晰的文字/图解表达，不声称已经展示真实产品截图或人物表演。
schema: {title,theme, scenes:[{kind,title,subtitle,items,caption,assetId,seconds,recipe,narration,illustration}]}。
kind只能为title/statement/steps/comparison/image/diagram/outro。title最多30个汉字，subtitle最多80个汉字，items为最多6条短句的数组，caption为可选原脚本字幕。
steps按步骤展示，comparison使用两列items，diagram使用3到6个简洁标签，image必须使用提供的assetId且图片已生成。title/outro使用标题卡。
每段只表达一个信息，段落时长按阅读需要分配。保留脚本已有逻辑次序、准确标题及公式原文。超出表达能力的要求写在结果warnings数组，不得假称实现。
recipe只能记录源脚本提及的卡名，不意味着完整重现该卡；当前版式是标题、步骤、对比、图解及图片动效。
必须为每个需要解说的段落写narration：只含自然口语的旁白，不朗读镜号、实现指令或排版参数。按简报时长每秒约3.5个汉字控制整片旁白总量，突出核心内容，不把长脚本全部塞进短片。开场不超过约2秒，结尾不超过约3秒；每段最多3条短要点，避免长列表一闪而过。可见标题只出现一次，subtitle和items不要重复标题。
theme可选botanical（植物/生命科普）、editorial（清晰彩色图解）、technology（深色科技）、paper（纸墨字卡）。科普优先图解配简短文字，不要整片都是字卡。
illustration可选leaf（叶片与阳光）、chloroplast（叶绿体结构）、energy（能量转换）、cycle（循环）、flow（流程）或空。这些是原理示意，不是显微照片；不能用叶绿体插图冒充真实显微结构。植物科普用合适的示意支撑关键解释；其他主题不要强加植物。caption为短字幕，不堆砌所有解说。'''
    system+='\n图片契约：assetId只准使用availableImages中的id，不使用脚本里的待生成素材名、概念名或模板贴图路径。无需外部图片时assetId写空字符串。使用leaf/chloroplast/energy/cycle/flow内置示意时kind写diagram，不写image。kind=image只用于已有真实图片。用户明确必须展示的实物照片、Logo或截图设置imageRequired=true；不得用示意图冒充。'
    if template_id:
        system=system.replace('recipe只能记录源脚本提及的卡名，不意味着完整重现该卡；当前版式是标题、步骤、对比、图解及图片动效。','recipe按下面所选完整模板的固定槽位填写；这条路径实际使用模板组件。').replace('开场不超过约2秒，结尾不超过约3秒；','开场、转场与结尾遵循完整模板原有时长，不强压为通用图解节奏；')
        from shotcraft_bridge import skill_root
        system+='\n用户明确选择了Ink Press整片模板，必须按原始10镜头顺序安排内容。输出10段，对应开场聚光、字卡1、卡片发牌筛选、详情行嵌入、字卡2、列表堆叠、字卡3、文档揭示、字卡4、合影收尾。实际渲染调用原场景组件，不准改成普通列表来冒充。只改文案和素材，不复制模板演示品牌、研究项目名或截图。原模板最低1085帧，时长不足会明确按模板延长。\n'+(skill_root()/'template/TEMPLATE.md').read_text('utf8')
    user={'name':project.get('name'),'brief':brief,'script':script,'availableImages':[{'id':a['id'],'name':a.get('name')} for a in ready_images.values()]}
    result=api.backend_request('POST','/ai/chat','',{'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(user,ensure_ascii=False)}],'temperature':0.2,'max_tokens':12000})
    from local_storage import _Handler
    output=re.sub(r'<think>[\s\S]*?</think>','',_Handler._chat_result_text(result),flags=re.I).strip()
    try: raw,_=json.JSONDecoder().raw_decode(output[output.index('{'):])
    except (ValueError,TypeError): raise ValueError('文本模型未返回完整整片方案，原内容未替换')
    plan=validate_plan(raw,project.get('ratio','16:9'),brief.get('duration',30))
    plan.update(plannerModel=model,plannerModelName=model_label(storage,model))
    plan=resolve_plan_images(plan,storage,assets,template_id)
    if template_id:plan=bind(plan)
    return {'plan':plan,'warnings':[*[text(x,200) for x in (raw.get('warnings') or [])[:8]],*plan.get('imageWarnings',[])],'scriptSha256':hashlib.sha256(script.encode()).hexdigest()}

def jobs(api,body):
    storage,project,chapter=project_context(api,body)
    records=[j for j in storage.list_documents('motion_renders') if j.get('projectId')==project['id'] and j.get('chapterId')==chapter['id']]
    for j in records:
        if j.get('status') in {'queued','rendering'} and j['id'] not in _processes:
            # Persist interrupted status once after restart. Never resubmit a job.
            j=storage.update_document('motion_renders',j['id'],{'status':'interrupted','message':'上次整片制作中断，原成片和方案仍保留；可重新生成新版本'})
    return [storage.get_document('motion_renders',j['id']) for j in records]

def probe_duration(api,path):
    ffmpeg=api._ffmpeg_binary()
    if not ffmpeg: raise ValueError('未找到视频检查组件')
    p=subprocess.run([ffmpeg,'-hide_banner','-i',str(path)],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    match=re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)',p.stderr.decode('utf8',errors='replace'))
    if not match: raise ValueError('无法读取媒体时长')
    return int(match[1])*3600+int(match[2])*60+float(match[3])

def start(api,body,token=''):
    storage,project,chapter=project_context(api,body)
    root=runtime_root();node=node_binary();browser=browser_binary()
    if not (root/'node_modules/@remotion/renderer/package.json').is_file(): raise ValueError('整片渲染依赖未同步')
    plan=validate_plan(body.get('plan'),project.get('ratio','16:9'),None)
    from inkpress_template import selected_template,bind
    template_id=selected_template(body.get('brief') if isinstance(body.get('brief'),dict) else project.get('productionBrief') or {})
    requested_duration=plan['duration']
    assets=assets_for(storage,project,chapter)
    plan=resolve_plan_images(plan,storage,assets,template_id)
    if template_id:plan=bind(plan)
    else:
        plan.pop('templateId',None);plan.pop('templateSourceScenes',None)
    by_id={str(a['id']):a for a in assets}
    needed={s['assetId'] for s in plan['scenes'] if s['assetId']}
    for ident in needed:
        if ident not in by_id or not (by_id[ident].get('fileId') or by_id[ident].get('coverId')): raise ValueError('需要的图片尚未生成或不属于当前作品')
    audio_id=text(body.get('audioFileId'),100)
    # Only a local file selected from the actual storage is accepted. No arbitrary URL or path.
    audio=None
    narration=body.get('narration') if isinstance(body.get('narration'),dict) else {}
    narration={'enabled':narration.get('enabled') is True,'provider':text(narration.get('provider') or 'cloud',30),'model':text(narration.get('model'),200),'voice':text(narration.get('voice'),100),'instruction':text(narration.get('instruction'),500),'autoExtend':narration.get('autoExtend') is True}
    if narration['enabled']:
        if audio_id:raise ValueError('自动旁白与已导入旁白请选择一种，背景音乐可单独添加')
        if narration['provider']=='breeze':
            status=api.breeze_status()
            if not status.get('ready'):raise ValueError('本地 Breeze 尚未就绪，请先启动并等待模型加载；不会自动改用云端收费配音')
            if narration['voice'] and narration['voice'] not in {str(v['id']) for v in status.get('voices',[])}:raise ValueError('所选 Breeze 音色已不存在，请刷新音色列表')
            narration.update(model='breeze-local',modelName='本地 Breeze TTS',projectKey='whole-film:'+str(project['id']),instruction=narration['instruction'] or '普通话清晰自然，温暖沉稳的女声，语速适中，适合知识讲解。')
        elif narration['provider']=='cloud':
            if not narration['model']:raise ValueError('请选择旁白配音模型')
            selected=next((m for m in storage.list_documents('ai_models') if str(m.get('id'))==narration['model'] and m.get('modelType')=='audio' and m.get('enabled') is not False),None)
            if not selected:raise ValueError('所选配音模型不可用，请刷新配置后选择')
            narration['modelName']=model_label(storage,narration['model'])
            if selected.get('provider')=='minimax' or '/voice_design' in str(selected.get('apiUrl','')):raise ValueError('整片旁白需要语音合成模型；音色设计模型请在原音频工具使用')
            if not narration['voice']:
                narration['voice']=text(selected.get('voice'),100)
                if not narration['voice'] and 'cosyvoice' in str(selected.get('modelName','')).lower():narration['voice']='longxiaochun_v2' if 'v2' in str(selected.get('modelName','')).lower() else 'longxiaochun'
        else:raise ValueError('不支持的旁白来源，请选择本地 Breeze 或已配置云端服务')
        if not any(s['narration'] for s in plan['scenes']):raise ValueError('方案没有旁白文本，请先填写或更新整片方案')
    music_id=text(body.get('musicFileId'),100)
    if music_id:
        music_meta=storage.find_file(music_id)
        if not str(music_meta.get('contentType','')).startswith('audio/'):raise ValueError('背景音乐必须是音频文件')
    if audio_id:
        meta=storage.find_file(audio_id)
        if not str(meta.get('contentType','')).startswith(('audio/','video/')): raise ValueError('旁白文件类型不正确')
        audio=storage.file_directory(meta['bucket'],audio_id)/'content.bin'
        if probe_duration(api,audio)>plan['duration']+.05: raise ValueError('旁白长于整片，请先延长整片时长；不会截断旁白')
    with _gate:
        if any(v.get('active') for v in _processes.values()): raise ValueError('已有整片正在渲染，请完成或取消后再开始')
        job=storage.create_document('motion_renders',{'projectId':project['id'],'chapterId':chapter['id'],'title':project.get('name'),
            'status':'queued','message':'正在准备整片','progress':0,'plan':plan,'sound':bool(body.get('sound',True)),'audioFileId':audio_id,
            'narration':narration,'musicFileId':music_id,'plannerModel':plan.get('plannerModel',''),'plannerModelName':plan.get('plannerModelName',''),'rendererVersion':plan.get('rendererVersion',2),
            'templateId':template_id,'templateName':plan.get('templateName',''),'requestedDuration':requested_duration,
            'extendedForTemplate':bool(template_id and plan['duration']>requested_duration),'templateRequestedDuration':requested_duration if template_id else None,
            'scriptSha256':hashlib.sha256(str(body.get('script') or chapter.get('script') or '').encode()).hexdigest()})
        state={'active':True,'cancel':threading.Event(),'process':None};_processes[job['id']]=state
    # Session credentials belong to this in-memory worker only, never the job,
    # plan, cache identity, diagnostics or other persisted documents.
    threading.Thread(target=_render,args=(api,storage,job,by_id,audio,root,node,browser,state,token),daemon=True,name='whole-film-'+job['id'][:8]).start()
    return job

def _render(api,storage,job,by_id,audio,root,node,browser,state,token=''):
    ident=job['id'];folder=storage.root.parent/'motion-renders'/ident;folder.mkdir(parents=True,exist_ok=True)
    def update(**patch): return storage.update_document('motion_renders',ident,patch)
    try:
        plan=copy.deepcopy(job['plan']);public=folder/'public';public.mkdir(exist_ok=True)
        from shotcraft_bridge import skill_root
        upstream=root/'upstream'
        if not upstream.exists(): raise ValueError('整片模板源码未同步')
        for scene in plan['scenes']:
            if scene['assetId']:
                asset=by_id[scene['assetId']];fid=asset.get('fileId') or asset.get('coverId');meta=storage.find_file(fid)
                if not str(meta.get('contentType','')).startswith('image/'): raise ValueError('参考素材不是图片')
                suffix={ 'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}.get(meta['contentType'],'.png')
                name=hashlib.sha256(fid.encode()).hexdigest()[:20]+suffix
                shutil.copy2(storage.file_directory(meta['bucket'],fid)/'content.bin',public/name);scene['src']=name
        if audio:
            shutil.copy2(audio,public/'narration.bin');plan['audio']='narration.bin'
        if job.get('musicFileId'):
            meta=storage.find_file(job['musicFileId']);shutil.copy2(storage.file_directory(meta['bucket'],meta['id'])/'content.bin',public/'music.bin');plan['music']='music.bin'
        if (job.get('narration') or {}).get('enabled'):
            build_narration(api,storage,job,plan,public,state,update,token)
            update(plan=plan,duration=plan['duration'],message='旁白已就绪，正在准备画面')
        if job['sound']:
            audio_source=skill_root()/'template/public/audio'
            if plan.get('templateId')=='ink-press':
                (public/'audio').mkdir(exist_ok=True)
                for source in audio_source.glob('*.mp3'):shutil.copy2(source,public/'audio'/source.name)
            else:
                for name in ['swoosh-quick.mp3','pop.mp3','sparkle.mp3']:shutil.copy2(audio_source/name,public/name)
            plan['sound']=True
        spec=folder/'plan.json';spec.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf8')
        if state['cancel'].is_set(): raise InterruptedError()
        update(status='rendering',message='正在渲染整片画面',progress=1)
        cmd=[node,str(root/'render.mjs'),str(spec),str(folder/'film.mp4'),str(public),browser]
        env={**os.environ,'PATH':str(Path(node).parent)+os.pathsep+os.environ.get('PATH','')}
        p=subprocess.Popen(cmd,cwd=root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        state['process']=p;lines=[];last=0;metadata=None
        for line in p.stdout:
            lines.append(line.rstrip());lines=lines[-120:]
            if state['cancel'].is_set():
                try:p.stdin.write('cancel\n');p.stdin.flush()
                except (OSError,ValueError):pass
            try:
                value=json.loads(line)
                if 'metadata' in value:metadata=value['metadata']
                if value.get('progress') is not None and time.monotonic()-last>1:
                    update(progress=min(98,round(number(value['progress'],0)*97)+1),message=text(value.get('message'),100) or '正在渲染整片');last=time.monotonic()
            except (ValueError,TypeError): pass
        code=p.wait();(folder/'render.log').write_text('\n'.join(lines),encoding='utf8')
        if state['cancel'].is_set(): raise InterruptedError()
        if code or not (folder/'film.mp4').is_file(): raise ValueError('整片渲染失败，详细记录已保留：'+'\n'.join(lines[-8:])[-1600:])
        if not metadata: raise ValueError('缺少整片视频帧检查结果')
        if plan.get('templateId')=='ink-press' and (metadata.get('rendererKind')!='ink-press-native-v1' or metadata.get('templateAssetCount')!=26):raise ValueError('所选Ink Press模板未完整执行，拒绝以通用排版替代')
        ffmpeg=api._ffmpeg_binary()
        counted=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-i',str(folder/'film.mp4'),'-map','0:v:0','-c:v','copy','-an','-progress','pipe:1','-nostats','-f','null','-'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        counts=re.findall(r'frame=(\d+)',counted.stdout.decode('utf8',errors='replace'))
        if counted.returncode or not counts or int(counts[-1])!=plan['durationInFrames'] or abs(number(metadata.get('fps'),0)-30)>.01: raise ValueError('整片视频帧数检查未通过，原渲染结果保留')
        actual=int(counts[-1])/30;metadata['verifiedFrames']=int(counts[-1]);metadata['verifiedVideoSeconds']=actual
        # AAC packet padding may extend the container by a few milliseconds;
        # remux the final audio only, preserving every already rendered frame.
        normalized=folder/'finished.mp4'
        cmd=[ffmpeg,'-y','-hide_banner','-loglevel','error','-i',str(folder/'film.mp4'),'-map','0:v:0','-map','0:a?','-c:v','copy','-c:a','aac','-t',str(plan['duration']),'-movflags','+faststart',str(normalized)]
        result=subprocess.run(cmd,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise ValueError('整片封装失败，原渲染结果保留')
        if state['cancel'].is_set():raise InterruptedError()
        container_duration=probe_duration(api,normalized)
        if abs(container_duration-plan['duration'])>.04:raise ValueError('整片封装时长检查未通过')
        (folder/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf8')
        meta=storage.save_file('motion_renders',normalized.read_bytes(),text(job.get('title'),60)+'.mp4','video/mp4')
        update(status='succeeded',message='整片已生成，含自动旁白，请检查画面与声音' if (job.get('narration') or {}).get('enabled') else '整片已生成，请检查画面与声音',progress=100,fileId=meta['id'],duration=actual,
               url='/file/'+meta['id']+'/download',sha256=meta['sha256'],reviewStatus='needs_review',finishedAt=time.time(),rendererKind=metadata.get('rendererKind'),templateComponents=metadata.get('templateComponents'),templateAssetCount=metadata.get('templateAssetCount'))
    except InterruptedError: update(status='cancelled',message='已取消；旧成片与方案保留')
    except Exception as e: update(status='failed',message=text(e,1800))
    finally: state['active']=False;state['process']=None

def breeze_narration(api,config,spoken,state,token=''):
    """Reuse the existing native voice bridge, including its stable role anchor.

    No cloud fallback and no change to the short-drama voice implementation.
    """
    if state['cancel'].is_set():raise InterruptedError()
    task=api.breeze_generate(token,{'projectKey':config['projectKey'],'contract':{'explicit':True,'lines':[spoken],'roles':['旁白']},'bindings':{'旁白':{'voiceId':config['voice'],'instruction':config['instruction']}}})
    ident=task.get('id')
    if not ident:raise ValueError('本地 Breeze 未返回配音任务')
    deadline=time.monotonic()+1200
    try:
        while time.monotonic()<deadline:
            if state['cancel'].is_set():raise InterruptedError()
            result=api.breeze_job(ident)
            if result.get('status')=='completed':return result.get('result') or {}
            if result.get('status')=='cancelled':raise InterruptedError()
            if result.get('status')=='failed':raise ValueError('本地 Breeze 配音失败：'+text(result.get('message'),500))
            state['cancel'].wait(.25)
        raise ValueError('本地 Breeze 配音等待超时，旧成片保留；不会自动改用云端')
    finally:
        if state['cancel'].is_set() or time.monotonic()>=deadline:api.breeze_cancel(ident)


def build_narration(api,storage,job,plan,public,state,update,token=''):
    config=job['narration'];ffmpeg=api._ffmpeg_binary();minimum=[];files=[];original_frames=plan['durationInFrames']
    for i,scene in enumerate(plan['scenes']):
        if state['cancel'].is_set():raise InterruptedError()
        spoken=scene.get('narration','')
        if not spoken:minimum.append(scene['frames']);continue
        update(status='rendering',message=f'正在生成旁白 {i+1}/{len(plan["scenes"])} · {config["modelName"]}',progress=min(20,1+i))
        identity=[config['model'],config['voice'],spoken]
        if config.get('provider')=='breeze':identity+=['breeze',config['instruction'],config['projectKey']]
        key=hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()
        cached=next((v for v in storage.list_documents('motion_narration_cache') if v.get('key')==key),None)
        if cached:
            fid=cached['fileId']
        else:
            result=breeze_narration(api,config,spoken,state,token) if config.get('provider')=='breeze' else api.backend_request('POST','/ai/audio',token,{'model':config['model'],'prompt':spoken,'text':spoken,'voice':config['voice']})
            fid=text((result or {}).get('fileId'),100)
            if not fid:raise ValueError('配音模型没有返回音频文件，原成片保留')
            storage.create_document('motion_narration_cache',{'key':key,'fileId':fid,'model':config['model'],'voice':config['voice'],'text':spoken,'provider':config.get('provider','cloud'),'instruction':config.get('instruction',''),'projectKey':config.get('projectKey','')})
        if state['cancel'].is_set():raise InterruptedError()
        meta=storage.find_file(fid);source=storage.file_directory(meta['bucket'],fid)/'content.bin';name=f'narration-{i+1:02}.wav';target=public/name
        p=subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-i',str(source),'-vn','-ac','1','-ar','48000','-c:a','pcm_s16le',str(target)],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if p.returncode:raise ValueError('旁白文件不能解码，原成片保留')
        with wave.open(str(target),'rb') as wav:seconds=wav.getnframes()/wav.getframerate()
        if not .08<seconds<180:raise ValueError('旁白音频时长不正确，原成片保留')
        required=math.ceil(seconds*30)+19
        minimum.append(max(scene['frames'],required));files.append({'scene':i,'src':name,'frames':math.ceil(seconds*30),'fileId':fid,'seconds':seconds,'text':spoken})
    total=sum(minimum)
    if total>5400:raise ValueError('完整旁白超过180秒，请减少内容后重试；已生成配音可复用')
    if total>original_frames and not config['autoExtend']:raise ValueError(f'完整旁白需要至少{math.ceil(total/30)}秒，请允许按旁白延长或精简内容；已生成配音可复用，不会截尾')
    cursor=0
    for scene,frames in zip(plan['scenes'],minimum):scene.update(**{'from':cursor,'frames':frames,'seconds':frames/30});cursor+=frames
    plan.update(durationInFrames=cursor,duration=cursor/30,narrationClips=[{**v,'from':plan['scenes'][v['scene']]['from']+4} for v in files])
    update(narrationFiles=files,requestedDuration=job.get('requestedDuration',original_frames/30),extendedForNarration=cursor>original_frames)

def cancel(api,ident):
    storage=storage_of(api);job=storage.get_document('motion_renders',ident)
    state=_processes.get(ident)
    if state and state['active']:
        state['cancel'].set();p=state.get('process')
        if p and p.poll() is None:
            try:p.stdin.write('cancel\n');p.stdin.flush()
            except (OSError,ValueError):pass
    return job

def dispatch(api,method,path,body,token=''):
    if path=='/shotcraft/film/prepare' and method=='POST':return prepare(api,body)
    if path=='/shotcraft/film/start' and method=='POST':return start(api,body,token=token)
    if path=='/shotcraft/film/list' and method=='POST':return jobs(api,body)
    if path.startswith('/shotcraft/film/cancel/') and method=='POST':return cancel(api,path.rsplit('/',1)[1])
    raise ValueError('整片接口不存在')
