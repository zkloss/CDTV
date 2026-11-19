"""Atomic local chapter import. No model calls, no assets/videos generated."""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import unquote

def digest(value):
    raw=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(raw.encode('utf8')).hexdigest()

def fail(message,status=400):
    from local_storage import StorageError
    raise StorageError(status,message)

def validate_document(document):
    if not isinstance(document,dict) or document.get('parserVersion')!=1:fail('文档解析版本不支持，请重新选择文件')
    raw=document.get('rawText')
    if not isinstance(raw,str) or not raw.strip() or '\0' in raw or len(raw.encode('utf8'))>2*1024*1024:fail('原文无效或超过2MB')
    if document.get('errors'):fail('文档仍有未处理的解析错误')
    episodes=document.get('episodes')
    if not isinstance(episodes,list) or not 1<=len(episodes)<=100:fail('文档没有可导入的分集')
    keys=set();total=0
    for ep in episodes:
        if not isinstance(ep,dict) or not re.fullmatch(r'episode-\d+',str(ep.get('key',''))) or ep['key'] in keys:fail('分集编号缺失或重复')
        keys.add(ep['key']);script=ep.get('script');shots=ep.get('shots')
        if not isinstance(script,str) or not script.strip() or not isinstance(shots,list) or not shots:fail('分集缺少可拍摄正文')
        if any(not isinstance(s,dict) for s in shots):fail('分镜格式无效')
        headers=re.findall(r'^【镜([\d-]+)】',script,re.M)
        if len(headers)!=len(shots) or len(set(headers))!=len(headers):fail('正文分镜数量或编号不完整')
        if headers!=[str(s.get('key','')) for s in shots]:fail('分镜顺序与正文不一致')
        for s in shots:
            if type(s.get('duration')) is not int or not 1<=s['duration']<=600 or not s.get('core'):fail('分镜时长或核心动作缺失')
        total+=len(shots)
    if total>500 or len(json.dumps(document,ensure_ascii=False).encode('utf8'))>8*1024*1024:fail('导入内容过多，请拆分文档')
    return digest(raw)

def episode_number(title):
    from local_storage import parse_chinese_number_py
    match=re.search(r'第\s*([\d一二两三四五六七八九十百]+)\s*集',str(title))
    return parse_chinese_number_py(match[1]) if match else 0

def empty_chapter(chapter,video_projects):
    workflow=chapter.get('workflow') or {}
    return not any(chapter.get(k) for k in ('script','content','sourceText','creationData','chapterDraft')) and not any(workflow.get(k) for k in ('script','novel','creationData','assets','storyboard','scriptImport')) and not any(str(v.get('chapterId') or v.get('sourceChapterId') or '')==str(chapter['id']) for v in video_projects)

def build_plan(project,chapters,videos,document,selected,reuse):
    file_hash=validate_document(document)
    if not isinstance(selected,list) or not selected or any(not isinstance(k,str) for k in selected) or len(set(selected))!=len(selected):fail('请选择不重复的分集')
    by_key={e['key']:e for e in document['episodes']}
    if any(k not in by_key for k in selected):fail('所选分集不属于这份文档')
    document_id='scriptdoc_'+digest(project['id']+'\0'+file_hash)[:40]
    existing={c.get('workflow',{}).get('scriptImport',{}).get('episodeKey'):c for c in chapters if c.get('workflow',{}).get('scriptImport',{}).get('documentId')==document_id}
    chosen=[e for e in document['episodes'] if e['key'] in selected]
    maximum=max([episode_number(c.get('title')) for c in chapters]+[0])
    target=next((c for c in chapters if c['id']==reuse),None)
    can_reuse=bool(target and episode_number(target.get('title'))==maximum and empty_chapter(target,videos) and not (project.get('workflow') or {}).get('creationData') and not project.get('creationData'))
    next_number=maximum if can_reuse else maximum+1
    plan=[];pending=0
    for e in chosen:
        old=existing.get(e['key'])
        if old:plan.append({'episodeKey':e['key'],'sourceTitle':e['title'],'targetTitle':old['title'],'chapterId':old['id'],'action':'duplicate','shotCount':len(e['shots'])});continue
        reuse_this=can_reuse and pending==0
        cid=target['id'] if reuse_this else 'scriptchapter_'+digest(project['id']+'\0'+file_hash+'\0'+e['key'])[:40]
        plan.append({'episodeKey':e['key'],'sourceTitle':e['title'],'targetTitle':f'第{next_number}集','chapterId':cid,'action':'fill_empty' if reuse_this else 'create','shotCount':len(e['shots'])})
        pending+=1;next_number+=1
    state={'project':[project['id'],project.get('revision')],'chapters':sorted((c['id'],c.get('revision')) for c in chapters),'videos':sorted((v['id'],v.get('revision')) for v in videos),'document':digest(document),'selected':selected,'reuse':reuse}
    return {'documentId':document_id,'fileHash':file_hash,'plan':plan,'previewToken':digest(state),'newCount':pending,'duplicateCount':len(plan)-pending}

def operate(storage,project_id,body,commit=False):
    document=body.get('document');selected=body.get('selectedEpisodes');reuse=str(body.get('reuseChapterId') or '')
    validate_document(document)
    # The same connection validates and writes the whole selection. A failure
    # rolls back every chapter; another request cannot overwrite a blank draft.
    with storage._lock,storage._connection() as connection:
        if commit:connection.execute('BEGIN IMMEDIATE')
        def rows(namespace):
            return [dict(json.loads(r['data_json']),id=r['object_id'],revision=r['revision']) for r in connection.execute('SELECT object_id,revision,data_json FROM storage_document WHERE namespace=?',(namespace,))]
        project=next((p for p in rows('projects') if p['id']==project_id),None)
        if not project:fail('项目已不存在，请返回项目列表',404)
        if project.get('workspace')=='general':fail('请在短剧项目中使用分镜文档导入')
        chapters=[c for c in rows('chapters') if str(c.get('projectId'))==project_id]
        chapter_ids={c['id'] for c in chapters}
        videos=[v for v in rows('video_projects') if str(v.get('projectId'))==project_id or str(v.get('chapterId') or v.get('sourceChapterId') or '') in chapter_ids]
        result=build_plan(project,chapters,videos,document,selected,reuse)
        if not commit:return result
        if result['newCount'] and body.get('previewToken')!=result['previewToken']:fail('项目或文档已变化，请刷新导入预览后再确认；本次未写入',409)
        timestamp=datetime.now(timezone.utc).isoformat()
        def write(namespace,cid,value,revision=1):
            payload=json.dumps(value,ensure_ascii=False,separators=(',',':'))
            if revision==1:connection.execute('INSERT INTO storage_document(namespace,object_id,revision,updated_at,content_hash,data_json) VALUES(?,?,?,?,?,?)',(namespace,cid,revision,timestamp,digest(payload),payload))
            else:connection.execute('UPDATE storage_document SET revision=?,updated_at=?,content_hash=?,data_json=? WHERE namespace=? AND object_id=?',(revision,timestamp,digest(payload),payload,namespace,cid))
        changed=[]
        pending=[p for p in result['plan'] if p['action']!='duplicate']
        if pending:
            if not any(d['id']==result['documentId'] for d in rows('script_documents')):
                write('script_documents',result['documentId'],{'id':result['documentId'],'projectId':project_id,'fileHash':result['fileHash'],'document':document,'createTime':timestamp})
            for item in pending:
                ep=next(e for e in document['episodes'] if e['key']==item['episodeKey'])
                old=next((c for c in chapters if c['id']==item['chapterId']),{})
                info={'documentId':result['documentId'],'episodeKey':ep['key'],'sourceTitle':ep['title'],'fileHash':result['fileHash'],'parserVersion':1,'shotCount':len(ep['shots']),'duration':ep.get('duration'),'originalScript':ep['script'],'rules':document.get('rules',[]),'models':document.get('models',[])}
                chapter={**old,'id':item['chapterId'],'projectId':project_id,'title':item['targetTitle'],'content':f"{ep['title']}；{len(ep['shots'])}段，原文与包装资料见导入资料。",'script':ep['script'],'createTime':old.get('createTime',timestamp),'updateTime':timestamp,'workflow':{**old.get('workflow',{}),'script':ep['script'],'workflowStage':'script','scriptImport':info}}
                revision=int(old.get('revision',0))+1;chapter.pop('revision',None)
                write('chapters',chapter['id'],chapter,revision);changed.append(dict(chapter,revision=revision))
        all_chapters=rows('chapters');all_chapters=[c for c in all_chapters if str(c.get('projectId'))==project_id]
        return {**result,'projectId':project_id,'chapters':all_chapters,'importedChapterIds':[c['id'] for c in changed],'firstChapterId':(changed or [next(c for c in all_chapters if c['id']==result['plan'][0]['chapterId'])])[0]['id']}

def install(handler_class):
    if getattr(handler_class,'_script_document_import_installed',False):return
    previous=handler_class._route
    def route(self,method,path,query):
        if path in ('/api/script-document/ai-adapt', '/script-document/ai-adapt') and method == 'POST':
            b = self._read_json()
            source_text = str(b.get('sourceText') or b.get('text') or '').strip()
            title = str(b.get('title') or '未命名剧集').strip()
            model_id = str(b.get('model') or b.get('modelId') or '').strip()
            custom_req = str(b.get('requirements') or '').strip()
            if not source_text:
                fail('请先提供要改编的文档文本', 400)
            
            prompt_req = f"""你是一位资深的工业级电影/短剧执行导演与视觉编剧。
请将提供的原始小说、故事草稿或文本内容，改编并规范化输出为直接可用于视频分镜制作的标准 CDTV 剧本。
输出必须严格遵循以下 Markdown 分镜格式规范：

# 第1集：{title}

### 镜头 01：[景别]·[镜头动作/构图]
【时长】: 5秒
【场景】: [地点·环境·时间·光影氛围]
【画面】: [高清晰度视觉画面描述，明确主体人物特征、服装、动作行为、景别构图、摄影机机位与光线]
【台词】: [角色名]：“纯净台词对白”（如为旁白写【旁白】：“...”，无对白写【台词】: 无）

### 镜头 02：...

核心要求：
1. 节奏紧凑，画面感强，每个镜头必须有明确具体的视觉动作与环境构图，禁止大段抽象空泛抒情。
2. 角色对白提炼纯净，严禁台词中夹杂动作括号。
3. 请尽可能保持原著核心剧情与台词原意，转化为便于 AI 视频生成的视觉镜头语言。
4. 直接输出 Markdown 剧本正文，不要有任何多余的开场白或解释。
{custom_req}"""
            
            ai_body = {
                "title": title,
                "sourceText": source_text,
                "requirements": prompt_req,
                "model": model_id or None,
            }
            try:
                gen_res = self._generate_script(self.storage, ai_body)
                script_out = str(gen_res.get("script") or "")
                used_model = str(gen_res.get("model") or "")
                self._ok({
                    "adaptedText": script_out,
                    "model": used_model,
                    "title": title,
                })
                return
            except Exception as e:
                fail(f"AI 文本模型精编失败：{str(e)}", 500)

        if path in ('/api/script-document/convert-file', '/script-document/convert-file') and method == 'POST':
            b = self._read_json()
            file_name = str(b.get('fileName') or 'document.txt')
            content_b64 = str(b.get('contentBase64') or '')
            raw_text = str(b.get('text') or '')
            import base64
            from document_format_adapter import extract_text_from_file_bytes, smart_adapt_script_to_cdtv_format
            if content_b64:
                file_bytes = base64.b64decode(content_b64)
                extracted_text = extract_text_from_file_bytes(file_name, file_bytes)
            else:
                extracted_text = raw_text
            adapted_text = smart_adapt_script_to_cdtv_format(extracted_text, file_name)
            self._ok({
                'fileName': file_name,
                'extractedText': extracted_text,
                'adaptedText': adapted_text,
            })
            return
        match=re.fullmatch(r'/project/([^/]+)/script-document/(preview|import|convert-file|ai-adapt|scriptdoc_[a-f0-9]+)',path)
        if not match:return previous(self,method,path,query)
        pid,action=unquote(match[1]),match[2]
        if action == 'ai-adapt' and method == 'POST':
            b = self._read_json()
            source_text = str(b.get('sourceText') or b.get('text') or '').strip()
            title = str(b.get('title') or '未命名剧集').strip()
            model_id = str(b.get('model') or b.get('modelId') or '').strip()
            custom_req = str(b.get('requirements') or '').strip()
            if not source_text:
                fail('请先提供要改编的文档文本', 400)
            
            prompt_req = f"""你是一位资深的工业级电影/短剧执行导演与视觉编剧。
请将提供的原始小说、故事草稿或文本内容，改编并规范化输出为直接可用于视频分镜制作的标准 CDTV 剧本。
输出必须严格遵循以下 Markdown 分镜格式规范：

# 第1集：{title}

### 镜头 01：[景别]·[镜头动作/构图]
【时长】: 5秒
【场景】: [地点·环境·时间·光影氛围]
【画面】: [高清晰度视觉画面描述，明确主体人物特征、服装、动作行为、景别构图、摄影机机位与光线]
【台词】: [角色名]：“纯净台词对白”（如为旁白写【旁白】：“...”，无对白写【台词】: 无）

### 镜头 02：...

核心要求：
1. 节奏紧凑，画面感强，每个镜头必须有明确具体的视觉动作与环境构图，禁止大段抽象空泛抒情。
2. 角色对白提炼纯净，严禁台词中夹杂动作括号。
3. 请尽可能保持原著核心剧情与台词原意，转化为便于 AI 视频生成的视觉镜头语言。
4. 直接输出 Markdown 剧本正文，不要有任何多余的开场白或解释。
{custom_req}"""
            
            ai_body = {
                "title": title,
                "sourceText": source_text,
                "requirements": prompt_req,
                "model": model_id or None,
            }
            try:
                gen_res = self._generate_script(self.storage, ai_body)
                script_out = str(gen_res.get("script") or "")
                used_model = str(gen_res.get("model") or "")
                self._ok({
                    "adaptedText": script_out,
                    "model": used_model,
                    "title": title,
                })
                return
            except Exception as e:
                fail(f"AI 文本模型精编失败：{str(e)}", 500)
        if action == 'convert-file' and method == 'POST':
            b = self._read_json()
            file_name = str(b.get('fileName') or 'document.txt')
            content_b64 = str(b.get('contentBase64') or '')
            raw_text = str(b.get('text') or '')
            import base64
            from document_format_adapter import extract_text_from_file_bytes, smart_adapt_script_to_cdtv_format
            if content_b64:
                file_bytes = base64.b64decode(content_b64)
                extracted_text = extract_text_from_file_bytes(file_name, file_bytes)
            else:
                extracted_text = raw_text
            adapted_text = smart_adapt_script_to_cdtv_format(extracted_text, file_name)
            self._ok({
                'fileName': file_name,
                'extractedText': extracted_text,
                'adaptedText': adapted_text,
            })
            return
        if action in ('preview','import') and method=='POST':
            self._ok(operate(self.storage,pid,self._read_json(),action=='import'));return
        if method=='GET' and action.startswith('scriptdoc_'):
            self.storage.get_document('projects',pid);record=self.storage.get_document('script_documents',action)
            if record.get('projectId')!=pid:fail('资料不属于当前项目',404)
            self._ok(record);return
        fail('文档导入操作不支持',405)
    handler_class._route=route;handler_class._script_document_import_installed=True
