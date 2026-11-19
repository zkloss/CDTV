"""Independent bridge candidates; immutable boundaries and a fail-closed assembly gate.

Muse accepts two reference attachments, not native start/end conditioning. A
request never certifies continuity. Numerical checks reject bad boundaries;
passing those checks still requires a review of the entire candidate.
"""
from __future__ import annotations
import hashlib
import math
import subprocess
import tempfile
import uuid
import json
from pathlib import Path
from urllib.parse import unquote

NS = 'assembly_plans'
MAE_LIMIT = .085
MAX_BRIDGE_SECONDS = 4.0
REVIEW_KEYS = ('entry', 'exit', 'identity', 'action', 'sound')
sha = lambda data: hashlib.sha256(data).hexdigest()


def fail(message, status=400):
    from local_storage import StorageError
    raise StorageError(status, message)


def read_video(storage, file_id):
    meta = storage.find_file(str(file_id))
    if not str(meta.get('contentType', '')).startswith('video/'):
        fail('请使用已入库的视频')
    if int(meta.get('size', 0)) > 128 * 1024 * 1024:
        fail('单段视频超过128MB，请先制作较小的副本')
    return storage.read_file_content(meta['bucket'], meta['id'])


def inspect_video(data):
    """Decode every video frame, rather than trusting only container metadata."""
    import cv2
    with tempfile.TemporaryDirectory(prefix='cdtv-bridge-inspect-') as tmp:
        path = Path(tmp) / 'clip.mp4'; path.write_bytes(data)
        capture = cv2.VideoCapture(str(path))
        fps = capture.get(cv2.CAP_PROP_FPS)
        first = last = None; count = 0; still_run = max_still = 0; previous = None
        try:
            while True:
                ok, frame = capture.read()
                if not ok: break
                count += 1
                sample = cv2.resize(frame, (96, 54)).astype('float32') / 255
                if previous is not None:
                    still_run = still_run + 1 if float(abs(sample-previous).mean()) < .0003 else 0
                    max_still = max(max_still, still_run)
                previous = sample
                if first is None: first = frame
                last = frame
        finally: capture.release()
    if first is None or not fps or not math.isfinite(fps) or fps <= 0:
        fail('视频无法完整解码')
    return {'fps': fps, 'frames': count, 'duration': count/fps,
            'width': first.shape[1], 'height': first.shape[0],
            'longestStillSeconds': max_still/fps}, first, last


def image_file(storage, frame, name):
    import cv2
    ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 94])
    if not ok: fail('边界图提取失败')
    return storage.save_file('assembly-frames', encoded.tobytes(), name, 'image/jpeg')['id']


def save(storage, plan):
    return storage.save_document(NS, plan['id'], {k:v for k,v in plan.items() if k != 'revision'},
                                 expected_revision=plan.get('revision', 0))


def load(storage, body):
    plan = storage.get_document(NS, str(body.get('plan_id') or ''))
    if plan.get('projectId') != str(body.get('project_id') or ''):
        fail('组片记录属于其他作品', 409)
    return plan


def verify_sources(storage, plan):
    for source in plan['sources']:
        if sha(read_video(storage, source['fileId'])) != source['sha256']:
            fail('源视频已经变化，请重新准备接点；旧候选继续保留', 409)


def join_for(plan, body):
    join = next((j for j in plan['joins'] if j['id'] == body.get('join_id')), None)
    if join is None: fail('接点不存在')
    return join


def prepare(handler, storage, body):
    sources = body.get('source_videos')
    if not isinstance(sources, list) or not 2 <= len(sources) <= 12:
        fail('请选择2至12段已完成的视频')
    plan = {'id':uuid.uuid4().hex, 'projectId':str(body.get('project_id') or ''),
            'policy':'independent-bridges-v1', 'sources':[], 'joins':[], 'results':[],
            'providerControl':'reference-images-only', 'nativeEndFrameControl':False}
    # Keep the original files and full audio; this first version uses their real
    # head/tail. Changing cut points creates a new plan and requires new review.
    for index, source in enumerate(sources):
        data = read_video(storage, source.get('fileId'))
        info, first, last = inspect_video(data)
        plan['sources'].append({'fileId':str(source['fileId']), 'sha256':sha(data),
            'shotId':str(source.get('shotId') or ''),'description':str(source.get('description') or '')[:14000],
            'title':str(source.get('title') or f'分镜{index+1}'), **info,
            'head':image_file(storage, first, f'{index+1}-head.jpg'),
            'tail':image_file(storage, last, f'{index+1}-tail.jpg')})
    for i in range(len(sources)-1):
        plan['joins'].append({'id':f'join-{i+1}-{i+2}', 'from':i, 'to':i+1,
            'startImage':plan['sources'][i]['tail'], 'endImage':plan['sources'][i+1]['head'],
            'candidates':[], 'selected':None, 'directReview':None})
    from assembly_context import hydrate
    return save(storage, hydrate(storage,plan))


def assess(storage, plan, join, file_id):
    import cv2
    data = read_video(storage, file_id)
    info, first, last = inspect_video(data)
    boundaries = []
    for i, position in ((join['from'], 2), (join['to'], 1)):
        content = read_video(storage, plan['sources'][i]['fileId'])
        boundaries.append(inspect_video(content)[position])
    def mae(a,b):
        a = cv2.resize(a,(160,90)).astype('float32')/255
        b = cv2.resize(b,(160,90)).astype('float32')/255
        return float(abs(a-b).mean())
    scores = {'entry':mae(first,boundaries[0]), 'exit':mae(last,boundaries[1])}
    reasons = []
    if any(sha(data)==s['sha256'] for s in plan['sources']): reasons.append('补段与原分镜文件相同，未得到独立过渡')
    if not .25 <= info['duration'] <= MAX_BRIDGE_SECONDS: reasons.append('补段时长应为0.25至4秒，未自动裁切')
    mode=(join.get('attempt') or {}).get('joinMode','continuous')
    for edge,label in [('entry','接入'),('exit','接出')]:
        if edge=='exit' and mode=='action_cut':continue
        if scores[edge] > MAE_LIMIT: reasons.append(f'{label}画面偏离实际边界')
    if info['longestStillSeconds'] >= .5: reasons.append('补段存在至少0.5秒近乎静止的连续画面，需重做或专项复核')
    candidate = {'id':uuid.uuid4().hex, 'fileId':file_id, 'sha256':sha(data), **info,
        'boundaryMae':scores, 'threshold':MAE_LIMIT, 'technicalPassed':not reasons,
        'reasons':reasons, 'review':None, 'sourceHashes':[s['sha256'] for s in plan['sources']],
        'head':image_file(storage,first,'bridge-head.jpg'), 'tail':image_file(storage,last,'bridge-tail.jpg')}
    candidate.update(joinMode=mode,needsSemanticReview=mode=='action_cut',
        analysisId=(join.get('attempt') or {}).get('actionAnalysisId'),
        boundaryStatus='semantic-review-required' if mode=='action_cut' else 'exact-endpoints')
    join['candidates'].insert(0, candidate)
    join['selected'] = None; join['directReview'] = None
    return candidate


def generate(handler, storage, body, plan, join):
    import native_film
    movement = str(body.get('action_plan') or '').strip()
    requirements = str(body.get('requirements') or '').strip()
    request_id = str(body.get('request_id') or '').strip()
    previous = join.get('attempt')
    from assembly_context import hydrate,join_context,generation_refs
    hydrate(storage,plan)
    # Explicit, revised actions may create another candidate in this same join.
    # Pending/uncertain receipts can only be queried, never retried. The request
    # id makes a repeated client request idempotent after a lost HTTP response.
    if previous:
        if request_id and previous.get('requestId') == request_id:
            return plan
        if previous.get('status') not in ('succeeded','failed','cancelled','canceled'):
            fail('这个接点已经提交过且回执尚未确认，请查询已有任务；不会自动重试或再次扣费',409)
    if (body.get('auto_plan') is True or body.get('use_analysis_id')) and not movement:
        from continuity_planner import analyze,PROMPT_VERSION
        if body.get('use_analysis_id'):
            if (join.get('analysisAttempt') or {}).get('status') in ('running','unknown'):
                fail('动作分析仍在执行或回执尚未确认，请查询当前分析；未调用视频生成',409)
            analysis=join.get('actionAnalysis') or {}
            if analysis.get('id')!=body['use_analysis_id'] or analysis.get('promptVersion')!=PROMPT_VERSION:
                fail('当前动作分析已经更新或仍是旧版，请刷新当前方案；未调用视频生成',409)
            signature=analysis.get('sourceSignature') or {}
            expected=[(s['fileId'],s['sha256']) for s in (plan['sources'][join['from']],plan['sources'][join['to']])]
            latest=(join.get('candidates') or [None])[0]
            failed=latest if latest and not latest.get('technicalPassed') else None
            if [tuple(s) for s in signature.get('sources',[])]!=expected or signature.get('failedCandidate')!=(failed.get('sha256') if failed else None):
                fail('源素材或失败补段已经变化，请重新识别衔接动作；未调用视频生成',409)
            if signature.get('context')!=plan.get('contextSignature'):fail('原分镜资料已经更新，请重新分析；未调用视频生成',409)
        else:
            plan=analyze(handler,storage,body,plan,join)
            join=join_for(plan,body)
        analysis=join['actionAnalysis']
        if analysis.get('edit_strategy',{}).get('type','bridge')!='bridge':fail('当前方案应剪接、调整切点或修复源镜头，不能强行生成补段；未调用视频生成',409)
        accepted_medium = analysis['confidence']=='medium' and body.get('accept_analysis_id')==analysis['id']
        if analysis['decision']!='bridge' or analysis.get('executionReady') is not True or (analysis['confidence']!='high' and not accepted_medium):
            fail('AI已给出分析，但建议直接切镜或仍有不确定项，未调用视频生成；请查看本接点建议',409)
        movement=analysis['bridge_prompt']
    if previous:
        if not movement:
            fail('请先填写这次修改的具体动作，再重做这个接点；原候选保留',409)
        if ' '.join(movement.split()) == ' '.join(str(previous.get('actionPlan') or '').split()):
            fail('动作方案没有修改，不会原样重复生成；请根据失败接点调整动作',409)
    model = handler._video_model(storage, body.get('model'))
    if not str(model.get('modelName','')).startswith('muse-video'): fail('当前独立补段仅接入Muse参考图模式')
    if previous:
        join.setdefault('attempts',[]).append(previous)
    join['attempt'] = {'status':'submitting','model':model['id'], 'requestId':request_id,
                       'joinMode':(join.get('actionAnalysis') or {}).get('edit_strategy',{}).get('join_mode','continuous') if body.get('use_analysis_id') or body.get('auto_plan') else 'continuous',
                       'actionPlan':movement, 'requirements':requirements,
                       'actionAnalysisId':(join.get('actionAnalysis') or {}).get('id') if body.get('auto_plan') or body.get('use_analysis_id') else None}
    join['selected'] = None; join['directReview'] = None
    plan = save(storage, plan); join = join_for(plan, body)
    try:
        refs=generation_refs(storage,plan,join)
        join['attempt']['referenceManifest']=refs
        result = native_film.submit(handler, storage, {'production_mode':'bridge','model':model['id'],
            'bridge_join_mode':join['attempt']['joinMode'],
            'project_id':plan['projectId'], 'reference_images':refs,
            'prompt':f"上一镜：{plan['sources'][join['from']]['title']}。下一镜：{plan['sources'][join['to']]['title']}。\n"
                     + (f'【本接点必须完成的具体动作】\n{movement}\n完成方案明确要求的主要动作后按本方案的接法接入下一镜；保持无需改变的身体与道具状态，不以其他动作或一轮重复反应替代缺失动作。\n' if movement else '')
                     + '\n【原分镜意图与持续事实；实际状态以图1和图2为准】\n'+json.dumps(join_context(plan,join),ensure_ascii=False)
                     + '\n图3起仅为已核对版本的身份或场景参考，不是额外端点。'
                     + (f'【补充要求】\n{requirements}' if requirements else '保留前后动作因果，自然接回下一镜。'),
            'ratio':'16:9' if plan['sources'][0]['width']>=plan['sources'][0]['height'] else '9:16', 'duration':0})
        join['attempt'].update(taskId=result['taskId'],status=result.get('status','queued'))
    except Exception as exc:
        join['attempt'].update(status='failed' if '未提交' in str(exc) else 'unknown',error=str(exc))
        save(storage,plan)
        raise
    return save(storage,plan)


def query(handler, storage, body, plan, join):
    attempt = join.get('attempt') or {}
    if attempt.get('status') in ('succeeded','failed'): return plan
    if not attempt.get('taskId'): fail('没有已确认任务编号；请核对桥接回执，不会自动重试')
    result = handler._poll_video(storage,attempt['taskId'],attempt['model'])
    status = str(result.get('status') or '').lower()
    attempt['status'] = status
    if status in ('succeeded','completed','done','success'):
        url = result.get('video_url') or ''
        if '/file/' not in url or '/download' not in url: fail('独立补段尚未入库，请重新查询')
        file_id = unquote(url.split('/file/')[-1].split('/download')[0])
        candidate = assess(storage,plan,join,file_id)
        attempt['candidateId'] = candidate['id']
        attempt['status'] = 'succeeded'
    if status in ('failed','cancelled','canceled'):
        attempt['error'] = str(result.get('error') or '生成失败')
        # Native polling retains even a technically invalid output. Preserve its
        # file pointer in this workspace, without marking it eligible to compose.
        attempt['resultUrl'] = result.get('video_url')
    return save(storage,plan)


def review(storage, body, plan, join):
    checks = body.get('checks') or {}
    if not all(checks.get(key) is True for key in REVIEW_KEYS): fail('请完整检查两端、人物、全段动作与声音')
    if body.get('direct') is True:
        join['directReview'] = {key:True for key in REVIEW_KEYS}; join['selected'] = None
    else:
        candidate = next((c for c in join['candidates'] if c['id'] == body.get('candidate_id')), None)
        if not candidate or not candidate['technicalPassed']: fail('补段未通过两端检查，不能采用或强行合成')
        if candidate.get('needsSemanticReview'):
            if not all(checks.get(k) is True for k in ('space','prop')):fail('动作切镜还需检查空间方向、持物与动作阶段，不能仅凭像素或点击通过')
            if candidate.get('analysisId')!=(join.get('actionAnalysis') or {}).get('id'):fail('候选所用方案已经变化，请按对应方案重新检查',409)
        # Recheck actual bytes immediately; caller cannot inject a passing report.
        if sha(read_video(storage,candidate['fileId'])) != candidate['sha256']: fail('候选文件已变化',409)
        candidate['review'] = {key:True for key in (*REVIEW_KEYS,'space','prop') if checks.get(key) is True}
        join['selected'] = candidate['id']; join['directReview'] = None
    return save(storage,plan)


def approved_parts(storage, plan):
    verify_sources(storage,plan)
    parts = [plan['sources'][0]['fileId']]
    for join in plan['joins']:
        if not join.get('directReview'):
            chosen = next((c for c in join['candidates'] if c['id'] == join.get('selected')),None)
            if not chosen or not chosen['technicalPassed'] or not all((chosen.get('review') or {}).get(k) is True for k in REVIEW_KEYS):
                fail(f"接点{join['from']+1}→{join['to']+1}尚未通过；未开始合成")
            if sha(read_video(storage,chosen['fileId'])) != chosen['sha256']: fail('补段内容已变化；未开始合成',409)
            parts.append(chosen['fileId'])
            if chosen.get('needsSemanticReview') and not all((chosen.get('review') or {}).get(k) for k in ('space','prop')):fail('动作切镜尚未核对空间和持物，未开始合成')
        parts.append(plan['sources'][join['to']]['fileId'])
    return parts


def render(handler, storage, plan, parts):
    binary = handler._ffmpeg_binary()
    if not binary: fail('本地视频合成组件不可用')
    source = plan['sources'][0]
    width,height = source['width']//2*2, source['height']//2*2
    with tempfile.TemporaryDirectory(prefix='cdtv-approved-assembly-') as tmp:
        work = Path(tmp); files=[]
        for index,file_id in enumerate(parts):
            original = work/f'input-{index}.mp4'; original.write_bytes(read_video(storage,file_id))
            target = work/f'part-{index}.mp4'
            probe = subprocess.run([binary,'-hide_banner','-i',str(original)],capture_output=True,
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=30)
            has_audio = b'Audio:' in probe.stderr
            inputs=['-i',str(original)] + ([] if has_audio else ['-f','lavfi','-i','anullsrc=r=48000:cl=stereo'])
            args=[binary,'-hide_banner','-loglevel','error','-y',*inputs,'-map','0:v:0','-map','0:a:0' if has_audio else '1:a:0',
                '-vf',f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1',
                '-r',str(source['fps']),'-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p',
                '-c:a','aac','-b:a','192k','-ar','48000','-ac','2',
                *([] if has_audio else ['-shortest']),'-movflags','+faststart',str(target)]
            run = subprocess.run(args,capture_output=True,timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if run.returncode: fail('本地分段合成失败，原片和所有候选保留',502)
            files.append(target)
        listing=work/'parts.txt';listing.write_text('\n'.join(f"file '{p.name}'" for p in files),'utf8')
        output=work/'assembly.mp4'
        run=subprocess.run([binary,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(listing),
                            '-c','copy','-movflags','+faststart',str(output)],capture_output=True,timeout=180,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if run.returncode: fail('本地合片失败，原片和所有候选保留',502)
        content=output.read_bytes();info,_,_=inspect_video(content)
        expected=sum(inspect_video(read_video(storage,fid))[0]['duration'] for fid in parts)
        if abs(info['duration']-expected)>max(.15,len(parts)/source['fps']):
            fail('合片总帧时长与选段不符，尚未交付；原片和补段均保留',502)
        # Full source video/audio retained. No speed changes, freezes or trims.
        return {'fileId':storage.save_file('generated-videos',content,'已检查接点_组片候选.mp4','video/mp4')['id'],
                'sha256':sha(content),**info,'reviewStatus':'whole-film-review-required','parts':parts}


def dispatch(handler, storage, body):
    action=str(body.get('production_mode',''))[9:]
    if action in {'motion_start','motion_history'}:
        from motion_assembly import dispatch as motion_dispatch
        return motion_dispatch(handler,storage,body)
    if action=='prepare': return prepare(handler,storage,body)
    plan=load(storage,body)
    if action=='status':
        from assembly_context import hydrate
        return hydrate(storage,plan)
    if action=='cancel_analysis':
        from analysis_runtime import cancel
        return cancel(storage,body)
    verify_sources(storage,plan)
    if plan.get('rendering'): fail('这版正在合成或合成回执未确认，请勿重复开始',409)
    if action=='finalize':
        if plan['results']: return plan
        parts=approved_parts(storage,plan) # Before render, even temporary output creation.
        plan['rendering']=True;plan=save(storage,plan)
        try: plan['results'].append(render(handler,storage,plan,parts))
        finally:
            plan['rendering']=False;plan=save(storage,plan)
        return plan
    join=join_for(plan,body)
    if action=='approve_refs':
        from assembly_context import hydrate
        hydrate(storage,plan)
        if body.get('confirmed') is not True:fail('请先核对所选图片与当前成片的身份、风格和版本一致')
        available={r['fileId']:r['sha256'] for i in (join['from'],join['to']) for r in plan['sources'][i]['context'].get('references',[])}
        chosen=body.get('reference_ids')
        if not isinstance(chosen,list) or any(fid not in available for fid in chosen):fail('所选参考不属于这两个分镜')
        approvals=plan.setdefault('referenceApprovals',{})
        for fid in available:approvals.pop(fid,None)
        approvals.update({fid:available[fid] for fid in chosen})
        join['selected']=None;join['directReview']=None
        return save(storage,hydrate(storage,plan))
    if action=='plan_action':
        from continuity_planner import analyze
        return analyze(handler,storage,body,plan,join)
    if action=='apply_cut':
        from assembly_cuts import apply_cut
        return apply_cut(handler,storage,body,plan,join)
    if action=='generate': return generate(handler,storage,body,plan,join)
    if action=='query': return query(handler,storage,body,plan,join)
    if action=='review': return review(storage,body,plan,join)
    if action=='import':
        assess(storage,plan,join,str(body.get('file_id') or ''))
        return save(storage,plan)
    fail('未知的独立组片操作')
