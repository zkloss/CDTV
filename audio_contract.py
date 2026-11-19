"""Muse dialogue contracts and offline transcript review for the CDTV desktop app.

The review checks recognized words, not voice identity, acting quality or lip sync.
"""
from __future__ import annotations

import ctypes
import difflib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import unicodedata

REVIEW_VERSION = 1
_REVIEW_LOCK = threading.Lock()

NON_DIALOGUE_PREFIXES = (
    '一致性引用', '接线单', '画面', '运镜', '景别', '提示词', '音频提示词', '音频', '声音',
    '环境音', '环境声', '音效', 'bgm', '背景音乐', '动作', '时间', '天气', '场景', '时空',
    '转场', '剪辑', '拍摄约束', '约束', '红线', '【时空与天气连续性】', '【自动转场安排',
    '【剪辑交接', '【00:', '【本镜动作】', '【时地背景】'
)

_EXPLICIT_DIALOGUE_LABEL = re.compile(
    r'^\s*(?:【\s*(对白|台词|画外音|旁白|内心独白|独白|解说|解说词|vo|os)\s*】|(对白|台词|画外音|旁白|内心独白|独白|解说|解说词|vo|os))\s*[：:]\s*(.*)$',
    re.I
)
_NONE = re.compile(r"^(?:无|无对白|无台词|无旁白|无画外音|无内心独白|none|silence)(?=$|[。.!！\s，,；;])", re.I)
_CHAR_SPEECH = re.compile(
    r'^\s*([^\s（(：:【】“"「『]{1,15})\s*(?:[（(]([^）)]+)[）)])?\s*[：:]\s*([“"「『‘\'].+[”"」』’\'])\s*$'
)


def stable_voice_prompt(value: str) -> str:
    text = str(value or '').replace('清晰紧张质地', '清晰自然质地')
    return '，'.join(s.strip() for s in re.split(r'[+，；;]', text)
                    if s.strip() and not re.search(r'喘息|气喘|粗重呼吸|带颤音|急促|嘶吼|哭腔|低微呼吸|苍老低微', s))


def collect_audio_prompts(audios: list, reference_ids: list, text: str) -> list[str]:
    characters = [str(cid) for cid in reference_ids if str(cid).startswith('char_')]
    prompts = []
    for asset in audios:
        aid = str(asset.get('id') or '')
        voice = asset.get('category') == 'voice' or aid.startswith('aud_vo_')
        matched = any(aid == 'aud_vo_' + cid[5:] for cid in characters) if voice else any(
            token in aid and re.search(pattern, text) for token, pattern in [
                ('door', r'撞开|木门|门板'), ('footstep', r'狂奔|脚步|冲刺'),
                ('breath', r'喘息|气喘'), ('kowtow', r'磕头|双膝跪地')])
        if not matched:
            continue
        if aid not in reference_ids:
            reference_ids.append(aid)
        prompt = stable_voice_prompt(asset.get('prompt')) if voice else str(asset.get('prompt') or '').strip()
        if prompt and prompt not in prompts:
            prompts.append(prompt)
    return prompts


def normalize_words(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text)).lower()
    if os.name == "nt":
        # Windows performs the same traditional/simplified normalization locally.
        fn = ctypes.windll.kernel32.LCMapStringEx
        fn.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_int,
                       ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_ssize_t]
        fn.restype = ctypes.c_int
        size = fn("zh-CN", 0x02000000, value, -1, None, 0, None, None, 0)
        if size:
            buf = ctypes.create_unicode_buffer(size)
            if fn("zh-CN", 0x02000000, value, -1, buf, size, None, None, 0):
                value = buf.value
    value = value.replace('麽', '么')
    return re.sub(r"[^\w\u3400-\u9fff]", "", value, flags=re.UNICODE).replace("_", "")


STANDARD_VOICE_PRESETS = [
    {
        "id": "narrator_epic",
        "label": "🎙️ 雄浑厚重旁白",
        "text": "成熟男性，男低音，声音雄浑厚重，低沉磁性，胸腔共鸣充沛，语气庄重沉稳、富有史诗叙事感，语速舒缓从容，字字千钧，吐字清晰有力，普通话标准。"
    },
    {
        "id": "narrator_weathered",
        "label": "📜 沧桑史诗旁白",
        "text": "成熟男性，男低音，声音雄浑厚重，低沉磁性带岁月沧桑颗粒感，胸腔共鸣扎实，声线沉稳大气，富有史诗叙事厚重感，吐字清晰沉着，语速舒缓从容，普通话标准。"
    },
    {
        "id": "narrator_powerful",
        "label": "👑 霸气掷地有声",
        "text": "壮年男性，男中低音，声音雄浑厚重、刚劲有力，胸腔共鸣充沛，声线霸气威严、掷地有声，中气十足，字字铿锵，富有号召力与穿透力，普通话标准。"
    },
    {
        "id": "narrator_solemn",
        "label": "⚖️ 庄严肃穆旁白",
        "text": "成熟男性，男低音，声音雄浑厚重，庄严肃穆，胸腔共鸣稳固，声线冷峻深沉，语速从容沉着，字字千钧，吐字清晰有力，普通话标准。"
    },
    {
        "id": "male_hero",
        "label": "⚔️ 坚毅热血男主",
        "text": "青年男性，约20岁，清亮有韧性的青年正音，音质清澈坚毅，低频微带磁性，声线刚强不屈、热血坚定，咬字干脆利落，气息稳定，普通话标准。"
    },
    {
        "id": "male_villain",
        "label": "🦹 傲慢轻蔑反派",
        "text": "青年男性，反派男音，声线轻慢刺耳带嘲弄不屑感，语调居高临下扬高，带有冷笑质感，咬字尖锐，普通话标准。"
    },
    {
        "id": "male_elder",
        "label": "👴 沉稳沧桑老者",
        "text": "资深老者，老年男性，低沉浑厚略带沙哑苍老，胸腔共鸣温厚，语气从容深邃，充满岁月阅历感，语速舒缓沉稳，普通话标准。"
    },
    {
        "id": "female_gentle",
        "label": "🌸 温婉清澈女主",
        "text": "年轻女性，声音温柔甜美治愈，声线清澈温润，呼吸自然轻盈，语气亲切舒缓，富有感染力，普通话标准。"
    },
    {
        "id": "weak_character",
        "label": "🍂 虚弱重伤少年",
        "text": "少年男性，声音虚弱微颤，略带沙哑气音，语气无助微弱，呼吸声微促，轻声细语，普通话标准。"
    },
]

_PRESET_MAP = {p["id"]: p["text"] for p in STANDARD_VOICE_PRESETS}


def extract_role_voice_instruction(prompt: str, role: str, delivery: str = "") -> str:
    prompt_str = str(prompt or "")
    deliv_str = str(delivery or "")

    if role in ("旁白", "画外音", "解说", "解说词", "内心独白", "vo", "os", "VO", "OS"):
        combined = f"{prompt_str} {deliv_str}"
        if re.search(r"掷地有声|霸气|强力|震撼|爆发", combined):
            return _PRESET_MAP["narrator_powerful"]
        if re.search(r"肃穆|庄重|冷峻|压迫", combined):
            return _PRESET_MAP["narrator_solemn"]
        if re.search(r"沧桑|沙哑|岁月|远古|三千年|悲壮", combined):
            return _PRESET_MAP["narrator_weathered"]
        return _PRESET_MAP["narrator_epic"]

    combined_info = f"{role} {deliv_str} {prompt_str}"
    if re.search(r"老人|老者|老头|师尊|师父|掌门|爷爷|六十|七十|陈守一", combined_info):
        return _PRESET_MAP["male_elder"]
    if re.search(r"弟子|反派|恶徒|狗腿|嘲讽|嫌恶|不屑|傲慢|冷笑", combined_info):
        return _PRESET_MAP["male_villain"]
    if re.search(r"乞丐|虚弱|重伤|濒死|微弱|有毒|颤抖|求救", combined_info):
        return _PRESET_MAP["weak_character"]
    if re.search(r"女|少女|师妹|师姐|仙子|苏兰|小妹|姑娘", combined_info):
        return _PRESET_MAP["female_gentle"]
    if re.search(r"林北|林枫|男主|少侠|少年|青年", combined_info):
        return _PRESET_MAP["male_hero"]

    return _PRESET_MAP["narrator_epic"]


def dialogue_contract(prompt: str) -> dict:
    lines, roles, deliveries, errors = [], [], [], []
    seen_blocks: set[tuple] = set()
    explicit_none = False

    for raw in str(prompt or '').splitlines():
        line = raw.strip()
        if not line:
            continue

        if any(line.startswith(p) for p in NON_DIALOGUE_PREFIXES):
            continue

        label_m = _EXPLICIT_DIALOGUE_LABEL.match(line)
        char_m = None
        default_role = ''
        body = ''

        if label_m:
            lbl = (label_m.group(1) or label_m.group(2) or '').lower()
            if lbl in ('旁白', '画外音', '内心独白', '独白', '解说', '解说词', 'vo', 'os'):
                default_role = '旁白' if lbl in ('旁白', 'vo', 'os', '画外音', '解说', '解说词') else '内心独白'
            body = label_m.group(3).strip()
            if _NONE.match(body):
                explicit_none = True
                continue
        else:
            char_m = _CHAR_SPEECH.match(line)
            if char_m:
                cand_role = char_m.group(1).strip()
                default_role = '旁白' if cand_role in ('旁白', '画外音', '独白', '解说') else cand_role
                body = line

        if not label_m and not char_m:
            continue

        quote_matches = list(re.finditer(r'[“"]([^”"]+)[”"]|[「]([^」]+)[」]|[『]([^』]+)[』]', body))
        block = []

        if quote_matches:
            prev_end = 0
            for q in quote_matches:
                text = q.group(1) or q.group(2) or q.group(3) or ''
                prefix = body[prev_end:q.start()].strip('；;，, ：:【】〖〗\t')
                role = re.sub(r'[（(][^）)]*[）)]', '', prefix).strip(' ：:')
                if not role or role in ('对白', '台词'):
                    role = default_role or '旁白'
                delivery_m = re.findall(r'[（(]([^）)]+)[）)]', prefix)
                delivery = '，'.join(d.strip() for d in delivery_m if d.strip())
                block.append((role, text.strip(), delivery))
                prev_end = q.end()
        else:
            colon_m = re.match(r'^(?:([^：:（(\s]{1,15})\s*(?:[（(]([^）)]+)[）)])?\s*[：:])?\s*(.+)$', body)
            if colon_m and colon_m.group(3) and colon_m.group(3).strip():
                extracted_role = colon_m.group(1) or default_role or '旁白'
                if extracted_role in ('对白', '台词'):
                    extracted_role = default_role or '旁白'
                extracted_delivery = (colon_m.group(2) or '').strip()
                extracted_text = colon_m.group(3).strip().strip('“"「『‘\'”"」』’\'')
                if extracted_text and not _NONE.match(extracted_text):
                    block.append((extracted_role, extracted_text, extracted_delivery))

        signature = tuple((b[0], b[1]) for b in block)
        if signature in seen_blocks:
            continue
        seen_blocks.add(signature)

        for b in block:
            roles.append(b[0])
            lines.append(b[1])
            deliveries.append(b[2])

    if explicit_none and lines:
        errors.append("无对白与有台词要求冲突，请保留一种")
    return {"version": REVIEW_VERSION, "lines": lines, "roles": roles, "deliveries": deliveries,
            "explicit": bool(lines) or explicit_none, "errors": errors, "text": "\n".join(lines)}


def compare_contracts(baseline: dict, candidate: dict) -> None:
    """Reject omissions, additions, changes, repetition and reordered dialogue."""
    if not baseline.get("explicit") or not candidate.get("explicit"):
        raise ValueError("台词基准未明确，请确认本镜对白或‘对白：无。’")
    before = [normalize_words(s) for s in baseline.get("lines", [])]
    after = [normalize_words(s) for s in candidate.get("lines", [])]
    if before != after:
        raise ValueError("当前台词与已确认基准不同（可能新增、遗漏、重复或改写）；请核对后点击‘确认当前台词’")
    if baseline.get('roles') is not None and baseline.get('roles') != candidate.get('roles'):
        raise ValueError("台词说话人与已确认基准不同，请核对后重新确认")


def prepare_muse_prompt(prompt: str, baseline: dict | None = None) -> tuple[str, dict]:
    contract = dialogue_contract(prompt)
    if contract["errors"]:
        raise ValueError("；".join(contract["errors"]))
    if baseline is not None:
        compare_contracts(baseline, contract)
    # JSON/special model tokens are deliberately not used: Muse receives plain text.
    if contract["lines"]:
        rule = ("本镜人声严格按上方对白、旁白和独白逐字一次说完，保持角色对应关系。"
                "只使用本镜列出的台词，不扩写，不重复上一镜台词。按逐句语气自然连贯发声，"
                "喘息只在本镜明确要求的动作间隙出现，不贯穿整句。")
    else:
        rule = "本镜人声内容为空。角色闭口完成动作，声音只包含本镜写明的环境声和动作拟音。"
    return str(prompt).strip() + "\n【本镜声音执行】" + rule, contract


def compare_transcript(contract: dict, transcript: str) -> dict:
    expected = str(contract.get("text") or "\n".join(contract.get("lines", [])))
    left, right = normalize_words(expected), normalize_words(transcript)
    explicit = bool(contract.get("explicit"))
    equal = explicit and left == right
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    similarity = matcher.ratio() if left or right else 0.0
    changes, matched = [], set()
    for tag, i, j, k, m in matcher.get_opcodes():
        if tag != "equal":
            changes.append({"kind": tag, "expected": left[i:j], "recognized": right[k:m]})
        else:
            matched.update(range(i, j))
    # The bundled small model regularly hears 主任 as 主人 and 一炉 as 一路.
    # A whole missing line still matters, so check each line's coverage.
    coverage, cursor = [], 0
    for line in contract.get("lines", []):
        word = normalize_words(line)
        coverage.append(round(sum(1 for i in range(cursor, cursor+len(word)) if i in matched)/max(len(word), 1), 3))
        cursor += len(word)
    # Treat near-equal recognition as a reference result, not a failed line.
    close = bool(explicit and left and not equal and similarity >= .7 and coverage and min(coverage) >= .6)
    if equal:
        status, summary = "matched_text", "台词文字一致，仍需试听"
    elif close:
        status, summary = "close_text", "本地识别与基准基本一致，个别同音字有差异，仍需试听核对"
    elif not explicit:
        status, summary = "needs_review", "台词基准尚未确认，请先核对本镜对白"
    else:
        status, summary = "needs_review", "本地识别与基准差异较大，可能漏字、多字或识别误差，请试听核对"
    return {"version": REVIEW_VERSION, "status": status,
            "expected": expected, "transcript": transcript, "differences": changes,
            "similarity": round(similarity, 3), "lineCoverage": coverage, "summary": summary,
            "limitation": "本地语音识别会把同音字听错；本检查只比较文字，仍需试听确认音色、表演和口型。"}


def review_video(video: Path, contract: dict, ffmpeg: Path, tools: Path) -> dict:
    cli, model = tools / "whisper-cli.exe", tools / "ggml-small-q5_1.bin"
    if not all(p.is_file() for p in (cli, model, ffmpeg)):
        return {"status": "unavailable", "summary": "本地语音检查组件缺失，尚未核验"}
    if not contract.get("explicit"):
        return {"status": "needs_spec", "summary": "请先确认当前台词或无对白，再核验"}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # Serialize local CPU work, and leave the UI/video generation available.
    if not _REVIEW_LOCK.acquire(timeout=600):
        return {"status": "unavailable", "summary": "本地语音检查繁忙，请稍后重试"}
    try:
        with tempfile.TemporaryDirectory(prefix="cdtv-audio-review-") as work:
            wav, output = Path(work) / "audio.wav", Path(work) / "transcript"
            result = subprocess.run([str(ffmpeg), "-v", "error", "-y", "-i", str(video),
                                     "-t", "180", "-vn", "-ac", "1", "-ar", "16000",
                                     "-c:a", "pcm_s16le", str(wav)],
                                    capture_output=True, creationflags=flags, timeout=90)
            if result.returncode:
                return {"status": "unavailable", "summary": "无法读取音轨，尚未核验（可能没有音轨）"}
            # A 3-minute guard prevents accidental partial reviews being reported as passes.
            import wave
            with wave.open(str(wav)) as source:
                duration = source.getnframes() / source.getframerate()
            if duration >= 179:
                return {"status": "unavailable", "summary": "视频过长，本地单镜检查只支持小于179秒"}
            result = subprocess.run([str(cli), "-m", str(model), "-f", str(wav), "-l", "zh",
                                     "-t", "4", "-nf", "-oj", "-of", str(output)],
                                    capture_output=True, creationflags=flags, timeout=480)
            path = output.with_suffix(".json")
            if result.returncode or not path.is_file():
                return {"status": "unavailable", "summary": "本地语音识别未完成，尚未核验"}
            data = json.loads(path.read_text(encoding="utf-8"))
            transcript = " ".join(str(s.get("text") or "") for s in data.get("transcription", []))
            report = compare_transcript(contract, transcript.strip())
            report["engine"] = "whisper.cpp small-q5_1 / 本地离线"
            return report
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "summary": "语音检查失败或超时，尚未核验，可重试"}
    finally:
        _REVIEW_LOCK.release()
