"""Recover omitted authored shots without treating a partial model response as complete."""
import re

HEADING = re.compile(r'^(?:#{1,6}\s*|[-*+]\s+)?(?:\*\*)?[【\[]?\s*(?:第\s*(\d+)\s*镜|(?:镜头|分镜|镜)\s*(\d+(?:\s*[-—–－]\s*\d+)?))[】\]]?(?:\*\*)?')


def clean_key(value):
    return '-'.join(str(int(p)) for p in re.sub(r'\s', '', re.sub('[—–－]', '-', str(value))).split('-'))


def tag(value):
    match = HEADING.match(str(value or '').strip())
    return (clean_key(match[1] or match[2]), match[0]) if match else None


def parse_script_shots(script, consistency=None):
    consistency = consistency if isinstance(consistency, dict) else {}
    scenes = consistency.get('scenes') or []
    scene = scenes[0] if scenes else None
    scene_name, block, blocks = '', None, []
    for raw in str(script or '').splitlines():
        line = raw.strip()
        sc = re.match(r'^(?:#{1,6}\s*)?【场\s*\d+\s*([^】]+)】', line)
        if sc:
            scene_name = re.split(r'\s*[/／]\s*', sc[1])[0].strip()
            scene = next((s for s in scenes if s.get('name') and (s['name'] in scene_name or scene_name in s['name'])), None)
            continue
        match = tag(line)
        if match:
            block = dict(key=match[0], title=line[len(match[1]):].strip(), lines=[], scene=scene, sceneName=scene_name)
            blocks.append(block)
        elif block is not None and line and not re.fullmatch(r'["\'}\s]+', line):
            block['lines'].append(line)
    shots = []
    for index, b in enumerate(blocks, 1):
        camera = re.sub(r'^[（(]|[）)]$', '', b['title']).strip() or '固定机位'
        dialogue, visual, audio, duration = [], [], [], 10
        for line in b['lines']:
            timing = re.fullmatch(r'[【\[]?(\d{1,2}):(\d{2}(?:\.\d+)?)\s*[-—–~～]\s*(\d{1,2}):(\d{2}(?:\.\d+)?)[】\]]?', line)
            if timing:
                span = int(timing[3])*60+float(timing[4])-int(timing[1])*60-float(timing[2])
                if span > 0:
                    duration = span
                continue
            spoken = re.sub(r'^对白[：:]\s*', '', line)
            speech = re.match(r'^([^：:。！？]{1,30})[：:]\s*[“"「]', spoken)
            if speech and not re.search('画面|界面|文字|环境|音效|显示|生成|出现', speech[1]):
                dialogue.append(spoken)
                continue
            parts = re.split(r'(?:环境音|环境声|音效)[：:]', line)
            if parts[0].strip():
                visual.append(parts[0].strip())
            if len(parts) > 1:
                audio.append('；'.join(parts[1:]).strip())
        text = (b['title']+' '+' '.join(b['lines'])+' '+b['sceneName']).lower()
        references, wirelist = [], []

        def add(asset, kind):
            if not asset or not asset.get('id') or asset['id'] in references:
                return
            references.append(asset['id'])
            wirelist.append(dict(slot=f'图{len(wirelist)+1}', asset_id=asset['id'], name=asset.get('name'), type=kind,
                                 action='环境底图' if kind == 'scene' else '主体锚定'))

        add(b['scene'], 'scene')
        for group, kind in [('characters', 'character'), ('props', 'prop')]:
            for asset in consistency.get(group) or []:
                if asset.get('name') and all(word in text for word in asset['name'].lower().split()):
                    add(asset, kind)
        picture = '\n'.join(visual) or b['title']
        shots.append(dict(id=f'shot_{index:02}', sourceShotKey=b['key'], title=f"【镜{b['key']}】{camera}", duration_s=duration,
                          scene_id=(b['scene'] or {}).get('id', ''), references=references, wirelist=wirelist, visual=picture,
                          camera=camera, dialogue=dialogue, audio_prompt='；'.join(audio), video_prompt=picture+'。运镜：'+camera))
    return shots


def ensure_script_shot_coverage(document, script):
    root = document.get('consistency') or document.get('assets') or document
    expected = parse_script_shots(script, root)
    if not expected:
        return document
    keys = [s['sourceShotKey'] for s in expected]
    if len(set(keys)) != len(keys):
        raise ValueError('剧本中有重复的分镜编号，请先改为唯一编号再推送')
    original = document.get('shots') if isinstance(document.get('shots'), list) else root.get('shots', [])
    matched, unmatched = {}, []
    for shot in original:
        if not isinstance(shot, dict):
            continue
        explicit = shot.get('sourceShotKey') or (tag(shot.get('title')) or tag(shot.get('name')) or ('', ''))[0]
        ordinal = re.fullmatch(r'(?:json-shot-)?shot[_-]0*(\d+)', str(shot.get('id') or ''), re.I)
        position = int(ordinal[1])-1 if ordinal else -1
        key = clean_key(explicit) if explicit else keys[position] if 0 <= position < len(keys) else ''
        if key in keys and key not in matched:
            matched[key] = shot
        else:
            unmatched.append(shot)
    shots, recovered, used = [], [], set()
    for fallback in expected:
        key = fallback['sourceShotKey']
        if key not in matched:
            recovered.append(key)
        shot = {**fallback, **matched.get(key, {}), 'sourceShotKey': key}
        shot_id = str(shot.get('id') or fallback['id'])
        if shot_id in used:
            shot_id = f"{fallback['id']}_script_{key}"
        used.add(shot_id)
        shot['id'] = shot_id
        shots.append(shot)
    return {**document, 'shots': shots, 'shotCoverage': dict(expected=len(expected), received=len(original), recovered=recovered, keys=keys),
            **({'unmappedShots': [*(document.get('unmappedShots') or []), *unmatched]} if unmatched else {})}
