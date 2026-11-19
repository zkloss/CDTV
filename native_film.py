"""Muse native scene production: keep full scripts and source videos intact."""
from __future__ import annotations

import base64
import hashlib
import uuid
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlparse
import httpx


ASSEMBLY_UPLOAD_BUDGET = 14 * 1024 * 1024


def _extract_frame_bytes(video_data, position='last', max_dim=720, jpeg_quality=85, binary=None):
    """Best-effort head/tail context using the bundled runtime, without OpenCV."""
    if not video_data or not binary:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix='cdtv-assembly-boundary-') as work:
            path = Path(work) / 'source.mp4'
            path.write_bytes(video_data)
            # Container/audio duration may extend beyond the final video frame.
            # Decode a short tail window, then select its last decodable frame.
            seek = ['-sseof', '-0.25'] if position == 'last' else []
            scale = f"scale=w='min({max_dim},iw)':h='min({max_dim},ih)':force_original_aspect_ratio=decrease"
            if position == 'last':
                scale += ',reverse'
            quality = max(2, min(31, round((100 - jpeg_quality) * .29) + 2))
            command = [str(binary), '-hide_banner', '-loglevel', 'error', *seek, '-i', str(path),
                       '-frames:v', '1', '-vf', scale, '-q:v', str(quality), '-f', 'image2pipe', '-vcodec', 'mjpeg', '-']
            result = subprocess.run(command, capture_output=True, timeout=30,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return result.stdout if result.returncode == 0 and result.stdout.startswith(b'\xff\xd8') else None
    except (OSError, subprocess.SubprocessError):
        return None


def _bridge_contracts(source_records, boundary_frames, reference_count=0):
    images = {(index, position): reference_count+n+1 for n, (index, position, _) in enumerate(boundary_frames)}
    return [{'id': f'join-{i+1}-{i+2}', 'fromIndex': i+1, 'toIndex': i+2,
             'fromFileId': source_records[i]['fileId'], 'toFileId': source_records[i+1]['fileId'],
             'startImageIndex': images.get((i, 'last')), 'endImageIndex': images.get((i+1, 'first')),
             'reviewEdges': ['source_to_bridge', 'bridge_to_next_source'], 'reviewStatus': 'pending'}
            for i in range(len(source_records)-1)]


def _assemble_instruction(production_id, source_records, prompt, duration, has_boundary_frames=False, boundary_frame_labels=None, bridge_contracts=None):
    """Build a director-style editing brief for Muse assemble mode.

    Give the model explicit permission to trim, re-cut, add transitions and
    generate brief bridges, while keeping characters, plot facts and dialogue.
    """
    lines = [
        f"【本次 AI 组片 {production_id}】你是一位剪辑导演。以下 {len(source_records)} 段已生成分镜视频是素材，请把它们剪辑、组接成一条连贯的完整成片。",
        "",
        "任务要求：",
        "1. 保留人物身份、剧情事实和全部关键对白；不省略、不重复、不截断台词。",
        "2. 分镜排列用于保持关键事件先后与因果，不必逐镜原样照搬、每镜等长或沿原边界硬切。可以调整入出点、镜头长短、局部动作和反应，删去冗余停顿，并用J-cut/L-cut等方式让原声跨镜延续。",
        "3. 逐一检查每个接点的人物位置、视线、手部与道具、动作阶段、机位及声音。无法仅靠剪辑接顺时，需要自行生成缺失动作或短过渡镜头（bridge），再接回原素材，不必等用户逐处指出。通常1至3秒，以补完整动作为准；不要仍然硬拼，也不要只用叠化、黑场或静帧掩盖跳变。",
        "4. 补生成仅用于连接原剧情，保持人物身份、场景空间、天气、道具状态和关键动作结果，不新增实质剧情或角色，不重新拍摄整部作品，不擅自重新配音。完整关键对白、说话人和原配音保留，不截词、不重复台词。",
        "4a. 每个补段必须同时服从两个真实边界：起点接上一镜选定切出帧，终点接下一镜选定切入帧。先选两端再生成，不能只从上一镜自由续写；调整切点时，从原视频重新提取实际切出/切入帧作为两端参考，不能凭想象改终点。",
        "4b. 用两侧原画面约束同一张脸、五官比例、衣服、手与道具位置、视线、景别、机位和屏幕方向；沿用原片的写实质感、曝光、色温与表演幅度。不要擅自把眼睛睁得更大、改脸型、强化惊讶或增加大片强蓝光等效果。原片已有特效的亮度、面积和出现时机也应匹配。",
        "4c. 输出前分别检查“上一镜→补段”和“补段→下一镜”，两头都自然才可用于成片；补段末尾必须回到下一镜开头的姿态、视线、道具状态、景别及光线。若后端对不上，重做或重剪该补段，不得只接好前端就原样交付，也不要靠冻结或叠化把问题藏起来。",
        "5. 必须覆盖全部所选片段的有效剧情，不能直接把某一段原片当作完整结果。总时长可随修剪冗余和补过渡自然变化，不强制等于源视频时长之和。",
        "6. 直接交付包含实际过渡处理的最终成片视频附件。",
        "",
        "素材顺序与基本信息（时长为近似值，仅作剪辑参考）：",
    ]
    for i, rec in enumerate(source_records, 1):
        dur = rec.get('duration')
        dur_text = f" 约{dur:g}秒" if dur else ""
        desc = rec.get('description')
        desc_text = f" — {desc}" if desc else ""
        lines.append(f"{i}. {rec['name']}{dur_text}{desc_text}")
    if len(source_records) > 1:
        lines.append("")
        lines.append("衔接处理建议（按素材顺序）：")
        for item in bridge_contracts or _bridge_contracts(source_records, []):
            start = f"图{item['startImageIndex']}（上一镜真实尾帧）" if item['startImageIndex'] else "从上一段视频提取实际切出帧（本次未附对应边界图）"
            end = f"图{item['endImageIndex']}（下一镜真实首帧）" if item['endImageIndex'] else "从下一段视频提取实际切入帧（本次未附对应边界图）"
            lines.append(f"- 接点{item['fromIndex']}→{item['toIndex']}：补段起点={start}；补段终点={end}。同时使用这两端约束生成，并分别验收入接和出接。")
    if has_boundary_frames:
        lines.append("")
        labels = "、".join(boundary_frame_labels or [])
        lines.append(f"参考图说明：同时上传了实际提取的边界关键帧，其图像附件序号为：{labels}。每个接点必须成对查看上一镜尾帧和下一镜首帧。它们是补段两端的真实状态参考，不是仅供自由发挥的风格图片；不能只读取第一张图便生成。")
    lines.append("")
    if duration:
        lines.append(f"目标时长{duration}秒，完整保留剧情与对白。")
    else:
        lines.append("按剧情和自然对白安排完整时长。")
    req = str(prompt or '').strip()
    if req:
        lines.append("")
        lines.append("【用户补充剪辑要求】")
        lines.append(req)
    lines.append("")
    lines.append(f"请将本次最终视频作为一个附件返回，文件名 film_{production_id}.mp4。")
    return "\n".join(lines)


def prepare_assembly_uploads(handler, videos, budget=ASSEMBLY_UPLOAD_BUDGET):
    """Prepare upload copies only when the encrypted inline request would be too large.

    Keep original files untouched. No trims, frame-rate changes, resizes, or audio
    re-synthesis: the audio streams are copied. The caller records both hashes.
    """
    from local_storage import StorageError
    if budget <= 0:
        raise StorageError(400, '参考图已超过组片上传预算，请减少参考素材；本次未提交')
    if sum(len(data) for _, data in videos) <= budget:
        return videos
    binary = handler._ffmpeg_binary()
    if not binary:
        raise StorageError(400, '组片视频合计过大，缺少上传副本压缩工具；本次未提交')
    durations = [handler._validate_video_duration(data, 0).get('actualDuration') for _, data in videos]
    if any(not duration or duration <= 0 for duration in durations):
        raise StorageError(400, '有源视频无法读取完整时长，请检查对应分镜；本次未提交')
    # Reserve room for the unchanged audio, container metadata and short-clip rate control.
    rate = int(budget * .9 * 8 / sum(durations) / 1000) - 384
    if rate < 500:
        raise StorageError(400, '片段总时长过长，压缩会明显影响画面，请减少所选片段分批组片；本次未提交')
    copies = []
    with tempfile.TemporaryDirectory(prefix='cdtv-assembly-upload-') as work:
        for index, ((_, data), duration) in enumerate(zip(videos, durations)):
            source = Path(work) / f'{index}-source.mp4'
            target = Path(work) / f'{index}-upload.mp4'
            source.write_bytes(data)
            common = [binary, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
                      '-map', '0:v:0', '-map', '0:a?', '-c:v', 'libx264', '-preset', 'fast',
                      '-b:v', f'{rate}k', '-maxrate', f'{int(rate * 1.5)}k', '-bufsize', f'{rate * 2}k',
                      '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough', '-passlogfile', str(Path(work) / f'{index}-pass')]
            commands = [common + ['-pass', '1', '-an', '-f', 'null', os.devnull],
                        common + ['-pass', '2', '-c:a', 'copy', '-movflags', '+faststart', str(target)]]
            try:
                for command in commands:
                    result = subprocess.run(command, capture_output=True, timeout=180,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    if result.returncode:
                        raise StorageError(400, '无法在保留原音轨的前提下准备上传副本，请检查源片格式或分批组片；本次未提交')
            except (OSError, subprocess.SubprocessError) as exc:
                raise StorageError(400, '组片上传副本准备失败，原分镜保持；本次未提交') from exc
            content = target.read_bytes()
            actual = handler._validate_video_duration(content, 0).get('actualDuration')
            if not actual or abs(actual - duration) > .08:
                raise StorageError(400, '上传副本时长发生变化，已停止，原分镜保持；本次未提交')
            copies.append(('video/mp4', content))
    if sum(len(data) for _, data in copies) > budget:
        raise StorageError(400, '保留原音轨后仍超过上传预算，请减少片段分批组片；本次未提交')
    return copies


def install(handler_class):
    """Add explicit native modes while preserving the deployed shot methods."""
    from script_document_import import install as install_script_documents
    install_script_documents(handler_class)
    if getattr(handler_class, '_native_film_installed', False):
        return
    previous_submit = handler_class._submit_video
    previous_poll = handler_class._poll_video

    def dispatch_submit(self, storage, body):
        if body.get('production_mode') not in (None, '', 'shot'):
            return submit(self, storage, body)
        return previous_submit(self, storage, body)

    def dispatch_poll(self, storage, task_id, selected):
        from local_storage import StorageError
        model = self._video_model(storage, selected)
        cache_id = hashlib.sha256(f"{model['id']}:{task_id}".encode()).hexdigest()
        try:
            submission = storage.get_document('ai_video_submissions', cache_id)
        except StorageError as exc:
            if exc.status != 404:
                raise
            submission = {}
        if not submission.get('productionMode'):
            return previous_poll(self, storage, task_id, selected)
        return poll(self, storage, task_id, model, submission, cache_id)

    handler_class._submit_video = dispatch_submit
    handler_class._poll_video = dispatch_poll
    handler_class._native_film_installed = True
    # Kept for release verification: original deployed methods stay unchanged.
    handler_class._native_film_previous_submit = previous_submit
    handler_class._native_film_previous_poll = previous_poll


def poll(handler, storage, task_id, model, submission, cache_id):
    from local_storage import StorageError, _safe_segment
    _safe_segment(task_id, '任务 ID')
    try:
        return storage.get_document('ai_video_results', cache_id)['result']
    except StorageError as exc:
        if exc.status != 404:
            raise
    result = None
    for endpoint in handler._video_poll_candidates(str(model.get('apiUrl') or ''), task_id):
        try:
            result = handler._request_ai_json(model, endpoint, 'Muse整场进度查询', timeout=60)
            break
        except StorageError as exc:
            if '404' in str(exc) or 'Invalid URL' in str(exc):
                continue
            raise
    if not isinstance(result, dict):
        raise StorageError(502, '尚未取回整场任务进度，请重新查询，无需重新生成')
    data = result.get('data') if isinstance(result.get('data'), dict) else {}
    content = result.get('content') if isinstance(result.get('content'), dict) else {}
    status = str(result.get('status') or result.get('state') or data.get('status') or data.get('state') or '').lower()
    result['status'] = status
    if status not in {'succeeded', 'completed', 'done', 'success'}:
        return result
    video_url = (result.get('video_url') or result.get('output_url') or result.get('url')
                 or content.get('video_url') or data.get('video_url') or data.get('url'))
    if not video_url and isinstance(result.get('data'), list) and result['data']:
        first = result['data'][0]
        video_url = (first.get('url') or first.get('video_url')) if isinstance(first, dict) else None
    if not video_url or urlparse(str(video_url)).scheme not in {'http', 'https'}:
        raise StorageError(502, '整场任务未返回有效视频地址，请检查桥接记录，无需重新生成')
    try:
        trust_env = urlparse(video_url).hostname not in {'127.0.0.1', 'localhost', '::1'}
        with httpx.Client(timeout=300, trust_env=trust_env, follow_redirects=True) as client:
            response = client.get(video_url)
            response.raise_for_status()
            mime = response.headers.get('content-type', 'video/mp4').split(';')[0].strip()
            if not response.content or not (mime.startswith('video/') or mime == 'application/octet-stream'):
                raise StorageError(502, '整场视频为空或内容无效，尚未替换采用版')
            report = validate(handler, response.content, submission)
            stored = storage.save_file('generated-videos', response.content, f'{task_id}.mp4', mime)
            result.update(video_url=handler._legacy_file(stored)['url'], validation=report,
                          production_mode=submission['productionMode'])
            if not report['passed']:
                result.update(status='failed', error={'code':'invalid_native_film', 'message':report['reason']})
    except httpx.HTTPError as exc:
        raise StorageError(502, '整场视频下载暂未完成，请重新查询，无需重新提交生成') from exc
    storage.save_document('ai_video_results', cache_id, {'result':result}, expected_revision=None)
    return result


def submit(handler, storage, body):
    from local_storage import StorageError
    if str(body.get('production_mode') or '').startswith('assembly_'):
        from verified_assembly import dispatch
        return dispatch(handler, storage, body)
    try:
        return _submit(handler, storage, body)
    except StorageError as exc:
        if not getattr(exc, "native_dispatched", False) and "未提交" not in str(exc):
            raise StorageError(exc.status, f"{exc}；本次未提交生成任务") from exc
        raise


def _submit(handler, storage, body):
    # Import lazily: local_storage owns the HTTP boundary and error type.
    from local_storage import StorageError

    mode = body.get("production_mode")
    if mode not in {"scene", "assemble", "bridge"}:
        raise StorageError(400, "请选择整场生成或已有视频组片")
    model = handler._video_model(storage, body.get("model"))
    if not str(model.get("modelName", "")).lower().startswith("muse-video"):
        raise StorageError(400, "整场制作请明确选择 Muse 视频模型")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise StorageError(400, "请填写完整剧本或组片要求")
    try:
        duration = int(body.get("duration") or 0)
    except (ValueError, TypeError) as exc:
        raise StorageError(400, "目标时长必须为整数秒") from exc
    if duration < 0 or duration > 3600:
        raise StorageError(400, "目标时长应为0至3600秒，0表示按剧情安排")
    sources = body.get("source_videos") or []
    references = body.get("reference_images") or []
    if not isinstance(sources, list) or not isinstance(references, list):
        raise StorageError(400, "视频和参考图必须按列表提交")
    if len(sources) > 12 or len(references) > 32:
        raise StorageError(400, "一次最多提交12段视频和32张参考图")
    if mode == "assemble" and len(sources) < 2:
        raise StorageError(400, "组片请至少选择两段视频")
    if mode == "scene" and sources:
        raise StorageError(400, "已有视频请使用组片方式提交")
    if mode == 'bridge' and (sources or len(references) != 2):
        raise StorageError(400, '独立补段必须使用实际切出和切入两张边界图')

    endpoint = handler._video_submit_candidates(str(model.get("apiUrl") or ""))[0]
    root = urlparse(endpoint)
    capability_url = f"{root.scheme}://{root.netloc}/v1/video-capabilities"
    try:
        capabilities = handler._request_ai_json(model, capability_url, "整场制作能力检查", timeout=15)
    except StorageError as exc:
        label = "组片" if mode == "assemble" else "整场制作"
        detail = str(exc)
        if isinstance(exc.__cause__, httpx.ConnectError):
            status = 503
            reason = f"未连接到 Muse 桥接（{root.netloc}），请先启动 Muse2API 并确认服务已就绪"
        elif exc.status == 504 or isinstance(exc.__cause__, httpx.TimeoutException):
            status = 504
            reason = "Muse 桥接能力检查超时，请确认 Muse2API 服务已就绪"
        elif any(f"HTTP {code}" in detail for code in (401, 403)):
            status = 502
            reason = "Muse 桥接认证未通过，请核对视频模型的 API 密钥与 Muse2API 配置"
        elif any(f"HTTP {code}" in detail for code in (404, 405)):
            status = 502
            reason = f"当前连接的 Muse 桥接缺少{label}能力接口，请确认已运行配套新版 Muse2API"
        else:
            status = 502
            reason = f"Muse 桥接能力检查失败：{detail}"
        raise StorageError(status, f"{reason}；本次未提交{label}任务") from exc
    if ('shot' if mode == 'bridge' else mode) not in capabilities.get("production_modes", []):
        raise StorageError(400, "当前Muse桥接不支持所选制作方式，本次未提交生成任务")

    total = 0
    source_records = []
    source_data = []

    def encode(item, kind):
        nonlocal total
        if not isinstance(item, dict) or not item.get("fileId"):
            raise StorageError(400, "素材尚未入库，请先导入文件")
        meta = storage.find_file(str(item["fileId"]))
        mime = str(meta.get("contentType") or "")
        if not mime.startswith(kind + "/"):
            raise StorageError(400, f"素材类型不正确：{meta.get('name', '')}")
        size = int(meta.get("size") or 0)
        total += size
        if size > 64 * 1024 * 1024 or total > 128 * 1024 * 1024:
            raise StorageError(400, "单个素材最大64MB，一次素材合计最大128MB，请分场制作")
        data = storage.read_file_content(meta["bucket"], meta["id"])
        if kind == "video":
            source_data.append((mime, data))
            source_records.append({"fileId": meta["id"], "name": str(item.get("title") or meta.get("name") or ""),
                                   "description": str(item.get("description") or "").strip(),
                                   "sha256": hashlib.sha256(data).hexdigest()})
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"

    images = [encode(item, "image") for item in references]
    videos = [encode(item, "video") for item in sources]
    if mode == 'assemble':
        # Muse may not actually "watch" attached video files, so also send
        # first/last frames as images so the model can see continuity.
        boundary_frames = []
        for index, (_, data) in enumerate(source_data):
            for position in ('first', 'last'):
                frame = _extract_frame_bytes(data, position, binary=handler._ffmpeg_binary())
                if frame:
                    boundary_frames.append((index, position, frame))
                    total += len(frame)
        if total > 128 * 1024 * 1024:
            raise StorageError(400, "视频与关键帧合计超过128MB，请减少片段或隐藏部分分镜后分批组片；本次未提交")
        for _, _, frame in boundary_frames:
            images.append(f"data:image/jpeg;base64,{base64.b64encode(frame).decode('ascii')}")
        reference_bytes = total - sum(len(data) for _, data in source_data)
        upload_videos = prepare_assembly_uploads(handler, source_data, ASSEMBLY_UPLOAD_BUDGET - reference_bytes)
        videos = [f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}" for mime, data in upload_videos]
        for record, (_, data) in zip(source_records, upload_videos):
            record.update(uploadSha256=hashlib.sha256(data).hexdigest(), uploadBytes=len(data),
                          uploadCopyPrepared=hashlib.sha256(data).hexdigest() != record['sha256'])
            duration_info = handler._validate_video_duration(data, 0)
            record["duration"] = duration_info.get("actualDuration") or 0
    production_id = uuid.uuid4().hex[:12]
    if mode == 'assemble':
        labels = [f"图{len(references)+n+1}：第{index+1}段{'首帧' if position == 'first' else '尾部'}"
                  for n, (index, position, _) in enumerate(boundary_frames)]
        contracts = _bridge_contracts(source_records, boundary_frames, len(references))
        instruction = _assemble_instruction(production_id, source_records, prompt, duration,
                                            has_boundary_frames=bool(boundary_frames), boundary_frame_labels=labels,
                                            bridge_contracts=contracts)
    elif mode == 'bridge':
        endpoint_rule=('图1为真实起点；完成必要演员动作后将切入图2的另一机位。图2只约束人物、持物及动作阶段，末帧不要求复制图2构图，不要额外绕拍。'
                       if body.get('bridge_join_mode')=='action_cut' else '图1为真实起点，图2为真实终点；从图1的动作状态自然到达图2。')
        instruction = (f'【独立过渡 {production_id}】只制作这一处过渡，不组装整片。'
                       + endpoint_rule +
                       '保持同一人物五官、衣服、道具、空间、光线和写实表演。'
                       '以完成衔接的最短动作为准，目标1至3秒；不重复反应，不新增对白、剧情或强特效。'
                       '不插入静帧，不冻结首尾，不叠化掩盖跳变。只返回实际生成的独立视频附件。\n'
                       + prompt + f'\n文件名 bridge_{production_id}.mp4。')
    else:
        instruction = (f"【本次整场制作 {production_id}】根据完整剧本自行安排分镜、分段生成并组装为完整视频。\n"
                       "保持人物身份、场景事实和剧情因果；保留全部明确台词及说话人，不重复或截断台词。"
                       + "允许按剧情换机位与切换场景，声音与画面连贯。"
                       + "直接交付最终视频附件。\n"
                       + (f"目标时长{duration}秒，完整保留剧情与对白。\n" if duration else "按剧情和自然对白安排完整时长。\n")
                       + ("视频顺序：\n" + "\n".join(f"{i+1}. {r['name']}" for i, r in enumerate(source_records)) + "\n" if videos else "")
                       + f"【用户完整原文】\n{prompt}\n请将本次最终视频作为一个附件返回，文件名 film_{production_id}.mp4。")
    # A bridge is one continuous shot. Sending scene here makes the gateway
    # prepend "Create the full film ... generating segments and assembling",
    # contradicting the bridge brief even when the CDTV request says otherwise.
    payload = {"model": model["modelName"], "prompt": instruction, "production_mode": 'shot' if mode == 'bridge' else mode,
               "images": images, "videos": videos, "ratio": body.get("ratio") or "16:9"}
    if duration:
        payload["duration"] = duration
    # One dispatch only: never strip the mode/videos or resubmit a paid request.
    try:
        result = handler._request_ai_json(model, endpoint, "Muse整场制作", payload, timeout=1800)
        task_id = str(result.get("id") or result.get("taskId") or result.get("task_id") or "")
        if not task_id:
            raise StorageError(502, "Muse整场请求未返回任务编号，请检查桥接记录，避免重复提交")
        cache_id = hashlib.sha256(f"{model['id']}:{task_id}".encode()).hexdigest()
        storage.save_document("ai_video_submissions", cache_id, {
            "productionMode": mode, "expectedDuration": duration, "isMuse": True,
            **({"assemblyPolicy": "dual-ended-bridges-v2", "bridgeContracts": contracts} if mode == "assemble" else {}),
            "projectId": str(body.get("project_id") or ""), "productionId": production_id,
            "sourceVideos": source_records, "referenceCount": len(images),
        }, expected_revision=None)
    except StorageError as exc:
        exc.native_dispatched = True
        raise
    return {**result, "taskId": task_id, "production_mode": mode}


def validate(handler, content, submission):
    target = float(submission.get("expectedDuration") or 0)
    # Decode and inspect the original output. Native films are never auto-trimmed.
    report = handler._validate_video_duration(content, target)
    actual = report.get("actualDuration")
    passed = bool(actual and actual > 0) and (not target or report["passed"])
    output_hash = hashlib.sha256(content).hexdigest()
    sources = submission.get("sourceVideos") or []
    if len(sources) > 1 and any(output_hash in {r.get("sha256"), r.get("uploadSha256")} for r in sources):
        passed = False
        report["reason"] = "组片结果与其中一段源视频完全相同，尚未得到完整组片"
    elif not passed:
        report["reason"] = f"目标{target:g}秒，实际{actual}秒，原始候选已保留" if actual else "无法解码整场视频，原始候选已保留"
    else:
        report["reason"] = ""
    return {**report, "passed": passed, "productionMode": submission["productionMode"],
            **({"continuityReview": {"status": "pending", "passed": None,
                "requiredEdges": ["source_to_bridge", "bridge_to_next_source"],
                "contracts": submission['bridgeContracts']}} if submission.get('bridgeContracts') else {}),
            "sha256": output_hash, "trimmed": False, "reviewStatus": "needs_review"}
