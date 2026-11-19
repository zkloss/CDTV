"""Owner-scoped storyboard evidence for assembly; intentions never override footage."""
import hashlib,json

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def hydrate(storage,plan):
    from local_storage import StorageError
    try: task=storage.get_document('video_projects',plan['projectId'])
    except StorageError as exc:
        if exc.status!=404:raise
        task={}
    boards=task.get('storyboards') or []
    for source in plan['sources']:
        if source.get('inputFileId') and source.get('context'):continue
        shot=next((s for s in boards if str(s.get('id'))==str(source.get('shotId'))),None)
        if not shot:
            hits=[s for s in boards if source['fileId'] in (s.get('resultFileId'),s.get('mixedVideoFileId'),s.get('originalVideoFileId'))]
            shot=hits[0] if len(hits)==1 else None
        if shot and source['fileId'] not in (shot.get('resultFileId'),shot.get('mixedVideoFileId'),shot.get('originalVideoFileId')):
            shot=None
        if not shot:
            source['context']={'status':'unlinked','intendedAction':source.get('description',''),'warnings':['未找到唯一对应的原分镜；仅按当前真实视频分析。'],'references':[]}
            continue
        source['shotId']=str(shot['id'])
        refs=[]
        for r in (shot.get('references') or []):
            if not isinstance(r,dict) or not r.get('fileId'):continue
            approved=r.get('continuityApproved') is True or (r.get('startFrameReview') or {}).get('status')=='passed'
            try:
                meta=storage.find_file(str(r['fileId']))
                if not meta.get('contentType','').startswith('image/'):continue
            except StorageError:continue
            approved=approved or (plan.get('referenceApprovals') or {}).get(str(r['fileId']))==meta.get('sha256')
            refs.append({'fileId':str(r['fileId']),'sha256':meta.get('sha256'), 'name':str(r.get('name',''))[:200],
                'role':r.get('category') or r.get('type') or 'reference','approvedForCurrentFootage':approved,
                'usage':'identity-and-setting' if approved else 'pending-style-and-version-review'})
        review=shot.get('performanceReview') or {}; warnings=[]
        if review.get('status')=='pending_generation':warnings.append(review.get('message') or '原镜头仍待按更新后的方案重拍；现有画面未更新。')
        if any(not r['approvedForCurrentFootage'] for r in refs):warnings.append('旧资产未确认与当前视频风格、版本一致，暂不作为生成图片输入。')
        source['context']={'status':'linked','shotId':source['shotId'],'intendedAction':str(shot.get('visual') or shot.get('prompt') or '')[:14000],
            'continuityState':shot.get('continuityState'),'actionChain':shot.get('actionChain'),'continuityPlan':shot.get('continuityPlan'),
            'environment':shot.get('environmentContinuity'),'dialogue':shot.get('dialogueBaseline') or shot.get('generationAudioContract'),
            'protectedAudio':(shot.get('breezeAlignment') or {}).get('rows',[]),'sourceNeedsRepair':review.get('status')=='pending_generation',
            'warnings':warnings,'references':refs,'actualFileId':source['fileId']}
    plan['contextSignature']=digest([s['context'] for s in plan['sources']])
    return plan

def join_context(plan,join):
    return {'authority':'真实源画面决定已经发生的状态；以下原分镜仅说明意图。冲突须标明，不能靠旧文字改写画面。',
            'previous':plan['sources'][join['from']].get('context',{}),'next':plan['sources'][join['to']].get('context',{})}

def generation_refs(storage,plan,join):
    refs=[{'fileId':join['startImage']},{'fileId':join['endImage']}];seen={r['fileId'] for r in refs}
    for i in (join['from'],join['to']):
        for r in plan['sources'][i].get('context',{}).get('references',[]):
            if not r['approvedForCurrentFootage'] or r['fileId'] in seen:continue
            meta=storage.find_file(r['fileId'])
            if meta.get('sha256')!=r['sha256']:
                from verified_assembly import fail
                fail('已确认参考图片发生变化，请重新分析',409)
            refs.append({'fileId':r['fileId'],'title':r['name']});seen.add(r['fileId'])
    if len(refs)>8:
        from verified_assembly import fail
        fail('已确认的参考图超过本次8张输入预算，请先整理参考职责；未提交视频')
    return refs

STRATEGIES={'direct_cut','trim_cut','bridge','repair_source','scene_cut'}
def strategy(result):
    from verified_assembly import fail
    value=result.get('edit_strategy')
    if value is None:fail('剪辑处理方式缺少edit_strategy字段',502)
    if not isinstance(value,dict) or value.get('type') not in STRATEGIES:fail('剪辑处理方式格式不正确',502)
    value=dict(value)
    # Some valid provider replies place strategy-specific fields at the root.
    # Copy only explicit fields; never guess a repair target/action or silently
    # choose between contradictory nested and root values.
    for key in ('repair_target','repair_action','previous_out','next_in'):
        if key not in result:continue
        if key in value and value[key] is not None and result[key] is not None and value[key]!=result[key]:
            fail('剪辑方案内外层字段冲突：'+key,502)
        if value.get(key) is None:value[key]=result[key]
    if value.get('join_mode','continuous') not in ('continuous','action_cut'):fail('补段接法格式不正确',502)
    if not str(value.get('reason','')).strip():fail('剪辑处理方式缺少依据',502)
    kind=value['type']
    if kind in ('direct_cut','scene_cut'):result['decision']='direct_cut'
    elif kind in ('trim_cut','repair_source'):result['decision']='needs_review'
    if kind=='repair_source' and (value.get('repair_target') not in ('previous','next') or not str(value.get('repair_action') or '').strip()):fail('局部修复方案缺少目标或具体动作',502)
    return {k:value[k] for k in ('type','reason','join_mode','previous_out','next_in','repair_target','repair_action') if k in value}
