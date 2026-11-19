"""Universal document format adapter for CDTV.
Supports .md, .markdown, .txt, .docx, .doc, .pdf, .xlsx, .xls, .csv, .json, and folder batch imports.
Provides intelligent auto-adaptation for screenplay, novel chapters, and loosely structured shot lists.
"""
import csv
import io
import json
import os
import re
from pathlib import Path
from typing import Any


def extract_text_from_file_bytes(file_name: str, content: bytes) -> str:
    """Extract readable Markdown or plain text from various document formats."""
    ext = os.path.splitext(file_name)[1].lower()

    if ext in {'.docx', '.doc'}:
        try:
            import docx
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            doc = docx.Document(io.BytesIO(content))
            lines = []
            for element in doc.element.body:
                if element.tag.endswith('p'):
                    p = Paragraph(element, doc)
                    t = p.text.strip()
                    if t:
                        lines.append(t)
                elif element.tag.endswith('tbl'):
                    tbl = Table(element, doc)
                    for row in tbl.rows:
                        cells = [c.text.strip().replace('\n', ' ') for c in row.cells]
                        if any(cells):
                            lines.append('| ' + ' | '.join(cells) + ' |')
            return '\n\n'.join(lines)
        except Exception as e:
            # Fallback to UTF-8 decoding if python-docx fails
            try:
                return content.decode('utf-8', errors='ignore')
            except Exception:
                raise ValueError(f"DOCX 文档解析失败: {e}")

    elif ext == '.pdf':
        try:
            import fitz  # pymupdf

            doc = fitz.open(stream=content, filetype='pdf')
            pages_text = []
            for page in doc:
                text = page.get_text('text')
                if text.strip():
                    pages_text.append(text.strip())
            return '\n\n'.join(pages_text)
        except Exception as e:
            raise ValueError(f"PDF 文档解析失败: {e}")

    elif ext in {'.xlsx', '.xls'}:
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            lines = []
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                rows = list(sheet.iter_rows(values_only=True))
                if not rows:
                    continue
                lines.append(f"## {sheet_name}")
                for row in rows:
                    cells = [str(c).strip().replace('\n', ' ') if c is not None else '' for c in row]
                    if any(cells):
                        lines.append('| ' + ' | '.join(cells) + ' |')
            return '\n\n'.join(lines)
        except Exception as e:
            raise ValueError(f"Excel 表格解析失败: {e}")

    elif ext == '.csv':
        try:
            raw_text = None
            for enc in ('utf-8', 'gb18030', 'gbk', 'utf-16'):
                try:
                    raw_text = content.decode(enc)
                    break
                except Exception:
                    continue
            if raw_text is None:
                raw_text = content.decode('utf-8', errors='ignore')

            reader = csv.reader(io.StringIO(raw_text))
            lines = []
            for row in reader:
                cells = [c.strip().replace('\n', ' ') for c in row]
                if any(cells):
                    lines.append('| ' + ' | '.join(cells) + ' |')
            return '\n'.join(lines)
        except Exception as e:
            raise ValueError(f"CSV 文档解析失败: {e}")

    elif ext == '.json':
        try:
            data = json.loads(content.decode('utf-8'))
            if isinstance(data, dict):
                # If it already matches CDTV rawText or episodes format
                if data.get('rawText'):
                    return data['rawText']
                if data.get('episodes'):
                    # Convert to markdown shots
                    out = []
                    for ep in data['episodes']:
                        out.append(f"# {ep.get('title', '第1集')}\n")
                        for s in ep.get('shots', []):
                            out.append(f"### 镜头 {s.get('number', 1)}：{s.get('title', '分镜')}")
                            if s.get('duration'):
                                out.append(f"【时长】: {s['duration']}秒")
                            if s.get('scene'):
                                out.append(f"【场景】: {s['scene']}")
                            if s.get('core'):
                                out.append(f"【画面描述】: {s['core']}")
                            if s.get('dialogue'):
                                out.append(f"【对白】: {s['dialogue']}")
                            if s.get('narration'):
                                out.append(f"【旁白】: {s['narration']}")
                            if s.get('sound'):
                                out.append(f"【环境音】: {s['sound']}")
                            if s.get('join'):
                                out.append(f"【转场】: {s['join']}")
                            if s.get('constraints'):
                                out.append(f"【拍摄约束】: {s['constraints']}")
                            out.append("")
                    return '\n'.join(out)
                return json.dumps(data, ensure_ascii=False, indent=2)
            elif isinstance(data, list):
                return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception as e:
            raise ValueError(f"JSON 文档解析失败: {e}")

    # Plain text / Markdown / HTML / other text files
    for enc in ('utf-8', 'gb18030', 'gbk', 'utf-16le', 'utf-16be'):
        try:
            return content.decode(enc)
        except Exception:
            continue
    return content.decode('utf-8', errors='ignore')


def smart_adapt_script_to_cdtv_format(raw_text: str, doc_name: str = "分镜文档") -> str:
    """Intelligently detects whether the text needs auto-adaptation into CDTV shots.
    If the document lacks standard '### 镜头' or '【镜X-X】' tags, this converts
    screenplay scenes, novel chapters, or table rows into compliant shots.
    """
    text = (raw_text or "").replace('\r\n', '\n').strip()
    if not text:
        return text

    # Check if text already has recognized shot headers
    has_shots = bool(re.search(
        r'^(?:#{1,6}\s*)?(?:镜头|分镜|分镜头|镜|【镜|\[镜|Shot|Cut)\s*[\d一二两三四五六七八九十]+',
        text,
        re.M | re.I
    ))
    if has_shots:
        return text

    lines = text.split('\n')
    preamble_lines = []
    body_lines = []
    tail_lines = []
    
    state = 'preamble'
    # Check if there is an explicit script body marker
    has_explicit_body = any(
        re.search(r'^(?:[一二三四五六七八九十0-9]+[、. ]|[#* ]+)?(?:分镜脚本|分镜头|正片分镜|分镜正文|剧本正文|分镜表)', l.strip())
        for l in lines
    )
    if not has_explicit_body:
        state = 'body'

    for line in lines:
        l = line.strip()
        if state == 'preamble':
            if re.search(r'^(?:[一二三四五六七八九十0-9]+[、. ]|[#* ]+)?(?:分镜脚本|分镜头|正片分镜|分镜正文|剧本正文|分镜表)', l):
                state = 'body'
                continue
            preamble_lines.append(line)
        elif state == 'body':
            if re.search(r'^(?:[一二三四五六七八九十0-9]+[、. ]|[#* ]+)?(?:时长预算|AI制作路径|古今用词|文旅赛|附录|总结|说明|参考|注意事项)', l):
                state = 'tail'
                tail_lines.append(line)
                continue
            body_lines.append(line)
        else:
            tail_lines.append(line)

    if not body_lines:
        body_lines = lines
        preamble_lines = []
        tail_lines = []

    # Adapt body lines into shots
    adapted_shots = []
    current_section = "正片"
    current_scene = "默认场景"
    shot_index = 1

    # Chunk body into scene / paragraph blocks
    blocks = []
    current_block = []

    for line in body_lines:
        l = line.strip()
        if not l:
            if current_block:
                blocks.append(current_block)
                current_block = []
            continue

        # Check section break (e.g. "序·...", "第一节...", "第1场...")
        sec_m = re.match(r'^(?:[#* ]+)?(?:序[·. ]|第[一二两三四五六七八九十0-9]+[节场幕集]|[0-9一二两三四五六七八九十]+[、. ])\s*(.*)$', l)
        if sec_m:
            if current_block:
                blocks.append(current_block)
                current_block = []
            blocks.append([line])
            continue

        current_block.append(line)

    if current_block:
        blocks.append(current_block)

    for block in blocks:
        block_text = '\n'.join(block).strip()
        if not block_text:
            continue

        # Check if this block is a section header
        first_line = block[0].strip()
        sec_m = re.match(r'^(?:[#* ]+)?(序[·. ].*|第[一二两三四五六七八九十0-9]+[节场幕集].*|[0-9一二两三四五六七八九十]+[、. ].*)$', first_line)
        if sec_m and len(block) == 1:
            current_section = sec_m.group(1).replace('#', '').strip()
            continue

        # Extract shot attributes from block
        shot_title = f"{current_section}·镜头{shot_index:02d}"
        core_lines = []
        dialogue_lines = []
        narration_lines = []
        sound_lines = []
        join_lines = []
        camera_desc = ""
        duration = 8

        # Check for duration clues
        dur_m = re.search(r'(\d+)\s*秒', block_text)
        if dur_m:
            duration = int(dur_m.group(1))

        # Check for camera movement clues
        cam_m = re.search(r'(特写|大远景|远景|全景|中景|近景|俯瞰|仰拍|仰视|前推|推近|拉远|摇镜|跟拍|升空|俯冲)', block_text)
        if cam_m:
            camera_desc = cam_m.group(1)
            shot_title = f"{camera_desc}·{current_section}·镜头{shot_index:02d}"

        for b_line in block:
            bl = b_line.strip()
            # Dialogue
            diag_m = re.match(r'^(?:对白|台词|现场对白)?\s*([^\s:：]{1,10})\s*[:：]\s*["“](.*?)["”]?$', bl)
            if diag_m and not re.match(r'^(?:画面|运镜|场景|时间|时长|音效|环境|转场)', diag_m.group(1)):
                speaker = diag_m.group(1)
                content_text = diag_m.group(2)
                dialogue_lines.append(f'{speaker}："{content_text}"')
                continue

            # Narration / Voiceover
            narr_m = re.match(r'^(?:旁白|画外音|解说词|解说)\s*[:：]\s*(.*)$', bl)
            if narr_m:
                narration_lines.append(narr_m.group(1))
                continue

            # Sound / BGM
            sound_m = re.match(r'^(?:环境音|音效|声音|BGM|背景音乐)\s*[:：]\s*(.*)$', bl)
            if sound_m:
                sound_lines.append(sound_m.group(1))
                continue

            # Transition
            join_m = re.match(r'^(?:转场|衔接|接点)\s*[:：]\s*(.*)$', bl)
            if join_m:
                join_lines.append(join_m.group(1))
                continue

            # Scene
            scene_m = re.match(r'^(?:场景|时地|地点|环境)\s*[:：]\s*(.*)$', bl)
            if scene_m:
                current_scene = scene_m.group(1)
                continue

            core_lines.append(bl)

        shot_block = [
            f"### 镜头 {shot_index:02d}：{shot_title}",
            f"【时长】: {duration}秒",
            f"【场景】: {current_scene}",
            f"【画面描述】: {' '.join(core_lines) if core_lines else '画面动作演进'}",
        ]
        if camera_desc:
            shot_block.append(f"【景别与运镜】: {camera_desc}")
        if dialogue_lines:
            shot_block.append(f"【对白】: {' '.join(dialogue_lines)}")
        if narration_lines:
            shot_block.append(f"【旁白】: {' '.join(narration_lines)}")
        if sound_lines:
            shot_block.append(f"【环境音】: {' '.join(sound_lines)}")
        if join_lines:
            shot_block.append(f"【转场】: {' '.join(join_lines)}")

        adapted_shots.append('\n'.join(shot_block))
        shot_index += 1

    # Assemble final markdown
    res = []
    if preamble_lines:
        res.append('\n'.join(preamble_lines))
        res.append('')

    title = doc_name.replace('.md', '').replace('.txt', '').replace('.docx', '').replace('.pdf', '')
    res.append(f"# 第1集：{title}（智能适配分镜）\n")
    res.append('\n\n'.join(adapted_shots))

    if tail_lines:
        res.append('\n')
        res.append('\n'.join(tail_lines))

    return '\n'.join(res)
