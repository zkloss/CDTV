"""Local, non-generative motion matching candidates. Never adopts or edits shots."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import subprocess
import tempfile
import threading

NS = 'motion_assemblies'
_lock = threading.RLock()
_workers = set()
ACTIVE = {'queued', 'running'}
stamp = lambda: datetime.now(timezone.utc).isoformat()
sha = lambda value: hashlib.sha256(value).hexdigest()


def fail(message, status=400):
    from local_storage import StorageError
    raise StorageError(status, message)


def sources_for(storage, body):
    from verified_assembly import read_video
    project_id = str(body.get('project_id') or '')
    if not project_id: fail('缺少作品编号')
    project = storage.get_document('video_projects', project_id)
    if project.get('productionMode') == 'template': fail('通用视频请继续使用原有成片流程')
    selected = body.get('source_videos')
    if not isinstance(selected, list) or not 2 <= len(selected) <= 12:
        fail('请选择2至12段当前分镜视频')
    current = {s.get('resultFileId'): s for s in project.get('storyboards', []) if s.get('resultFileId')}
    result = []
    for item in selected:
        if not isinstance(item, dict): fail('分镜素材格式不完整')
        fid = str(item.get('fileId') or '')
        if fid not in current: fail('所选视频不是这个作品的当前分镜，请重新打开预览', 409)
        shot = current[fid]
        if (shot.get('referenceReview') or {}).get('status') == 'failed':
            fail('有分镜未通过人物或场景参考检查，请先处理该分镜')
        data = read_video(storage, fid)
        result.append({'fileId': fid, 'shotId': shot['id'], 'title': shot.get('title', ''), 'sha256': sha(data)})
    if len({s['fileId'] for s in result}) != len(result): fail('同一段视频不能重复加入')
    order = {s['id']: i for i, s in enumerate(project['storyboards'])}
    if [order[s['shotId']] for s in result] != sorted(order[s['shotId']] for s in result):
        fail('请按当前分镜顺序选择视频')
    return project_id, result


def _save(storage, job_id, **patch):
    with _lock:
        return storage.update_document(NS, job_id, patch)


def run_command(args, timeout=300):
    p = subprocess.run(args, capture_output=True, timeout=timeout,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if p.returncode: fail('本地视频处理未完成，原片保留', 502)


def protect_frames(a, b, made, originals):
    """Retain actual frames where cross-shot correspondence is unreliable.

    A global median flow error misses a newly appearing person or a doubled
    ear. Such areas must not borrow pixels from another time/shot.
    """
    import cv2
    import numpy as np
    if len(made)!=len(originals) or any(f.shape!=a.shape for f in originals):
        fail('接点真实帧不完整，未进行补帧')
    h,w=a.shape[:2];size=(min(640,w),max(16,round(min(640,w)*h/w)))
    def gray(v):return cv2.cvtColor(cv2.resize(v,size),cv2.COLOR_BGR2GRAY)
    dis=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    forward=dis.calc(gray(a),gray(b),None);backward=dis.calc(gray(b),gray(a),None)
    x,y=np.meshgrid(np.arange(size[0],dtype=np.float32),np.arange(size[1],dtype=np.float32))
    def sample(v,flow):return cv2.remap(v,x+flow[:,:,0],y+flow[:,:,1],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT101)
    masks=[]
    for first,second,v,vback in ((a,b,forward,backward),(b,a,backward,forward)):
        im1=cv2.resize(first,size).astype(np.float32);im2=cv2.resize(second,size).astype(np.float32)
        photo=np.max(np.abs(cv2.GaussianBlur(im1,(7,7),0)-sample(cv2.GaussianBlur(im2,(7,7),0),v)),axis=2)
        error=np.linalg.norm(v+sample(vback,v),axis=2)
        strain=np.maximum(np.linalg.norm(np.gradient(v,axis=0),axis=2),np.linalg.norm(np.gradient(v,axis=1),axis=2))
        masks.append((photo>25)|(error>3)|(strain>.50))
    base=cv2.resize((masks[0]|masks[1]).astype(np.uint8),(w,h),interpolation=cv2.INTER_NEAREST)
    result=[];coverage=[]
    for synth,real in zip(made,originals):
        disagree=np.max(np.abs(cv2.GaussianBlur(synth,(5,5),0).astype(np.float32)-cv2.GaussianBlur(real,(5,5),0).astype(np.float32)),axis=2)>32
        risk=cv2.dilate((base|disagree).astype(np.uint8),np.ones((17,17),np.uint8))
        risk=cv2.GaussianBlur(risk.astype(np.float32),(15,15),0)
        # Preserve protected pixels exactly; blending endpoints must also be exact.
        weight=(1-risk)[...,None]
        clean=np.clip(real.astype(np.float32)*(1-weight)+synth.astype(np.float32)*weight,0,255).astype(np.uint8)
        clean[risk>=.999]=real[risk>=.999]
        result.append(clean);coverage.append(float(risk.mean()))
    result[0]=originals[0];result[-1]=originals[-1]
    return result,coverage


def boundary_morph(a, b, count, previous=None, following=None):
    import cv2
    import numpy as np
    h,w=a.shape[:2];small=(min(640,w),max(16,round(min(640,w)*h/w)))
    if count<2:return None
    def gray(x):return cv2.cvtColor(cv2.resize(x,small),cv2.COLOR_BGR2GRAY)
    dis=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    def flow(x,y):
        scale=np.array([w/small[0],h/small[1]],dtype=np.float32)
        return cv2.resize(dis.calc(gray(x),gray(y),None),(w,h))*scale
    difference=float(np.abs(gray(a).astype('float32')-gray(b).astype('float32')).mean()/255)
    if difference>.14:return None
    f=flow(a,b);back=flow(b,a)
    va=-flow(a,previous) if previous is not None else f/(count-1)
    vb=flow(b,following) if following is not None else -back/(count-1)
    x,y=np.meshgrid(np.arange(w,dtype=np.float32),np.arange(h,dtype=np.float32))
    def sample(v,mx,my):return cv2.remap(v,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT101)
    err_a=np.linalg.norm(f+sample(back,x+f[:,:,0],y+f[:,:,1]),axis=2)
    err_b=np.linalg.norm(back+sample(f,x+back[:,:,0],y+back[:,:,1]),axis=2)
    if float(np.median(err_a))>6:return None
    ca=np.exp(-err_a/(2+np.linalg.norm(f,axis=2)*.05)).astype(np.float32)
    cb=np.exp(-err_b/(2+np.linalg.norm(back,axis=2)*.05)).astype(np.float32)
    # Tangents follow real neighboring motion; clamp overshoot in occluded areas.
    def clamp(v,d):
        limit=np.linalg.norm(d,axis=2)*2+.5
        return v*np.minimum(1,limit/(np.linalg.norm(v,axis=2)+1e-5))[...,None]
    ta=clamp(va*(count-1),f);tb=clamp(vb*(count-1),back)
    tb_at_a=sample(tb,x+f[:,:,0],y+f[:,:,1]);ta_at_b=sample(ta,x+back[:,:,0],y+back[:,:,1])
    made=[]
    for n in range(count):
        t=n/(count-1)
        if n==0:made.append(a);continue
        if n==count-1:made.append(b);continue
        h01=3*t*t-2*t*t*t;h00=1-h01;h10=t*t*t-2*t*t+t;h11=t*t*t-t*t
        da=h01*f+h10*ta+h11*tb_at_a
        db=h00*back+h10*ta_at_b+h11*tb
        ax=x.copy();ay=y.copy();bx=x.copy();by=y.copy()
        for _ in range(3):
            av=sample(da,ax,ay);bv=sample(db,bx,by);ax=x-av[:,:,0];ay=y-av[:,:,1];bx=x-bv[:,:,0];by=y-bv[:,:,1]
        aa=sample(a,ax,ay).astype(np.float32);bb=sample(b,bx,by).astype(np.float32)
        wa=(1-t)*np.maximum(.08,sample(ca,ax,ay));wb=t*np.maximum(.08,sample(cb,bx,by));alpha=(wb/(wa+wb))[...,None]
        made.append(np.clip(aa*(1-alpha)+bb*alpha,0,255).astype(np.uint8))
    return made




def aligned_cut(previous,following):
    """Smooth a small cut offset while each output uses only its own real frame.

    previous: the last eight actual frames; following: the first sixteen.
    No temporal image blend, no new motion synthesis, no audio/time changes.
    """
    import cv2
    import numpy as np
    assert len(previous)==8 and len(following)==16
    a,b=previous[-1],following[0];h,w=a.shape[:2]
    assert all(v.shape==a.shape for v in previous+following)
    small=(min(640,w),max(16,round(min(640,w)*h/w)))
    def gray(v):return cv2.cvtColor(cv2.resize(v,small),cv2.COLOR_BGR2GRAY)
    dis=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    f=cv2.resize(dis.calc(gray(a),gray(b),None),(w,h))*np.array([w/small[0],h/small[1]],np.float32)
    f=cv2.GaussianBlur(f,(101,101),0)
    f*=np.minimum(1,32/(np.linalg.norm(f,axis=2)+1e-6))[...,None]
    # Refuse folds rather than smoothing over a physically invalid map.
    dx=np.gradient(f,axis=1);dy=np.gradient(f,axis=0)
    determinants=[]
    for amount in (-.5,.5):
        det=(1+amount*dx[:,:,0])*(1+amount*dy[:,:,1])-amount*amount*dy[:,:,0]*dx[:,:,1]
        determinants.append(float(det.min()))
    if min(determinants)<.3:raise ValueError('Geometric map folds or compresses too far; repair requires another strategy')
    x,y=np.meshgrid(np.arange(w,dtype=np.float32),np.arange(h,dtype=np.float32))
    def warp(img,amount):return cv2.remap(img,x+amount*f[:,:,0],y+amount*f[:,:,1],cv2.INTER_CUBIC,borderMode=cv2.BORDER_REFLECT101)
    left=[];right=[]
    for n,img in enumerate(previous):
        t=(n+1)/8;s=t*t*(3-2*t);left.append(warp(img,-.5*s))
    for n,img in enumerate(following):
        t=n/15;s=1-t*t*(3-2*t);right.append(warp(img,.5*s))
    return left,right,{'method':'single-source-geometry','minimumJacobian':min(determinants),'maxFieldDisplacement':float(np.max(np.linalg.norm(f,axis=2))),'temporalImageBlending':False}


def refine_geometry(handler, content, paths, infos, joins, work, progress):
    """Apply the approved single-image method only at a bounded geometry spike.

    Large appearance mismatches remain protected, never forced into alignment.
    Every new run starts with its own current source frames, not a cached movie.
    """
    import cv2
    import numpy as np
    baseline=work/'geometry-baseline.mp4';baseline.write_bytes(content)
    changes={};aligned=[];decisions=[];offset=0
    def read(path,start,count):
        cap=cv2.VideoCapture(str(path));cap.set(cv2.CAP_PROP_POS_FRAMES,start);frames=[]
        try:
            for _ in range(count):
                ok,frame=cap.read()
                if not ok:fail('接点真实帧读取不完整，未交付处理版',502)
                frames.append(frame)
        finally:cap.release()
        return frames
    for i,join in enumerate(joins):
        offset+=infos[i]['frames']
        decision={'from':i+1,'to':i+2,'applied':False}
        if not join['processed'] or join.get('protectedFraction',1)>=.5:
            decisions.append({**decision,'reason':'原画对应不可靠，保留原保护策略'});continue
        if min(infos[i]['frames'],infos[i+1]['frames'])<24:
            decisions.append({**decision,'reason':'窗口过短，避免与相邻接点重叠'});continue
        frames=read(baseline,offset-3,6)
        gray=[cv2.cvtColor(cv2.resize(f,(480,270)),cv2.COLOR_BGR2GRAY) for f in frames]
        dis=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        motion=[float(np.percentile(np.linalg.norm(dis.calc(a,b,None)[15:240,100:300],axis=2),80)) for a,b in zip(gray,gray[1:])]
        ratio=motion[2]/max(float(np.median([motion[n] for n in (0,1,3,4)])),.01)
        if ratio<=1.8:
            decisions.append({**decision,'reason':'没有孤立的切点位移尖峰','motionRatio':ratio});continue
        progress(f'对齐接点{i+1}→{i+2}的真实画面')
        try:left,right,meta=aligned_cut(read(paths[i],infos[i]['frames']-8,8),read(paths[i+1],0,16))
        except ValueError:
            decisions.append({**decision,'reason':'几何变形过大，保留原保护策略','motionRatio':ratio});continue
        changes.update({offset-8+n:f for n,f in enumerate(left+right)})
        meta={**decision,**meta,'applied':True,'motionRatioBefore':ratio,'startSeconds':(offset-8)/infos[i]['fps'],'endSeconds':(offset+15)/infos[i]['fps']}
        aligned.append(meta);decisions.append(meta)
    if not changes:return content,aligned,decisions
    width,height,fps=infos[0]['width'],infos[0]['height'],infos[0]['fps']
    binary=handler._ffmpeg_binary();picture=work/'geometry-picture.mp4'
    proc=subprocess.Popen([binary,'-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{width}x{height}','-r',str(fps),'-i','-','-an','-c:v','libx264','-crf','18','-preset','fast','-pix_fmt','yuv420p',str(picture)],stdin=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    cap=cv2.VideoCapture(str(baseline));n=0
    try:
        while True:
            ok,frame=cap.read()
            if not ok:break
            proc.stdin.write(changes.get(n,frame).tobytes());n+=1
        if n!=sum(v['frames'] for v in infos):fail('真实画面对齐后帧数不符',502)
        proc.stdin.close();proc.stdin=None;_,error=proc.communicate(timeout=180)
        if proc.returncode:fail('真实画面对齐编码未完成',502)
    finally:
        cap.release()
        if proc.poll() is None:proc.kill();proc.wait()
    output=work/'geometry-result.mp4'
    run_command([binary,'-v','error','-y','-i',str(picture),'-i',str(baseline),'-map','0:v:0','-map','1:a:0','-c','copy','-movflags','+faststart',str(output)])
    return output.read_bytes(),aligned,decisions


def render(handler, storage, sources, progress=lambda _: None):
    import cv2
    from verified_assembly import read_video, inspect_video
    binary = handler._ffmpeg_binary()
    if not binary: fail('本地视频处理组件不可用')
    with tempfile.TemporaryDirectory(prefix='cdtv-motion-') as tmp:
        work=Path(tmp);paths=[];infos=[];heads=[];tails=[];incoming=[];outgoing=[];real_heads=[];real_tails=[]
        for i,s in enumerate(sources):
            progress(f'读取第{i+1}段视频')
            data=read_video(storage,s['fileId'])
            if sha(data)!=s['sha256']: fail('源视频已变化，请重新选择',409)
            info,first,_=inspect_video(data)
            if info['frames']<9: fail('分镜过短，无法制作接点处理版')
            if info['width']*info['height']>1920*1080: fail('当前接点处理支持最高1080p，请先使用较小的副本')
            if infos and any(info[k]!=infos[0][k] for k in ('width','height','fps')):
                fail('当前视频的画幅或帧率不同，请先统一格式；未改变原片')
            p=work/f'{i}.mp4';p.write_bytes(data);paths.append(p);infos.append(info)
            # Include real motion on both sides. Ending at frame zero alone
            # reproduces the source's held/duplicate startup frame.
            c=cv2.VideoCapture(str(p))
            samples={}
            try:
                for n in sorted(set(range(5))|set(range(info['frames']-5,info['frames']))):
                    c.set(cv2.CAP_PROP_POS_FRAMES,n);ok,frame=c.read()
                    if not ok:fail('源视频接点附近无法解码')
                    samples[n]=frame
            finally:c.release()
            heads.append(samples[3]);incoming.append(samples[4])
            tails.append(samples[info['frames']-4]);outgoing.append(samples[info['frames']-5])
            real_heads.append([samples[n] for n in range(4)])
            real_tails.append([samples[n] for n in range(info['frames']-4,info['frames'])])
        width,height,fps=infos[0]['width'],infos[0]['height'],infos[0]['fps']
        changes={};joins=[];offset=0
        for i in range(len(paths)-1):
            progress(f'匹配接点{i+1}→{i+2}')
            offset+=infos[i]['frames'];made=boundary_morph(tails[i],heads[i+1],8,outgoing[i],incoming[i+1])
            protection=[]
            if made:
                made,protection=protect_frames(tails[i],heads[i+1],made,real_tails[i]+real_heads[i+1])
                changes.update({offset-4+n:f for n,f in enumerate(made)})
            joins.append({'from':i+1,'to':i+2,'processed':made is not None,'startSeconds':(offset-4)/fps,'endSeconds':(offset+3)/fps,'motionCadenceMatched':made is not None and max(protection,default=0)<.5,
                          'protectedFraction':max(protection,default=0),'preservesDisocclusions':bool(protection),'requiresMotionRepair':max(protection,default=0)>.5})
        if not changes: fail('接点差异较大，短距离处理不适用；请使用AI补动作或修复原镜头')
        # Audio is composed independently at original speed; no crossfade,
        # speech trimming, time stretch or re-voicing.
        progress('保留原音轨')
        args=[binary,'-hide_banner','-loglevel','error','-y'];filters=[];parts=[]
        for i,p in enumerate(paths):
            args+=['-i',str(p)]
            probe=subprocess.run([binary,'-hide_banner','-i',str(p)],capture_output=True,timeout=30,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            duration=infos[i]['frames']/fps
            if b'Audio:' in probe.stderr:
                filters.append(f'[{i}:a]aresample=48000,apad,atrim=duration={duration:.9f},asetpts=PTS-STARTPTS[a{i}]')
            else:
                filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={duration:.9f},asetpts=PTS-STARTPTS[a{i}]')
            parts.append(f'[a{i}]')
        filters.append(''.join(parts)+f'concat=n={len(paths)}:v=0:a=1[a]')
        audio=work/'audio.m4a'
        run_command(args+['-filter_complex',';'.join(filters),'-map','[a]','-vn','-c:a','aac','-b:a','192k',str(audio)])
        progress('生成接点处理版')
        picture=work/'picture.mp4'
        proc=subprocess.Popen([binary,'-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{width}x{height}','-r',str(fps),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(picture)],stdin=subprocess.PIPE,stderr=subprocess.PIPE,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        total=0
        try:
            for p,info in zip(paths,infos):
                c=cv2.VideoCapture(str(p));count=0
                try:
                    while True:
                        ok,frame=c.read()
                        if not ok: break
                        proc.stdin.write(changes.get(total,frame).tobytes());total+=1;count+=1
                finally:c.release()
                if count!=info['frames']:fail('源视频解码不完整，未交付处理版',502)
            proc.stdin.close();proc.stdin=None
            _,error=proc.communicate(timeout=180)
            if proc.returncode!=0:fail('接点视频编码未完成，原片保留',502)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
        output=work/'candidate.mp4'
        run_command([binary,'-hide_banner','-loglevel','error','-y','-i',str(picture),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-c','copy','-movflags','+faststart',str(output)])
        content=output.read_bytes();info,_,_=inspect_video(content)
        if info['frames']!=sum(i['frames'] for i in infos):fail('处理后总帧数不符，原片保留',502)
        base_hash=sha(content)
        content,aligned,decisions=refine_geometry(handler,content,paths,infos,joins,work,progress)
        info,_,_=inspect_video(content)
        if info['frames']!=sum(i['frames'] for i in infos):fail('对齐后总帧数不符，原片保留',502)
        stored=storage.save_file('generated-videos',content,'分镜接点处理_候选.mp4','video/mp4')
        return {'fileId':stored['id'],'sha256':sha(content),**info,'joins':joins,
                'method':'protected-single-source-alignment-v4','videoModelGenerated':False,
                'cadenceVersion':4,'artifactProtection':True,'preservesOriginalTimeline':True,
                'geometryAlignment':bool(aligned),'alignedJoins':aligned,'alignmentDecisions':decisions,'geometryBaseSha256':base_hash,
                'reviewStatus':'whole-film-review-required','sourceHashes':[s['sha256'] for s in sources]}


def _worker(handler,storage,job_id):
    try:
        job=_save(storage,job_id,status='running',stage='正在读取分镜')
        result=render(handler,storage,job['sources'],lambda text:_save(storage,job_id,stage=text))
        _save(storage,job_id,status='succeeded',stage='处理版已保存',result=result,finishedAt=stamp())
    except Exception as error:
        _save(storage,job_id,status='failed',stage='处理未完成',error=str(error) or type(error).__name__,finishedAt=stamp())
    finally:
        with _lock:_workers.discard(job_id)


def dispatch(handler,storage,body):
    from local_storage import StorageError
    project_id=str(body.get('project_id') or '')
    storage.get_document('video_projects',project_id)
    with _lock:
        jobs=[j for j in storage.list_documents(NS) if j.get('projectId')==project_id]
        for j in jobs:
            if j.get('status') in ACTIVE and j['id'] not in _workers:
                _save(storage,j['id'],status='interrupted',error='程序已重新启动，之前的本地处理未完成；原片保留，可重新制作',finishedAt=stamp())
        if body['production_mode']=='assembly_motion_history':
            return [storage.get_document(NS,j['id']) for j in jobs]
        if body['production_mode']!='assembly_motion_start':fail('未知的接点处理操作')
        request_id=str(body.get('request_id') or '')
        if not request_id or len(request_id)>100:fail('缺少本次处理编号')
        for j in jobs:
            if j.get('requestId')==request_id:
                incoming=[str(s.get('fileId') or '') for s in body.get('source_videos',[]) if isinstance(s,dict)]
                if incoming!=[s['fileId'] for s in j['sources']]:fail('本次处理编号已用于另一组素材，请重新开始',409)
                return storage.get_document(NS,j['id'])
            if j.get('status') in ACTIVE and j['id'] in _workers:return j
        if _workers:fail('已有接点处理正在进行，请稍后再试',409)
        project_id,sources=sources_for(storage,body)
        job=storage.create_document(NS,{'projectId':project_id,'requestId':request_id,'sources':sources,
                                       'status':'queued','stage':'准备处理接点','createdAt':stamp()})
        _workers.add(job['id'])
        threading.Thread(target=_worker,args=(handler,storage,job['id']),daemon=True).start()
        return job
