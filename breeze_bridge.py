"""Local Breeze dubbing. Generated reference clips stay in CDTV's own data folder."""
from pathlib import Path
import hashlib
import os
import json
import subprocess
import tempfile
import threading
import uuid
import wave

import httpx


def _default_breeze_root() -> Path:
    """Breeze 应用目录：优先 CDTV_TOOLS_ROOT，否则从源码目录向上查找 breeze-tts。"""
    configured = os.environ.get("CDTV_TOOLS_ROOT", "").strip()
    if configured:
        return Path(configured) / "breeze-tts"
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "breeze-tts").is_dir():
            return candidate / "breeze-tts"
    return Path("breeze-tts")


class BreezeBridge:
    def __init__(self, data_dir, upload, endpoint="http://127.0.0.1:18080", fetch=None, ffmpeg=None, tools=None):
        self.directory = Path(data_dir) / "breeze"
        self.upload = upload
        self.endpoint = endpoint
        self.jobs = {}
        self.lock = threading.Lock()
        self.generation_lock = threading.Lock()
        self.fetch, self.ffmpeg, self.tools = fetch, ffmpeg, tools
        self.alignment = None

    def _alignment(self, require_media=True):
        import importlib.util
        candidates = [
            Path(__file__).with_name("dubbing_alignment.py"),
            Path(__file__).parent / "dubbing_alignment.py",
            Path(__file__).parent / "_internal" / "dubbing_alignment.py",
        ]
        found = next((p for p in candidates if p.is_file()), None)
        if found:
            spec = importlib.util.spec_from_file_location("cdtv_dubbing_alignment", found)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.alignment = module
        elif self.alignment is None:
            try:
                import dubbing_alignment
                self.alignment = dubbing_alignment
            except Exception:
                raise RuntimeError("本地音轨组件缺失，请同步客户端文件")
        if require_media and (not self.ffmpeg or not self.fetch):
            raise ValueError("本地音轨组件尚未准备好")
        return self.alignment

    def align_begin(self, token, payload):
        contract = payload.get('contract') or {}
        if not contract.get('explicit') or not contract.get('lines'):
            raise ValueError("请先生成带有逐句台词的配音")
        self._alignment()
        job_id=uuid.uuid4().hex
        job={'id':job_id,'status':'running','message':'正在读取原视频声音…','cancel':threading.Event()}
        with self.lock:
            self.jobs[job_id]=job
        threading.Thread(target=self._align_run,args=(job,token,json.loads(json.dumps(payload))),daemon=True).start()
        return {'id':job_id}

    def _align_run(self, job, token, payload):
        try:
            module=self._alignment()
            with tempfile.TemporaryDirectory(prefix='cdtv-align-') as work:
                video=Path(work)/'original.mp4'
                self.fetch(token,payload['videoFileId'],video)
                duration=module.media_duration(self.ffmpeg,video)
                if duration>=179:
                    raise ValueError('单镜自动定位支持小于179秒的视频，请先拆分')
                self._update(job,message='正在定位原视频每句台词的起止时间…')
                try:
                    data=module.transcribe(self.ffmpeg,self.tools,video,work)
                    self._update(job,message='正在检查整句说话位置，排除喘息和脚步干扰…')
                    data=module.refine_single_line_window(self.ffmpeg,self.tools,video,work,payload['contract'],data,duration)
                    result=module.match_lines(payload['contract'],data,duration)
                except ValueError as exc:
                    result=module.match_lines(payload['contract'],{},duration)
                    result['warning']=str(exc)+'；可预览原视频并填写时间'
                if result['status']=='matched' and payload.get('timeline'):
                    try:
                        self._update(job,message='正在对齐句内停顿与后半句位置…')
                        speech=Path(work)/'speech.wav'
                        self.fetch(token,payload['audioFileId'],speech)
                        source=module.transcribe(self.ffmpeg,self.tools,speech,work)
                        module.attach_pause_plan(payload['contract'],result['rows'],data,source,payload['timeline'])
                        if any(r.get('pausePlanWarning') for r in result['rows']):
                            result['recognitionNote']='；'.join(filter(None,[result.get('recognitionNote'),
                                '整句已定位；部分句内停顿按配音自身节奏保留，不影响应用。']))
                    except ValueError as exc:
                        # Source-TTS recognition only refines internal pauses;
                        # never discard a confirmed original-video alignment.
                        result['pausePlanWarning']=str(exc)
                        result['recognitionNote']='；'.join(filter(None,[result.get('recognitionNote'),
                            '整句已定位，句内停顿精细分析未完成，将保留配音自身的自然停顿。']))
                if job['cancel'].is_set():raise InterruptedError('已停止原声定位')
                result.update({'videoFileId':payload['videoFileId'],'audioFileId':payload['audioFileId'],
                               'contract':payload['contract'],'videoDuration':duration,'alignmentVersion':5})
            self._update(job,status='completed',message='原声时间已定位' if result['status']=='matched' else '部分台词无法可靠定位，请校准时间',result=result)
        except InterruptedError as exc:self._update(job,status='cancelled',message=str(exc))
        except Exception as exc:self._update(job,status='failed',message=str(exc))

    def align_mix(self, token, payload):
        module=self._alignment()
        with tempfile.TemporaryDirectory(prefix='cdtv-aligned-mix-') as work:
            video,audio,output=Path(work)/'original.mp4',Path(work)/'speech.wav',Path(work)/'aligned-video.mp4'
            self.fetch(token,payload['videoFileId'],video)
            self.fetch(token,payload['audioFileId'],audio)
            if payload.get('mode') == 'voice-conversion':
                if payload.get('sourceVideoFileId') != payload['videoFileId']:
                    raise ValueError('原视频已更换，请重新生成跟随原声的配音')
                module.render_converted(self.ffmpeg,video,audio,payload['contract'],payload['rows'],output)
            else:
                module.render(self.ffmpeg,video,audio,payload['contract'],payload['timeline'],payload['rows'],output,work)
            uploaded=self.upload(token,str(output))
            if not uploaded.get('id'):raise ValueError('对齐视频未能保存，请重试')
            return {'id':str(uploaded['id']),'fileId':str(uploaded['id']),'loudnessVersion':1}

    def status(self, root=None):
        root = Path(root) if root else _default_breeze_root()
        installed = (root / "Breeze语音.exe").is_file()
        try:
            with httpx.Client(trust_env=False, timeout=3) as client:
                health = client.get(self.endpoint + "/health")
                health.raise_for_status()
                data = health.json()
                if data.get("status") != "ok" or int(data.get("sample_rate", 0)) <= 0:
                    raise ValueError("本地语音尚未准备好")
                voices = client.get(self.endpoint + "/v1/voices")
                voices.raise_for_status()
                voices = voices.json()
                if not isinstance(voices, list):
                    raise ValueError("声音库返回格式不正确")
            return {"ready": True, "installed": installed, "voices": [
                {"id": str(v["id"]), "description": str(v.get("description") or ""), "saved": bool(v.get("saved"))}
                for v in voices if isinstance(v, dict) and v.get("id") and v.get("saved")
            ], "message": "Breeze 已连接，语音在本机生成"}
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return {"ready": False, "installed": installed, "voices": [],
                    "message": "Breeze 尚未就绪，请启动后连接" if installed else "未找到 Breeze，请检查应用目录"}

    def start(self, root=None):
        root = Path(root) if root else _default_breeze_root()
        exe = root.resolve() / "Breeze语音.exe"
        if not exe.is_file():
            raise ValueError("未找到 Breeze语音.exe，请填写 Breeze 应用目录")
        if not self.status(root)["ready"]:
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
        return {"started": True}

    def begin(self, token, payload):
        contract = payload.get("contract") or {}
        lines, roles = contract.get("lines"), contract.get("roles") or []
        if not contract.get("explicit") or not isinstance(lines, list) or not lines:
            raise ValueError("请先填写带引号的逐字台词；无对白分镜无需生成配音")
        if len(lines) > 80 or sum(len(str(s)) for s in lines) > 8000:
            raise ValueError("单镜台词过长，请拆成多个分镜再配音")
        if not self.generation_lock.acquire(blocking=False):
            raise ValueError("已有本地配音正在生成，请等待完成")
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "status": "running", "completed": 0, "total": len(lines),
               "message": "正在连接 Breeze…", "cancel": threading.Event()}
        try:
            bindings = payload.get("bindings") or {}
            segments = []
            for index, text in enumerate(lines):
                role = str(roles[index] if index < len(roles) else "").strip() or "未标注角色"
                config = bindings.get(role) or {}
                instruction = str(config.get("instruction") or "普通话，清晰自然，语速适中。")[:1800]
                reference_instruction = instruction
                if payload.get('delivery') == 'natural-dialogue':
                    instruction += '。保持自然正常语速，吐字利落，不拖长字音；按标点自然停顿，力度与情绪遵循本句表演。'
                deliveries=contract.get('deliveries') or []
                if index<len(deliveries) and str(deliveries[index]).strip():
                    instruction += '。本句表演：'+str(deliveries[index]).strip()[:240]+'。保持角色音色，按此语气说出台词，不能朗读表演说明。'
                segments.append({"text": str(text), "role": role, "voice": str(config.get("voiceId") or ""),
                                 "instruction": instruction, "referenceInstruction": reference_instruction})
            with self.lock:
                # Keep only recent outcomes; running jobs never get evicted.
                for key in list(self.jobs)[:-15]:
                    if self.jobs[key]["status"] != "running":
                        self.jobs.pop(key, None)
                self.jobs[job_id] = job
            if payload.get('mode') == 'voice-conversion':
                self._alignment()
                threading.Thread(target=self._run_conversion, args=(job,token,json.loads(json.dumps(payload))),daemon=True).start()
            else:
                threading.Thread(target=self._run, args=(job, token, str(payload.get("projectKey") or "default"), segments), daemon=True).start()
        except Exception:
            self.generation_lock.release()
            raise
        return {"id": job_id}

    def _run_conversion(self, job, token, payload):
        """Experimental audio-to-audio voice change; never stretch a TTS take."""
        import array
        try:
            module=self._alignment()
            contract=payload['contract']
            with tempfile.TemporaryDirectory(prefix='cdtv-convert-') as work:
                work=Path(work);video=work/'original.mp4';reference=work/'reference.wav'
                self.fetch(token,payload['videoFileId'],video)
                self.fetch(token,payload['referenceAudioFileId'],reference)
                duration=module.media_duration(self.ffmpeg,video)
                if duration>=179:raise ValueError('单镜换音色支持小于179秒的视频')
                self._update(job,message='正在核对原视频台词与发声时间…')
                data=module.transcribe(self.ffmpeg,self.tools,video,work)
                alignment=module.match_lines(contract,data,duration)
                original_text=''.join(str(s.get('text') or '') for s in data.get('transcription',[]))
                expected_text=contract.get('text') or ''.join(contract['lines'])
                # If caller provided explicit rows (e.g. from user confirmation/adjustments), honor them
                provided_rows = payload.get('rows')
                if provided_rows and len(provided_rows) == len(contract['lines']):
                    alignment['rows'] = provided_rows
                # Ensure all rows have valid start/end
                for idx, row in enumerate(alignment['rows']):
                    if row.get('start') is None or row.get('end') is None or row.get('end') <= row.get('start'):
                        windows = data.get('speechWindows') or []
                        if windows:
                            row['start'] = float(windows[min(idx, len(windows)-1)]['start'])
                            row['end'] = float(windows[min(idx, len(windows)-1)]['end'])
                        else:
                            row['start'] = 0.0
                            row['end'] = duration
                    row['confirmed'] = True
                samples=module.read_pcm(self.ffmpeg,reference,work/'reference-pcm.wav')
                ranges=module.source_ranges(payload['referenceContract'],payload['referenceTimeline'],len(samples)/24000)
                track=array.array('h',[0])*int(round(duration*24000));timeline=[]
                with httpx.Client(trust_env=False,timeout=httpx.Timeout(600,connect=5)) as client:
                    for i,row in enumerate(alignment['rows']):
                        if job['cancel'].is_set():raise InterruptedError('已停止原声换音色')
                        role=row['role'] or '未标注角色'
                        reference_roles=payload['referenceContract'].get('roles') or []
                        reference_index=next((n for n,r in enumerate(reference_roles) if (r or '未标注角色')==role),None)
                        if reference_index is None:raise ValueError(f'缺少{role}的参考声音，请先生成角色配音')
                        left,right=ranges[reference_index]
                        source=work/f'source-{i}.wav';voice=work/f'voice-{i}.wav'
                        module.command([self.ffmpeg,'-v','error','-nostdin','-y','-i',video,'-af',f'atrim=start={row["start"]:.6f}:end={row["end"]:.6f},asetpts=PTS-STARTPTS','-ac','1','-ar','24000',source])
                        module.command([self.ffmpeg,'-v','error','-nostdin','-y','-i',reference,'-af',f'atrim=start={left:.6f}:end={right:.6f},asetpts=PTS-STARTPTS','-ac','1','-ar','24000',voice])
                        self._update(job,message=f'正在为{role}换音色，保留原片语速与停顿（{i+1}/{len(alignment["rows"])}）…')
                        with source.open('rb') as source_handle,voice.open('rb') as voice_handle:
                            response=client.post(self.endpoint+'/v1/audio/convert',data={'text':row['text'],
                                'ref_text':payload['referenceContract']['lines'][reference_index], 'temperature':'0.3','top_k':'1','keep_acoustic':'0','seed':'42'},
                                files={'source':('source.wav',source_handle,'audio/wav'),'ref_audio':('voice.wav',voice_handle,'audio/wav')})
                        if response.status_code==409:raise ValueError('Breeze 正忙，请等其他语音生成完成后再试')
                        response.raise_for_status()
                        if 'audio/pcm' not in response.headers.get('content-type','') or int(response.headers.get('x-sample-rate','0'))!=24000 or len(response.content)%2:
                            raise ValueError('换音色返回了无法识别的音频')
                        expected=int(round((row['end']-row['start'])*24000))
                        converted=array.array('h',response.content)
                        # The codec pads to 80ms frames. Only remove/pad its final
                        # fractional frame; never resample speech to fill a slot.
                        if not converted or abs(len(converted)-expected)>int(.16*24000):
                            raise ValueError('换音色没有保持原片时长，本次结果未采用')
                        offset=int(round(row['start']*24000));count=min(expected,len(converted),len(track)-offset)
                        track[offset:offset+count]=converted[:count]
                        timeline.append({'role':role,'text':row['text'],'start':row['start'],'duration':row['end']-row['start']})
                        self._update(job,completed=i+1)
                if job['cancel'].is_set():raise InterruptedError('已停止原声换音色')
                output=work/'original-rhythm-voice.wav'
                self._write_wave(output,24000,track.tobytes())
                self._update(job,message='正在检查换音色后的台词…')
                reviewed=module.transcribe(self.ffmpeg,self.tools,output,work)
                transcript=''.join(str(s.get('text') or '') for s in reviewed.get('transcription',[]))
                matched=module.normalize_words(transcript)==module.normalize_words(contract.get('text') or ''.join(contract['lines']))
                review={'status':'matched_text' if matched else 'needs_review','transcript':transcript,
                        'summary':'台词识别一致，仍请试听' if matched else '换音色后的识别台词有差异，请试听核对后再合入'}
                uploaded=self.upload(token,str(output));file_id=str(uploaded.get('id') or '')
                if not file_id:raise ValueError('换音色配音未能保存')
                alignment.update({'videoFileId':payload['videoFileId'],'audioFileId':file_id,'contract':contract,'videoDuration':duration,'mode':'voice-conversion'})
            self._update(job,status='completed',message='原声换音色已完成，语速保持原片节奏',result={'fileId':file_id,
                'duration':duration,'timeline':timeline,'mode':'voice-conversion','sourceVideoFileId':payload['videoFileId'],'alignment':alignment,'review':review})
        except InterruptedError as exc:self._update(job,status='cancelled',message=str(exc))
        except Exception as exc:self._update(job,status='failed',message=str(exc))
        finally:self.generation_lock.release()

    def job(self, job_id):
        with self.lock:
            job = self.jobs.get(str(job_id))
            if not job:
                raise ValueError("配音任务不存在，请重新生成")
            return {k: v for k, v in job.items() if k != "cancel"}

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(str(job_id))
            if job and job["status"] == "running":
                job["cancel"].set()
        return {"cancelled": True}

    def _update(self, job, **values):
        with self.lock:
            job.update(values)

    def _speech(self, client, segment, anchor, job, project_key=""):
        # Ensure project-wide role voice reproducibility and consistency across all shots
        norm_role = "旁白" if segment["role"] in ("旁白", "画外音", "解说", "解说词", "内心独白") else segment["role"]
        identity = (project_key or "default") + "\0" + norm_role
        seed = int(hashlib.sha256(identity.encode()).hexdigest()[:7], 16)
        fields = {"text": segment["text"], "instruction": segment["instruction"], "seed": str(seed), "split_chars": "200"}
        files = None
        reference = None
        if segment["voice"]:
            fields["voice_id"] = segment["voice"]
        elif anchor.with_suffix(".json").is_file() and anchor.is_file():
            meta = json.loads(anchor.with_suffix(".json").read_text(encoding="utf8"))
            fields["ref_text"] = meta["text"]
            reference = anchor.open("rb")
            files = {"ref_audio": ("reference.wav", reference, "audio/wav")}
        try:
            # Native endpoint returns headerless s16le PCM; never treat it as a WAV.
            with client.stream("POST", self.endpoint + "/v1/audio/speech", data=fields, files=files) as response:
                if response.status_code == 409:
                    raise ValueError("Breeze 正在处理其他语音，请等它完成后再试")
                if response.status_code == 404:
                    raise ValueError("所选声音已不在 Breeze 声音库中，请刷新并重新选择")
                response.raise_for_status()
                if "audio/pcm" not in response.headers.get("content-type", ""):
                    raise ValueError("Breeze 返回了无法识别的音频格式")
                rate = int(response.headers.get("x-sample-rate", "24000"))
                if not 8000 <= rate <= 192000:
                    raise ValueError("Breeze 音频采样率无效")
                data = bytearray()
                for block in response.iter_bytes():
                    if job["cancel"].is_set():
                        raise InterruptedError("已停止本次配音")
                    data.extend(block)
                    if len(data) > rate * 2 * 180:
                        raise ValueError("单句音频超过三分钟，请拆分台词")
                if len(data) < rate // 5 or len(data) % 2:
                    raise ValueError("Breeze 返回的音频不完整，请重试")
                return rate, bytes(data)
        finally:
            if reference:
                reference.close()

    @staticmethod
    def _write_wave(path, rate, data):
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(data)

    def _run(self, job, token, project_key, segments):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            reference_dir = self.directory / "role-references"
            reference_dir.mkdir(exist_ok=True)
            audio = bytearray()
            sample_rate = None
            timeline = []
            with httpx.Client(trust_env=False, timeout=httpx.Timeout(600, connect=5)) as client:
                for index, segment in enumerate(segments):
                    if job["cancel"].is_set():
                        raise InterruptedError("已停止本次配音")
                    self._update(job, message=f"正在生成 {segment['role']} 的第 {index + 1}/{len(segments)} 句…")
                    norm_role = "旁白" if segment["role"] in ("旁白", "画外音", "解说", "解说词", "内心独白") else segment["role"]
                    key = hashlib.sha256((project_key + "\0" + norm_role).encode()).hexdigest()
                    anchor = reference_dir / (key + ".wav")
                    rate, pcm = self._speech(client, segment, anchor, job, project_key=project_key)
                    if sample_rate is not None and sample_rate != rate:
                        raise ValueError("Breeze 在生成期间切换了采样率，请重新生成")
                    sample_rate = rate
                    reference_pcm = pcm
                    pcm, level = self._alignment(require_media=False).normalize_speech_pcm(pcm, rate)
                    if index:
                        audio.extend(b"\0\0" * int(rate * .18))
                    timeline.append({"role": segment["role"], "text": segment["text"],
                                     "start": len(audio) / (rate * 2), "duration": len(pcm) / (rate * 2), "loudness": level})
                    audio.extend(pcm)
                    if not segment["voice"] and not anchor.exists():
                        self._write_wave(anchor, rate, reference_pcm)
                        anchor.with_suffix(".json").write_text(json.dumps({"text": segment["text"]}, ensure_ascii=False), encoding="utf8")
                    self._update(job, completed=index + 1)
            if job["cancel"].is_set():
                raise InterruptedError("已停止本次配音")
            self._update(job, message="台词生成完成，正在保存配音…")
            with tempfile.TemporaryDirectory(prefix="cdtv-breeze-") as work:
                output = Path(work) / "breeze-dubbing.wav"
                self._write_wave(output, sample_rate, audio)
                uploaded = self.upload(token, str(output))
            file_id = str(uploaded.get("id") or uploaded.get("fileId") or "")
            if not file_id:
                raise ValueError("配音保存未返回文件，请重新生成")
            self._update(job, status="completed", message="本地配音已生成", result={"fileId": file_id,
                         "duration": len(audio) / (sample_rate * 2), "timeline": timeline, "loudnessVersion":1})
        except InterruptedError as exc:
            self._update(job, status="cancelled", message=str(exc))
        except Exception as exc:
            message = "Breeze 连接中断，请确认应用已启动并等待模型加载完成" if isinstance(exc, httpx.HTTPError) else str(exc)
            self._update(job, status="failed", message=message)
        finally:
            self.generation_lock.release()
