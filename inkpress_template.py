"""Explicit data binding for the bundled Ink Press composition, never model code."""
import copy
import math

TEMPLATE_ID='ink-press'
SLOTS=[('morning',220,'brand-ink-open / spotlight-hero-card'),('card1',55,'paper-title-card'),
       ('table',190,'deck-deal-flyin / type-and-filter'),('macro',100,'row-embed'),
       ('card2',55,'paper-title-card'),('chart',105,'list-stack-press'),('cardWbr',50,'paper-title-card'),
       ('wbr',110,'document-typewriter-reveal'),('card3',55,'paper-title-card'),('outro',145,'outro-group-photo-launch')]
COMPONENTS=['SceneOpen','PaperTitleCard','SceneFlyIn','SceneDetail','PaperTitleCard','ScenePapers','PaperTitleCard','SceneWbr','PaperTitleCard','SceneOutroLive']

def selected_template(brief):
    ident=str(brief.get('templateId') or ('ink-press' if brief.get('mode')=='template' else ''))
    if ident and ident!=TEMPLATE_ID:raise ValueError('所选整片模板尚无执行器，不能用通用排版代替；请选择 Ink Press 或切换自主创作')
    return ident

def bind(plan):
    """Preserve source content and narration order; bind the ten actual template slots.

    Native motion is never sped up to squeeze the 36.17 s template into 30 s.
    Longer slots hold their settled pose, leaving narration at its original speed.
    """
    plan=copy.deepcopy(plan);source=copy.deepcopy(plan['scenes']);already=plan.get('templateId')==TEMPLATE_ID and [s.get('templateSlot') for s in source]==[v[0] for v in SLOTS]
    requested=plan['durationInFrames'];scenes=[];cursor=0
    for i,(slot,native,recipe) in enumerate(SLOTS):
        if already:
            scene=source[i]
        else:
            left=math.floor(i*len(source)/10);right=math.floor((i+1)*len(source)/10)
            group=source[left:right]
            seed=source[min(left,len(source)-1)]
            scene=copy.deepcopy(seed)
            scene.update(narration=''.join(s['narration'] for s in group if s.get('narration')),sourceIndices=list(range(left,right)),
                         details=[v for s in group for v in [s['title'],s.get('subtitle',''),*s.get('items',[])] if v])
            if not group:scene['narration']=''
            if group:
                scene['items']=[v for s in group for v in s.get('items',[])][:6]
        if len(scene.get('narration',''))>500:raise ValueError('模板合并后的单段旁白超过500字，请减少内容；不会截词')
        frames=max(native,scene.get('frames',native)) if already else max(native,round(requested*native/1085))
        scene.update(templateSlot=slot,nativeFrames=native,templateComponent=COMPONENTS[i],recipe=recipe,
                     kind='title' if slot.startswith('card') else 'outro' if slot=='outro' else scene['kind'],
                     **{'from':cursor,'frames':frames,'seconds':frames/30})
        scenes.append(scene);cursor+=frames
    if cursor>5400:raise ValueError('所选模板和内容超过180秒，请缩短计划时长或旁白')
    plan.update(scenes=scenes,templateId=TEMPLATE_ID,templateName='Ink Press · 原版镜头执行',templateVersion=1,rendererVersion=3,
                templateOriginalFrames=1085,requestedDuration=plan.get('requestedDuration',requested/30),
                durationInFrames=cursor,duration=cursor/30,templateComponents=COMPONENTS,
                templateSourceScenes=plan.get('templateSourceScenes',source),theme='paper')
    return plan
