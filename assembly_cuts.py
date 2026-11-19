"""Non-destructive cut-point variants; no source or dialogue is silently replaced."""
import copy,math,subprocess,tempfile,uuid
from pathlib import Path

def apply_cut(handler,storage,body,plan,join):
    from verified_assembly import fail,read_video,inspect_video,image_file,sha,save
    a=join.get('actionAnalysis') or {};s=a.get('edit_strategy') or {}
    if a.get('id')!=body.get('use_analysis_id') or s.get('type')!='trim_cut':fail('切点方案已经变化，请重新查看当前建议',409)
    if (join.get('analysisAttempt') or {}).get('status') in ('running','unknown'):fail('分析仍在执行，不能调整切点',409)
    if (join.get('attempt') or {}).get('status') in ('submitting','unknown','queued','running','processing'):fail('已有视频任务尚未结束',409)
    if not all((body.get('checks') or {}).get(k) is True for k in ('sound','action')):fail('请先连看原片，确认被去掉的区间没有完整对白、必要声音或关键动作')
    proposals=[(join['from'],0,s.get('previous_out')),(join['to'],s.get('next_in'),plan['sources'][join['to']]['duration'])]
    cuts=[]
    for i,start,end in proposals:
        src=plan['sources'][i];duration=src['duration']
        if type(start) not in (int,float) or type(end) not in (int,float) or not all(math.isfinite(v) for v in (start,end)) or not 0<=start<end<=duration:fail('建议切点不在实际视频范围内')
        if end-start<.25:fail('调整后片段过短')
        context=src.get('context',{});rows=context.get('protectedAudio') or []
        if (context.get('dialogue') or {}).get('text') and not rows and (start>0 or end<duration):fail('原分镜有对白但没有可靠音频区间，不能自动采用此切点；请在原镜头中核对')
        for row in rows:
            lo=row.get('start');hi=row.get('end')
            if type(lo) not in (int,float) or type(hi) not in (int,float) or start>lo or end<hi:fail('建议切点会裁掉已记录的对白区间，未修改原片')
        cuts.append((i,start,end))
    binary=handler._ffmpeg_binary()
    if not binary:fail('本地剪辑组件不可用')
    result=copy.deepcopy(plan);result['id']=uuid.uuid4().hex;result.pop('revision',None)
    result.update(parentPlanId=plan['id'],results=[],cutPointProposal={'analysisId':a['id'],'checks':body['checks']})
    with tempfile.TemporaryDirectory(prefix='cdtv-safe-cut-') as tmp:
        work=Path(tmp)
        for i,start,end in cuts:
            src=result['sources'][i]
            if start==0 and end==src['duration']:continue
            inp=work/f'in-{i}.mp4';out=work/f'out-{i}.mp4';inp.write_bytes(read_video(storage,src['fileId']))
            run=subprocess.run([binary,'-hide_banner','-loglevel','error','-y','-i',str(inp),'-ss',str(start),'-t',str(end-start),
                '-map','0:v:0','-map','0:a?','-c:v','libx264','-crf','18','-preset','veryfast','-c:a','aac','-movflags','+faststart',str(out)],
                capture_output=True,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if run.returncode:fail('切点副本制作失败，原方案保留',502)
            data=out.read_bytes();info,head,tail=inspect_video(data)
            if abs(info['duration']-(end-start))>max(.15,2/info['fps']):fail('切点副本实际时长不符合建议，未采用',502)
            original=src['fileId'];src.update(info)
            src.update(originalFileId=src.get('originalFileId') or original,inputFileId=src.get('inputFileId') or original,
                fileId=storage.save_file('assembly-cut-copies',data,f'cut-{i+1}.mp4','video/mp4')['id'],sha256=sha(data),
                selectedRange={'start':start,'end':end},head=image_file(storage,head,'cut-head.jpg'),tail=image_file(storage,tail,'cut-tail.jpg'))
            if src.get('context'):src['context']['protectedAudio']=[{**r,'start':r['start']-start,'end':r['end']-start} for r in src['context'].get('protectedAudio',[])]
    # Neighboring joins also have changed endpoints: invalidate their approvals.
    result['previousJoins']=result['joins'];result['joins']=[]
    for i in range(len(result['sources'])-1):
        result['joins'].append({'id':f'join-{i+1}-{i+2}','from':i,'to':i+1,'startImage':result['sources'][i]['tail'],
            'endImage':result['sources'][i+1]['head'],'candidates':[],'selected':None,'directReview':None})
    return save(storage,result)
