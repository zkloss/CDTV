"""Match dialogue to the original soundtrack and render replacement speech in place.

Transcript order supplies role labels; recognition does not identify faces or speakers.
Uncertain matches require explicit timing edits rather than falling back to time zero.
"""
from pathlib import Path
import array
import difflib
import json
import math
import re
import subprocess
import tempfile
import threading
import wave

from audio_contract import normalize_words

_ASR_LOCK = threading.Lock()

# Bounded recognition confusions, used only after an independent, unprompted
# decode of a single short acoustic window. Never a global text substitution.
_SHORT_HOMOPHONES = ('穿川船', '在再', '的地得', '他她它', '吗嘛', '做作', '里理', '到道', '又右', '声生', '你妳', '着著')


def short_homophone_agreement(wanted, recognized):
    wanted, recognized = normalize_words(wanted), normalize_words(recognized)
    if not 4 <= len(wanted) <= 12 or len(wanted) != len(recognized):
        return False
    changes = [(a,b) for a,b in zip(wanted,recognized) if a != b]
    if not changes or len(changes) > 2 or len(changes) > len(wanted)/2:
        return False
    groups = [next((group for group in _SHORT_HOMOPHONES if a in group and b in group), None) for a,b in changes]
    return all(groups) and len(set(groups)) == 1


def command(args, timeout=180):
    result = subprocess.run([str(a) for a in args], capture_output=True, timeout=timeout,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ValueError("音轨处理未完成，请检查媒体文件后重试")
    return result


def media_duration(ffmpeg, path):
    result = subprocess.run([str(ffmpeg), "-hide_banner", "-i", str(path)], capture_output=True,
                            timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr.decode("utf8", errors="replace"))
    if not match:
        raise ValueError("无法读取原视频时长")
    return int(match[1])*3600 + int(match[2])*60 + float(match[3])


def transcribe(ffmpeg, tools, media, work):
    cli, model = Path(tools)/"whisper-cli.exe", Path(tools)/"ggml-small-q5_1.bin"
    vad = Path(tools)/"ggml-silero-v6.2.0.bin"
    if not cli.is_file() or not model.is_file() or not vad.is_file():
        raise ValueError("本地台词定位组件缺失，请同步完整客户端")
    wav, output = Path(work)/"recognize.wav", Path(work)/"recognize"
    command([ffmpeg, "-v", "error", "-nostdin", "-y", "-i", media, "-t", "179", "-vn", "-ac", "1", "-ar", "16000", wav])
    with _ASR_LOCK:
        result = command([cli, "-m", model, "-f", wav, "-l", "zh", "-t", "4", "-nf", "--vad", "-vm", vad,
                          "-vt", "0.25", "-vspd", "80", "-vsd", "600", "-vp", "60", "-ojf", "-of", output], timeout=480)
    data = json.loads(output.with_suffix(".json").read_text(encoding="utf8"))
    # This bundled whisper.cpp maps segment timestamps to the original file,
    # but writes token offsets on its silence-compressed VAD clock. Restore the
    # token clock from its own exact mapping; otherwise silence shifts speech to 0.
    log = (result.stderr + result.stdout).decode('utf8',errors='replace')
    mappings = [tuple(map(float,m)) for m in re.findall(
        r'vad_segment_info: orig_start: ([\d.]+), orig_end: ([\d.]+), vad_start: ([\d.]+), vad_end: ([\d.]+)',log)]
    if not mappings:
        return {'transcription': []}
    def original_time(value):
        for i,(left,right,start,end) in enumerate(mappings):
            if value<=end:
                if value<start and i:
                    previous=mappings[i-1]
                    ratio=(value-previous[3])/max(start-previous[3],.001)
                    return previous[1]+max(0,min(1,ratio))*(left-previous[1])
                return max(left,min(right,left+value-start))
        return mappings[-1][1]
    tokens=[t for s in data.get('transcription',[]) for t in s.get('tokens',[]) if not str(t.get('text','')).startswith('[_')]
    maximum=max((float(t.get('offsets',{}).get('to',0))/1000 for t in tokens),default=0)
    compressed=maximum<=mappings[-1][3]+.3 and mappings[-1][1]-mappings[-1][3]>.2
    if compressed:
        for token in tokens:
            offsets=token.get('offsets') or {}
            token['offsets']={key:round(original_time(float(offsets.get(key,0))/1000)*1000) for key in ('from','to')}
    data['speechWindows']=[{'start':m[0],'end':m[1]} for m in mappings]
    return data


def refine_single_line_window(ffmpeg, tools, media, work, contract, data, duration):
    """Check a complete spoken phrase locally before trusting a tiny VAD burst.

    A grunt/footstep ahead of dialogue must not receive the first two words of a
    sentence merely because the global recognizer maps words across that burst.
    """
    lines = contract.get('lines') or []
    windows = data.get('speechWindows') or []
    if len(lines) != 1:
        return data
    wanted = normalize_words(lines[0])
    short_retry = (4 <= len(wanted) <= 12 and len(windows) == 1
                   and match_lines(contract, data, duration)['status'] != 'matched')
    burst_retry = len(wanted) >= 5 and len(windows) >= 2 and any(w['end']-w['start'] < .5 for w in windows)
    if not short_retry and not burst_retry:
        return data
    candidates = []
    for index, window in enumerate(windows):
        if window['end']-window['start'] < max(.5, len(wanted)*.045):
            continue
        left = max(0, window['start']-.12)
        right = min(duration, window['end']+.25)
        wav, output = Path(work)/f'phrase-{index}.wav', Path(work)/f'phrase-{index}'
        command([ffmpeg,'-v','error','-nostdin','-y','-ss',left,'-i',media,'-t',right-left,
                 '-vn','-ac','1','-ar','16000',wav])
        with _ASR_LOCK:
            command([Path(tools)/'whisper-cli.exe','-m',Path(tools)/'ggml-small-q5_1.bin',
                     '-f',wav,'-l','zh','-t','4','-nf','-ojf','-of',output],timeout=180)
        local = json.loads(output.with_suffix('.json').read_text(encoding='utf8'))
        text = ''.join(str(segment.get('text') or '') for segment in local.get('transcription',[]))
        recognized = normalize_words(text)
        similarity = difflib.SequenceMatcher(None,wanted,recognized,autojunk=False).ratio()
        homophone = (short_retry and window['end']-window['start'] <= max(4, len(wanted)*.65)
                     and short_homophone_agreement(wanted, recognized))
        # Preserve repeated opening words (e.g. "I... I wasn't..."). A later
        # phrase lacking that opening cannot swallow the preceding speech burst.
        if not homophone and (similarity < .8 or not recognized.startswith(wanted[:3])):
            continue
        for segment in local.get('transcription',[]):
            for item in [segment, *(segment.get('tokens') or [])]:
                offsets = item.get('offsets') or {}
                item['offsets'] = {key: round(float(offsets.get(key,0))+left*1000) for key in ('from','to')}
        local['speechWindows'] = [{'start':window['start'], 'end':min(duration,window['end']+.12)}]
        local['verifiedPhraseWindow'] = True
        local['phraseSimilarity'] = similarity
        if homophone:
            local['verifiedShortHomophones'] = True
            local['recognitionNote'] = '已对单一发声片段独立复核，识别文本含常见同音字'
        candidates.append(local)
    # More than one plausible utterance remains ambiguous; do not pick one at random.
    return candidates[0] if len(candidates)==1 else data


def timed_characters(data):
    characters = []
    for segment in data.get("transcription", []):
        tokens = segment.get("tokens") or [segment]
        for token in tokens:
            text = str(token.get("text") or "")
            if text.startswith("[_") or text.startswith("<|"):
                continue
            offsets = token.get("offsets") or {}
            start, end = float(offsets.get("from", 0))/1000, float(offsets.get("to", 0))/1000
            word = normalize_words(text)
            if not word:
                # Trailing punctuation carries the end of the final syllable too.
                if characters and re.search(r"[?!！？。…]", text) and start <= characters[-1]["end"]+.5:
                    characters[-1]["end"] = max(characters[-1]["end"], end)
                continue
            for i, char in enumerate(word):
                characters.append({"char": char, "start": start+(end-start)*i/len(word),
                                   "end": start+(end-start)*(i+1)/len(word)})
    return characters


def ordered_fallback(contract, data, duration, wanted, recognized, mapping, chars):
    """Place known lines by dialogue order when ASR mishears a character or two.

    The small bundled model hears 主任/主人 and 一炉/一路 alike. Exact text gates
    would leave such lines unplaced and block dubbing. Order is reliable because
    the shot prompt already fixes who speaks when; require enough text overlap
    to prove the audio is this shot's dialogue.
    """
    lines, windows = contract.get('lines') or [], data.get('speechWindows') or []
    if not lines or not chars or len(recognized) < 2:
        return None
    words = [normalize_words(line) for line in lines]
    overall = difflib.SequenceMatcher(None, wanted, recognized, autojunk=False).ratio()
    window_mode = len(windows) >= len(lines) and (overall >= .25 or (len(lines) == 1 and overall >= .15))
    if not window_mode and overall < .45:
        return None
    rows, cursor, previous_end = [], 0, 0
    for index, (line, word) in enumerate(zip(lines, words)):
        matched = [mapping[i] for i in range(cursor, cursor+len(word)) if i in mapping]
        confidence = len(matched)/max(len(word), 1)
        start = end = None
        if window_mode:
            start = float(windows[index]['start'])
            end = float(windows[index]['end'] if index < len(lines)-1 else windows[-1]['end'])
            confidence = max(confidence, .5)
        elif matched:
            start, end = chars[matched[0]]['start'], chars[matched[-1]]['end']
            if windows:
                first = next((w for w in windows if w['end'] >= start), None)
                last = next((w for w in reversed(windows) if w['start'] <= end), None)
                if first and start-float(first['start']) <= .8: start = float(first['start'])
                if last and float(last['end'])-end <= .8: end = float(last['end'])
        elif index == 0 and windows:
            start, confidence = float(windows[0]['start']), .5
        elif index == len(lines)-1 and windows:
            end, confidence = float(windows[-1]['end']), .5
        else:
            return None
        rows.append({'index': index,
                     'role': (contract.get('roles') or [])[index] if index < len(contract.get('roles') or []) else '未标注角色',
                     'text': line, 'start': start, 'end': end, 'confidence': round(confidence, 3),
                     'confirmed': False, 'method': 'order'})
        cursor += len(word)
    for index, row in enumerate(rows):
        if row['start'] is None:
            previous = rows[index-1]['end'] if index else None
            if previous is None: return None
            row['start'] = previous
        if row['end'] is None:
            following = rows[index+1]['start'] if index+1 < len(rows) else None
            if following is None: return None
            row['end'] = following
        if not math.isfinite(row['start']) or not math.isfinite(row['end']): return None
        row['start'] = round(max(0.0, min(duration, row['start'])), 3)
        row['end'] = round(max(0.0, min(duration, row['end'])), 3)
        if row['end']-row['start'] < .12 or row['start'] < previous_end-.05: return None
        row['confirmed'] = True
        previous_end = row['end']
    return rows


def match_lines(contract, data, duration):
    chars = timed_characters(data)
    recognized = ''.join(c['char'] for c in chars)
    lines = contract.get("lines") or []
    wanted = ''.join(normalize_words(line) for line in lines)
    verified_homophones = (len(lines) == 1 and data.get('verifiedPhraseWindow')
                           and data.get('verifiedShortHomophones')
                           and len(data.get('speechWindows') or []) == 1
                           and short_homophone_agreement(wanted, recognized))
    mapping = {}
    if verified_homophones:
        mapping = {i:i for i in range(len(wanted))}
    else:
        for block in difflib.SequenceMatcher(None, wanted, recognized, autojunk=False).get_matching_blocks():
            mapping.update({block.a+i:block.b+i for i in range(block.size)})
    rows, cursor = [], 0
    overall = len(mapping)/max(len(wanted), len(recognized), 1)
    previous_end = 0
    for index, line in enumerate(lines):
        word = normalize_words(line)
        matched = [mapping[i] for i in range(cursor, cursor+len(word)) if i in mapping]
        confidence = len(matched)/max(len(word), 1)
        exact_enough = confidence >= (.99 if len(word)<6 else .8) and overall >= .8
        start = chars[matched[0]]["start"] if matched else None
        end = chars[matched[-1]]["end"] if matched else None
        windows = data.get('speechWindows') or []
        acoustic = False
        if start is not None and windows:
            first = next((w for w in windows if w['end']>=start), None)
            last = next((w for w in reversed(windows) if w['start']<=end), None)
            if first and last:
                acoustic = bool(data.get('verifiedPhraseWindow')) or (start-first['start'] <= .8 and last['end']-end <= .8)
                if start-first['start'] <= 0.8: start = first['start']
                if last['end']-end <= 0.8: end = last['end']

        valid = False
        # The acoustic window is a candidate, never proof of the right dialogue.
        if len(lines) == 1 and windows:
            speech_start = max(0.0, float(windows[0]['start']))
            speech_end = min(duration, float(windows[-1]['end']))
            if speech_end > speech_start:
                start, end = speech_start, speech_end
                valid = bool(exact_enough and acoustic and speech_end-speech_start>=.12)
        else:
            valid = bool(exact_enough and acoustic and start is not None and end is not None and end-start >= .12 and start >= previous_end-.05 and end <= duration+.05)

        rows.append({"index": index, "role": (contract.get("roles") or [])[index] if index<len(contract.get("roles") or []) else "未标注角色",
                     "text": line, "start": round(max(0,start),3) if start is not None else None,
                     "end": round(min(duration,end),3) if end is not None else None,
                     "confidence": round(confidence,3), "confirmed": bool(valid),
                     "method": "matched" if valid else "manual_required"})
        if valid:
            previous_end = end
        cursor += len(word)
    note = data.get('recognitionNote', '')
    if rows and not all(r['confirmed'] for r in rows):
        fallback = ordered_fallback(contract, data, duration, wanted, recognized, mapping, chars)
        if fallback:
            rows = fallback
            note = '；'.join(filter(None, [note, '本地识别有个别字差异，已按分镜台词顺序与原声语段自动定位；请试听核对']))
    result = {"rows": rows, "transcript": ' '.join(str(s.get('text') or '') for s in data.get('transcription',[])),
              "recognitionNote": note,
              "status": "matched" if rows and all(r['confirmed'] for r in rows) else "needs_review"}
    if result['status'] == 'needs_review':
        reasons = []
        for row in rows:
            if row['confirmed']:
                continue
            if not chars:
                reason = '原视频未识别到可对照的对白，请检查原片是否有声音或台词。'
            elif row['start'] is None or row['end'] is None:
                reason = '识别结果未包含这句台词，不能自动猜测说话时间。'
            elif row['confidence'] < .8:
                reason = '只识别到部分台词，尚不能确认整句范围。'
            else:
                reason = '台词文字已找到，但发声范围或前后顺序仍不明确。'
            row['reviewReason'] = reason
            reasons.append(f"第{row['index']+1}句：{reason}")
        result['warning'] = '；'.join(reasons)
    return result


def source_ranges(contract, timeline, audio_duration):
    if len(timeline or []) != len(contract.get('lines') or []):
        raise ValueError("这份配音缺少逐句位置，请重新生成本镜配音")
    result=[]
    previous=0
    for index,item in enumerate(timeline):
        if normalize_words(item.get('text')) != normalize_words(contract['lines'][index]):
            raise ValueError("配音文件与分镜台词不同，请重新生成")
        role = (contract.get('roles') or ['']*len(timeline))[index] or '未标注角色'
        if str(item.get('role') or '未标注角色') != role:
            raise ValueError("配音的角色顺序与分镜不同，请重新生成")
        start, end = float(item['start']), float(item['start'])+float(item['duration'])
        if not all(math.isfinite(v) for v in (start,end)) or start<previous-.01 or end<=start or end>audio_duration+.05:
            raise ValueError("配音逐句位置无效，请重新生成")
        result.append((max(0,start),min(audio_duration,end)));previous=end
    return result


def attach_pause_plan(contract, rows, target_data, source_data, timeline):
    """Keep pauses between speech bursts, e.g. 'I ... I wasn't at work?'."""
    wanted=''.join(normalize_words(v) for v in contract['lines'])
    def mapped(data):
        chars=timed_characters(data);recognized=''.join(c['char'] for c in chars);result={}
        for block in difflib.SequenceMatcher(None,wanted,recognized,autojunk=False).get_matching_blocks():
            result.update({block.a+i:chars[block.b+i] for i in range(block.size)})
        return result
    target,source=mapped(target_data),mapped(source_data)
    recognized_source=''.join(normalize_words(s.get('text') or '') for s in source_data.get('transcription',[]))
    source_matches=difflib.SequenceMatcher(None,wanted,recognized_source,autojunk=False).ratio() >= .85
    source_characters=timed_characters(source_data)
    cursor=0
    for i,row in enumerate(rows):
        count=len(normalize_words(row['text']))
        windows=[w for w in target_data.get('speechWindows',[]) if row['start'] is not None and row['end'] is not None and min(row['end'],w['end'])-max(row['start'],w['start'])>.08]
        if len(windows)>1 and row.get('confirmed'):
            # Whisper may put the second "I" on the preceding VAD boundary,
            # or recognize a final homophone (吗/嘛). When both recordings have
            # the same ordered speech bursts and the words mostly agree, their
            # actual acoustic windows are safer than those token boundaries.
            left=float(timeline[i]['start']);right=left+float(timeline[i]['duration'])
            recognized_line=''.join(c['char'] for c in source_characters if left-.02<=c['start']<right+.02)
            line_matches=difflib.SequenceMatcher(None,normalize_words(row['text']),recognized_line,autojunk=False).ratio() >= .85
            source_windows=[w for w in source_data.get('speechWindows',[])
                            if min(right,w['end'])-max(left,w['start'])>.08]
            if source_matches and line_matches and len(source_windows)==len(windows):
                pieces=[{'sourceStart':max(left,s['start']),'sourceEnd':min(right,s['end']),
                         'start':max(row['start'],t['start']),'end':min(row['end'],t['end'])}
                        for s,t in zip(source_windows,windows)]
                if all(p['sourceEnd']>p['sourceStart'] and p['end']>p['start'] for p in pieces):
                    row.update({'pieces':pieces,'planStart':row['start'],'planEnd':row['end'], 'pausePlan':'speech-windows'})
                    cursor+=count
                    continue
            groups={}
            for index in range(cursor,cursor+count):
                if index not in target:continue
                at=target[index]['start']
                slot=min(range(len(windows)),key=lambda n:max(windows[n]['start']-at,at-windows[n]['end'],0))
                groups.setdefault(slot,[]).append(index)
            pieces=[]
            group_items=list(groups.items())
            allowed_boundaries={len(normalize_words(row['text'][:match.start()])) for match in re.finditer(r'[！？!?。；;…]+|\.{2,}',row['text'])}
            for group_index,(slot,indices) in enumerate(group_items):
                if indices[0] not in source or indices[-1] not in source:
                    pieces=[];break
                if group_index and indices[0]-cursor not in allowed_boundaries:
                    # Never create a two-second silence halfway through "don't
                    # let that boy..." because one non-speech sound was detected.
                    pieces=[];break
                left=source[indices[0]]['start'] if pieces else float(timeline[i]['start'])
                next_index=indices[-1]+1
                right=source[next_index]['start'] if group_index<len(group_items)-1 and next_index<cursor+count and next_index in source else float(timeline[i]['start'])+float(timeline[i]['duration'])
                source_windows=source_data.get('speechWindows') or []
                if source_windows:
                    def window_at(at):
                        return min(range(len(source_windows)),key=lambda n:max(source_windows[n]['start']-at,at-source_windows[n]['end'],0))
                    first_window=window_at(source[indices[0]]['start'])
                    last_window=window_at(source[indices[-1]]['start'])
                    previous_index=indices[0]-1
                    if previous_index<cursor or previous_index not in source or window_at(source[previous_index]['start'])!=first_window:
                        left=source_windows[first_window]['start']
                    if group_index<len(group_items)-1 and (next_index>=cursor+count or next_index not in source or window_at(source[next_index]['start'])!=last_window):
                        right=source_windows[last_window]['end']
                left=max(float(timeline[i]['start']),left)
                right=min(float(timeline[i]['start'])+float(timeline[i]['duration']),right)
                pieces.append({'sourceStart':left,'sourceEnd':right,'start':max(row['start'],windows[slot]['start']),'end':min(row['end'],windows[slot]['end'])})
            if len(pieces)>1 and all(p['sourceEnd']>p['sourceStart'] for p in pieces):
                row.update({'pieces':pieces,'planStart':row['start'],'planEnd':row['end']})
            else:
                # Matching the whole utterance already established its location.
                # Failure to map optional sub-phrase pauses is not evidence that
                # the utterance was absent. Render the complete take in this
                # confirmed window, keeping its own natural pauses.
                for key in ('pieces','planStart','planEnd'):
                    row.pop(key,None)
                row['pausePlan']='whole-line'
                row['pausePlanWarning']='句内停顿细分未通过，已保留整句定位，沿用配音自身的自然停顿。'
        cursor+=count


def validate_rows(contract, rows, duration):
    if len(rows or []) != len(contract.get('lines') or []):
        raise ValueError("请先定位原声每句台词")
    previous = 0
    for i, row in enumerate(rows):
        role = (contract.get('roles') or ['']*len(rows))[i] or '未标注角色'
        if normalize_words(row.get('text')) != normalize_words(contract['lines'][i]) or (row.get('role') or '未标注角色') != role:
            raise ValueError("时间表台词或角色已变动，请重新定位")
        if row.get('start') is None or row.get('end') is None:
            raise ValueError(f"请填写第 {i+1} 句的开始和结束时间")
        try:
            start, end = float(row.get('start', 0)), float(row.get('end', 0))
        except (ValueError, TypeError, KeyError):
            raise ValueError(f"请填写第 {i+1} 句的开始和结束时间")
        if not all(math.isfinite(v) for v in (start, end)) or end-start < .12 or start < 0 or end > duration+.02:
            raise ValueError(f"第 {i+1} 句时间无效，结束时间必须大于开始时间")
        if start < previous - 0.05:
            raise ValueError(f'第 {i+1} 句与上一句的时间重叠，请重新定位')
        row['confirmed'] = True
        previous = end


def read_pcm(ffmpeg, media, output):
    command([ffmpeg,"-v","error","-nostdin","-y","-i",media,"-vn","-ac","1","-ar","24000","-c:a","pcm_s16le",output])
    with wave.open(str(output),'rb') as wav:
        samples=array.array('h',wav.readframes(wav.getnframes()))
    return samples


def normalize_speech_pcm(pcm, rate=24000, target_dbfs=-18.0):
    """One constant gain per utterance; ignore pauses and preserve every sample.

    Peak headroom prevents clipping without a compressor or a change of timbre.
    Low-level silence is left alone rather than amplified into noise.
    """
    samples = array.array('h', pcm)
    peak = max((abs(v) for v in samples), default=0)
    block = max(1, round(rate * .02))
    energies = [sum(v*v for v in samples[i:i+block])/len(samples[i:i+block])
                for i in range(0,len(samples),block)]
    strongest = max(energies, default=0)
    active = [energy for energy in energies if energy >= max(16.0, strongest*.0064)]
    if peak < 8 or not active:
        return bytes(pcm), {'version':1, 'gainDb':0.0, 'status':'silence'}
    rms = math.sqrt(sum(active)/len(active))
    target = 32768 * 10**(target_dbfs/20)
    ceiling = 32767 * 10**(-1.5/20)
    gain = min(target/max(rms,1), ceiling/peak, 10**(24/20))
    gain = max(10**(-24/20), gain)
    normalized = array.array('h', (round(v*gain) for v in samples))
    return normalized.tobytes(), {'version':1, 'status':'normalized', 'gainDb':round(20*math.log10(gain),2),
        'voicedRmsBeforeDbfs':round(20*math.log10(rms/32768),2),
        'voicedRmsAfterDbfs':round(20*math.log10(rms*gain/32768),2),
        'peakAfterDbfs':round(20*math.log10(peak*gain/32768),2)}


def speech_edges(samples, start, end, rate=24000):
    """Trim only leading/trailing quiet in clean TTS, retaining internal pauses."""
    left,right=int(start*rate),min(len(samples),int(end*rate))
    block=max(1,int(rate*.01));peak=max((abs(v) for v in samples[left:right]),default=0)
    threshold=max(45,peak*.012)
    active=[i for i in range(left,right,block) if max((abs(v) for v in samples[i:min(i+block,right)]),default=0)>threshold]
    if not active:raise ValueError("配音片段没有可用人声，请重新生成")
    return max(left,active[0]-int(.025*rate))/rate,min(right,active[-1]+block+int(.04*rate))/rate


MAX_DUBBING_SPEED=1.18
MIN_DUBBING_PAUSE=0.35
PAUSE_DETECT=0.12

def compact_pauses(pcm,rate=24000,room=None):
    """Shorten TTS pauses to make a take fit before speeding up the voice.

    Long pauses after '。' can double a take's length while the words themselves
    are fine. Reduce the longest pauses first, never below target_min_pause, and
    only as much as the available room requires.
    """
    samples=array.array('h',pcm)
    if len(samples)<2: return samples
    block=max(1,int(rate*.01))
    peaks=[max((abs(v) for v in samples[i:i+block]),default=0) for i in range(0,len(samples),block)]
    threshold=max(45,max(peaks,default=0)*.012)
    runs=[]; i=0
    while i<len(peaks):
        if peaks[i]<=threshold:
            j=i
            while j<len(peaks) and peaks[j]<=threshold: j+=1
            if (j-i)*block>=PAUSE_DETECT*rate: runs.append([i*block,min(len(samples),j*block)])
            i=j
        else: i+=1
    if not runs: return samples
    needed=max(0.0,len(samples)/rate-float(room)) if room is not None else 0.0
    if needed<=0 and room is not None: return samples
    target_min_pause = max(0.15, MIN_DUBBING_PAUSE - 0.15) if (room is not None and needed > 0.35) else MIN_DUBBING_PAUSE
    reducible=[[run,(run[1]-run[0])/rate-target_min_pause] for run in runs]
    reducible=[item for item in reducible if item[1]>1e-6]
    savings=0.0
    for item in sorted(reducible,key=lambda item:-item[1]):
        item[1]=max(0.0,min(item[1],needed-savings)) if room is not None else item[1]
        savings+=item[1]
        if room is not None and savings>=needed-1e-6: break
    keeps={}
    for run,reduction in reducible:
        length=(run[1]-run[0])/rate
        keeps[(run[0],run[1])]=max(target_min_pause,length-reduction) if room is not None else target_min_pause
    out=[]; cursor=0
    for run in runs:
        length=(run[1]-run[0])/rate
        keep=int(round(keeps.get((run[0],run[1]),length)*rate))
        out.append(samples[cursor:run[0]+keep])
        cursor=run[1]
    out.append(samples[cursor:])
    return array.array('h',b''.join(part.tobytes() for part in out if part))


def speech_placement(speech_len,start,deadline,role=""):
    """Fit the whole utterance into [start, deadline]; never cut the tail."""
    room=max(0.05,float(deadline)-float(start))
    if speech_len<=room:
        return 1.0,speech_len
    speed=speech_len/room
    is_vo = str(role or '').strip() in ('旁白', '画外音', '解说', '解说词', '内心独白', 'vo', 'os', 'VO', 'OS')
    max_speed = 1.45 if is_vo else 1.30
    if speed>max_speed:
        if speed <= 1.55:
            return speed, room
        raise ValueError(f'本句配音时长约 {speech_len:.1f} 秒，画面预留窗口仅 {room:.1f} 秒（即使加速到 {max_speed:.2f} 倍仍放不下）。建议适当精简台词，或在分镜设置中增加视频时长。')
    return speed,room


def render(ffmpeg, video, audio, contract, timeline, rows, output, work):
    duration=media_duration(ffmpeg,video)
    validate_rows(contract,rows,duration)
    samples=read_pcm(ffmpeg,audio,Path(work)/'source.wav')
    ranges=source_ranges(contract,timeline,len(samples)/24000)
    # Also level existing takes, so correcting their volume needs no TTS call.
    for left,right in ranges:
        a,b=int(left*24000),min(len(samples),int(right*24000))
        pcm,_=normalize_speech_pcm(samples[a:b].tobytes())
        samples[a:b]=array.array('h',pcm)
    audio=Path(work)/'leveled-speech.wav'
    with wave.open(str(audio),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(samples.tobytes())
    track=array.array('h',[0])*(int(math.ceil(duration*24000))+2)
    row_limits=[min(duration,float(rows[i+1]['start'])-.04 if i+1<len(rows) else duration) for i in range(len(rows))]
    for i,(row,(left,right)) in enumerate(zip(rows,ranges)):
        pieces=row.get('pieces') or [{'sourceStart':left,'sourceEnd':right,'start':row['start'],'end':row['end']}]
        scale=(float(row['end'])-float(row['start']))/max(.01,float(row.get('planEnd',row['end']))-float(row.get('planStart',row['start'])))
        row_prev_limit = float(rows[i-1]['end']) + 0.04 if i > 0 else 0.06
        current_piece_left = row_prev_limit
        previous_source = left
        for j,part in enumerate(pieces):
            a,b=float(part['sourceStart']),float(part['sourceEnd'])
            start=float(row['start'])+(float(part['start'])-float(row.get('planStart',row['start'])))*scale
            end=float(row['start'])+(float(part['end'])-float(row.get('planStart',row['start'])))*scale
            if not all(math.isfinite(v) for v in (a,b,start,end)) or a<previous_source-.01 or b>right+.03 or b<=a or end>float(row['end'])+.02 or end<=start:
                raise ValueError('句内停顿位置无效，请重新定位原声')
            previous_source = b
            a,b=speech_edges(samples,a,b)
            # The window is a deadline, not a length the voice must fill. A
            # longer take may use the following pause, and if there is no pause
            # it is sped up just enough to be heard to the last syllable.
            if j+1<len(pieces):
                deadline=float(row['start'])+(float(pieces[j+1]['start'])-float(row.get('planStart',row['start'])))*scale-.04
            else:
                deadline=row_limits[i]
            take_dur = (b - a)
            available_room = deadline - start
            if take_dur > available_room and start > current_piece_left:
                borrow = min(start - current_piece_left, take_dur - available_room)
                start -= borrow
            current_piece_left = end
            take=compact_pauses(samples[int(round(a*24000)):int(round(b*24000))],24000,deadline-start)
            take_file=Path(work)/f'line-{i}-{j}-take.wav'
            with wave.open(str(take_file),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(take.tobytes())
            speed,length=speech_placement(len(take)/24000,start,deadline,role=row.get('role', ''))
            piece=Path(work)/f'line-{i}-{j}.wav'
            command([ffmpeg,'-v','error','-nostdin','-y','-i',str(take_file),'-af',
                     f'atempo={speed:.8f},apad=whole_dur={length:.6f},atrim=duration={length:.6f},afade=t=in:d=0.006,afade=t=out:st={max(0,length-.008):.6f}:d=0.008',
                     '-ac','1','-ar','24000','-c:a','pcm_s16le',piece])
            with wave.open(str(piece),'rb') as wav:chunk=array.array('h',wav.readframes(wav.getnframes()))
            offset=int(round(start*24000))
            if offset+len(chunk)>len(track):
                chunk = chunk[:max(0, len(track) - offset)]
            track[offset:offset+len(chunk)]=chunk
    aligned=Path(work)/'aligned.wav'
    with wave.open(str(aligned),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(track.tobytes())
    mix_track(ffmpeg,video,aligned,rows,duration,output,work)
    return duration


def render_converted(ffmpeg, video, audio, contract, rows, output):
    duration=media_duration(ffmpeg,video)
    validate_rows(contract,rows,duration)
    if abs(media_duration(ffmpeg,audio)-duration)>.1:
        raise ValueError('换音色配音的时间轴与原视频不同，请重新生成')
    mix_track(ffmpeg,video,audio,rows,duration,output,Path(output).parent)
    return duration


def mix_track(ffmpeg, video, audio, rows, duration, output, work):
    windows='+'.join(f'between(t,{float(r["start"]):.6f},{float(r["end"]):.6f})' for r in rows)
    # Preserve original ambience outside the replaced speech windows. No original
    # speech is mixed over the new voices in those windows.
    original_audio=Path(work)/'original.wav'
    try:
        command([ffmpeg,'-v','error','-nostdin','-y','-i',video,'-vn','-ac','1','-ar','24000',original_audio])
        filters=f"[0:a:0]volume=0:enable='{windows}'[base];[base][1:a:0]amix=inputs=2:duration=longest:normalize=0[mix]"
        args=['-filter_complex',filters,'-map','0:v:0','-map','[mix]']
    except ValueError:
        args=['-map','0:v:0','-map','1:a:0']
    command([ffmpeg,'-v','error','-nostdin','-y','-i',video,'-i',audio,*args,'-c:v','copy','-c:a','aac','-t',f'{duration:.6f}',output])
