"""CDTV's general-video workspace. Read-only skill access; generation uses existing text models."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

_server = None
_server_lock = threading.Lock()


def skill_root() -> Path:
    here = Path(__file__).resolve().parent
    for base in (here, here.parent, here.parent.parent):
        candidate = base / 'SKILL' / 'video-shotcraft'
        if (candidate / 'SKILL.md').is_file():
            return candidate
    raise ValueError('完整 Shotcraft 技能目录未找到，请检查程序同步是否完成')


def resource_path(relative: str) -> Path:
    root = skill_root().resolve()
    path = (root / str(relative)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('技能资源不存在或路径不正确')
    return path


def read_resource(relative: str) -> str:
    path = resource_path(relative)
    if path.suffix.lower() not in {'.md', '.tsx', '.ts', '.js', '.mjs', '.json', '.py', '.txt', '.css', '.html'}:
        raise ValueError('该资源不是可读取的技能文档或源码')
    return path.read_text(encoding='utf-8')


def asset_base() -> str:
    global _server
    with _server_lock:
        if _server is None:
            class Assets(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_GET(self):
                    try:
                        path = resource_path(unquote(urlparse(self.path).path).lstrip('/'))
                        size = path.stat().st_size
                        start, end = 0, size - 1
                        requested = self.headers.get('Range', '')
                        if requested:
                            match = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
                            if not match:
                                self.send_error(416)
                                return
                            start = int(match[1])
                            end = min(int(match[2]) if match[2] else end, end)
                            if start > end:
                                self.send_error(416)
                                return
                        self.send_response(206 if requested else 200)
                        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.send_header('Accept-Ranges', 'bytes')
                        self.send_header('Content-Length', str(end - start + 1))
                        if requested:
                            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                        self.end_headers()
                        with path.open('rb') as source:
                            source.seek(start)
                            remaining = end - start + 1
                            while remaining:
                                chunk = source.read(min(65536, remaining))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                remaining -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    except (ValueError, OSError):
                        self.send_error(404)

            _server = ThreadingHTTPServer(('127.0.0.1', 0), Assets)
            _server.daemon_threads = True
            threading.Thread(target=_server.serve_forever, daemon=True, name='shotcraft-library').start()
        return f'http://127.0.0.1:{_server.server_address[1]}'


def catalog() -> dict:
    library = json.loads(read_resource('gallery/api/library.json'))
    base = asset_base()
    cards = []
    for card in library['cards']:
        item = {key: card.get(key, '') for key in ('name', 'summary', 'use', 'duration', 'energy', 'source', 'category')}
        item['styles'] = [{**style, 'previewUrl': base + '/gallery/' + style['media']['url'].removeprefix('./'),
                           'posterUrl': base + '/gallery/posters/' + style['key'] + '.jpg'}
                          for style in card['styles']]
        cards.append(item)
    root = skill_root()
    return {'cards': cards, 'categories': library.get('categories', {}), 'revision': library.get('revision'),
            'cardCount': len(cards), 'styleCount': sum(len(card['styles']) for card in cards),
            'previewCount': sum((root / 'gallery' / style['media']['url'].split('?')[0].removeprefix('./')).is_file()
                                for card in library['cards'] for style in card['styles']),
            'galleryUrl': base + '/gallery/index.html',
            'template': {'name': 'Ink Press', 'description': '纸墨晨读风 · 完整产品宣传片 · 约36秒', 'source': 'template/TEMPLATE.md'},
            'resources': sorted(str(path.relative_to(root)).replace('\\', '/') for path in root.rglob('*.md')),
            'capabilities': ['整片模板', '自主创作', '逐步共创', '全部镜头配方与源码', '声音与音乐卡点', '画面审查', '动效工作台', '剪映导出', '按用户要求发布']}


def build_context(body: dict, phase: str = 'plan') -> dict:
    library = json.loads(read_resource('gallery/api/library.json'))
    chosen = list(dict.fromkeys(str(value) for value in body.get('selectedCards', []) if value))
    index = {}
    for card in library['cards']:
        index[card['name']] = card
        for style in card['styles']:
            index[style['key']] = card
    unknown = [key for key in chosen if key not in index]
    if unknown:
        raise ValueError('镜头卡不存在：' + '、'.join(unknown))
    docs = ['SKILL.md', 'references/aesthetic-rules.md']
    mode = body.get('mode') or 'autonomous'
    docs += ['template/TEMPLATE.md'] if mode == 'template' else ['references/pipeline.md']
    if mode == 'guided':
        docs.append('references/guided-free-creation.md')
    task = str(body.get('prompt') or '')
    if re.search('配音|旁白|音效|音乐|声音|BGM|卡点', task, re.I) or phase == 'extract':
        docs += ['references/sound-design.md', 'references/sfx-sourcing.md']
    if re.search('BGM|音乐|卡点', task, re.I):
        docs.append('references/music-beat-sync.md')
    if re.search('剪映|导出工程', task):
        docs.append('references/jianying-export.md')
    if re.search('工作台|编辑动效|时间线', task):
        docs.append('references/workbench.md')
    if re.search('发布|上传平台', task):
        docs.append('references/publish-upload-post.md')
    if re.search('验收|检查|审查', task):
        docs.append('references/final-review.md')
    texts, sources, seen = [], [], set()

    def include(relative):
        relative = str(relative).replace('\\', '/')
        if relative in seen:
            return
        text = read_resource(relative)
        seen.add(relative)
        texts.append(f'\n【技能资源 {relative}】\n{text}')
        sources.append({'path': relative, 'sha256': hashlib.sha256(text.encode()).hexdigest()})
        # Resolve implementation dependencies from the actual source, never guess demo paths by card name.
        if relative.endswith(('.tsx', '.ts')):
            for imported in re.findall(r'(?:from\s+|import\s*)[\'"](\.[^\'"]+)[\'"]', text):
                target = resource_path(relative).parent / imported
                for candidate in (target, target.with_suffix('.tsx'), target.with_suffix('.ts'), target / 'index.tsx'):
                    if candidate.is_file() and candidate.suffix in {'.tsx', '.ts'}:
                        include(str(candidate.resolve().relative_to(skill_root().resolve())))
                        break

    for document in docs:
        include(document)
    if mode == 'template':
        include('template/src/aifl/Main.tsx')
    for key in chosen:
        card = index[key]
        include(card['source'])
        for source in re.findall(r'(?:demos|assets)/[\w./-]+\.(?:tsx|ts)', read_resource(card['source'])):
            include(source)
    recipes = '\n'.join(f"{card['name']} | {card['category']} | {card['summary']} | 时长:{card.get('duration', '')} | 能量:{card.get('energy', '')} | {card.get('use', '')}"
                        for card in library['cards'])
    project = body.get('project') if isinstance(body.get('project'), dict) else {}
    brief = body.get('brief') if isinstance(body.get('brief'), dict) else {}
    system = f'''你是 CDTV 通用视频创作助手，服务宣传、广告、科普、纪录、生活与创意短视频。
当前用户已选择创作模式：{mode}。以该选择执行 Shotcraft 对应模式，不重复要求选择模式。
本项目不属于连续短剧，不生成“第几集”、episodes、多集大纲，不套用短剧对白、人物表演、12~18镜或单镜8~10秒的固定要求。
总时长按用户简报规划，镜头长短依据内容、阅读速度、旁白、音乐与所选镜头卡决定。
项目资料和用户选定画风优先；科普以事实解释、步骤、对比、信息可读性为主，不强塞广告购买号召。
影视场景可用现有生图/视频模型；真实产品界面、准确文字和Logo可用模板动效。不能声称仅凭提示词已实现源码动效。
本次只执行用户当前按钮所代表的策划或分镜任务，不运行代码、不自动发布、不代替用户批准素材。
品牌名、代码和界面原文可以保留原语言，其余说明使用中文。
项目：{json.dumps(project, ensure_ascii=False)}
制作简报：{json.dumps(brief, ensure_ascii=False)}
完整镜头索引（全部 {len(library['cards'])} 张，按任务选择；精读卡片与准确源码）：
{recipes}
''' + '\n'.join(texts)
    if phase == 'extract':
        system += '''\n请提取完整资产与分镜，输出合法JSON对象：schema_version、title、style、consistency（characters/scenes/props/asset_wirelist）、shots。
shots逐镜完整覆盖原文，每镜含id/title/duration_s/visual/camera/dialogue/audio_prompt/video_prompt/references/scene_id；不凭空补人物或对白。
旁白明确写成旁白，不伪装角色对白。可增加shotcraft_card和render_kind（ai_video/motion/mixed）记录制作方式。
原文存在镜号时保留对应关系。只输出JSON，不输出解释。'''
    else:
        system += '''\n输出合法JSON对象，包含script（完整单片脚本）、summary（创作说明）、questions（共同创作模式需要的问题数组，否则空数组）、selectedCards（推荐镜头卡名数组）。
script使用【镜1】、【镜2】等唯一镜号，逐镜写时长、画面、字幕或旁白、声音与转场；不要套用人物场次要求。只输出JSON。'''
    return {'system': system, 'sources': sources, 'mode': mode, 'selectedCards': chosen,
            'availableCards': len(library['cards']), 'availableStyles': sum(len(card['styles']) for card in library['cards'])}


def dispatch(api, method: str, path: str, body=None, token=''):
    parsed = urlparse(path)
    body = body if isinstance(body, dict) else {}
    if parsed.path.startswith('/shotcraft/film/'):
        from whole_film_renderer import dispatch as film_dispatch
        return film_dispatch(api, method, parsed.path, body, token=token)
    if method == 'GET' and parsed.path == '/shotcraft/catalog':
        return catalog()
    if method == 'GET' and parsed.path == '/shotcraft/resource':
        name = parse_qs(parsed.query).get('path', ['SKILL.md'])[0]
        return {'path': name, 'content': read_resource(name)}
    if method == 'POST' and parsed.path in {'/shotcraft/context', '/shotcraft/plan', '/shotcraft/extract'}:
        phase = 'extract' if parsed.path.endswith('/extract') else 'plan'
        context = build_context(body, phase)
        if parsed.path.endswith('/context'):
            return context
        if not str(body.get('model') or '').strip():
            raise ValueError('请先选择文本模型')
        from local_storage import _Handler
        history = [{'role': turn['role'], 'content': str(turn.get('content') or '')}
                   for turn in body.get('history', []) if isinstance(turn, dict) and turn.get('role') in {'user', 'assistant'}][-40:]
        user = str(body.get('prompt') or '') + '\n当前脚本：\n' + str(body.get('script') or '')
        def ask(current_context):
            return api.backend_request('POST', '/ai/chat', '', {
                'model': body['model'], 'messages': [{'role': 'system', 'content': current_context['system']}, *history,
                    {'role': 'user', 'content': user}], 'temperature': 0.4, 'max_tokens': 16000,
            })
        response = ask(context)
        text = _Handler._chat_result_text(response)
        if phase == 'extract':
            document = _Handler._parse_creation_json(text, script_text=str(body.get('script') or ''))
            project = body.get('project') or {}
            for key in ('style', 'storyGenres', 'styleNotes', 'ratio'):
                if key in project:
                    document[key] = project[key]
            document['project'] = {key: project[key] for key in ('name', 'description', 'style', 'storyGenres', 'styleNotes', 'ratio') if key in project}
            result = {'document': document}
        else:
            clean = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.I).strip()
            start = clean.find('{')
            try:
                value, _ = json.JSONDecoder(strict=False).raw_decode(clean[start:])
            except (ValueError, TypeError):
                raise ValueError('文本模型没有返回完整方案，请保留当前脚本后重试')
            if not isinstance(value, dict) or (not value.get('script') and not value.get('questions')):
                raise ValueError('文本模型没有返回脚本或共创问题，当前内容未替换')
            # Autonomous selection is followed by an implementation-aware pass, so recommendations
            # become real recipe/source context rather than names invented from the gallery.
            recommendations = value.get('selectedCards')
            if value.get('script') and not body.get('selectedCards') and isinstance(recommendations, list) and recommendations:
                context = build_context({**body, 'selectedCards': recommendations}, phase)
                revised = _Handler._chat_result_text(ask(context))
                revised = re.sub(r'<think>[\s\S]*?</think>', '', revised, flags=re.I).strip()
                try:
                    checked, _ = json.JSONDecoder(strict=False).raw_decode(revised[revised.find('{'):])
                except (ValueError, TypeError):
                    raise ValueError('镜头配方核对未返回完整方案，原脚本未替换')
                if not isinstance(checked, dict) or not checked.get('script'):
                    raise ValueError('镜头配方核对缺少完整脚本，原脚本未替换')
                value = checked
            result = value
        result['skillContext'] = {key: value for key, value in context.items() if key != 'system'}
        return result
    raise ValueError('通用视频接口不存在')
