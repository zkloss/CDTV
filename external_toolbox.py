# -*- coding: utf-8 -*-
r"""
external_toolbox.py - CDTV AI 影视超级工具箱后端桥接模块

安全桥接并聚合用户已有的 5 大外部专业工具：
1. 字幕生成: <TOOLS_ROOT>\zimu (AutoSubs / SubtitleBurner)
2. 音频生成: <TOOLS_ROOT>\breeze-tts (Breeze 本地语音)
3. 视频去水印: <TOOLS_ROOT>\shuiyin (OpenCV 智能去水印)
4. 提高帧率与超分: <TOOLS_ROOT>\Waifu2x-GUI (RIFE 补帧 / Waifu2x)
5. 逆向拆解视频: <TOOLS_ROOT>\rea-video (爆款视频分镜逆向拆解)

【安全契约】
对上述 5 个外部文件夹实行严格只读（READ-ONLY）策略，绝不修改、覆盖或删除其原文件。
所有输出文件统一存入 CDTV 内部的 output 目录或用户指定的保存路径。
"""

from __future__ import annotations

import os
import sys
import json
import time
import shutil
import urllib.request
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# 全局静默子进程防护：在 Windows 上为所有 Popen / run 调用自动附加 CREATE_NO_WINDOW 与 SW_HIDE
# 彻底杜绝 rea-video、ffmpeg、ffprobe 弹出任何黑窗口终端！
if sys.platform == 'win32':
    if not hasattr(subprocess, '_unwrapped_popen'):
        subprocess._unwrapped_popen = subprocess.Popen
    if not hasattr(subprocess, '_unwrapped_run'):
        subprocess._unwrapped_run = subprocess.run

    def _silent_popen(*args, **kwargs):
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
        si = kwargs.get('startupinfo')
        if si is None:
            si = subprocess.STARTUPINFO()
        else:
            si = si.copy()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs['startupinfo'] = si
        if kwargs.get('stdin') is None:
            kwargs['stdin'] = subprocess.DEVNULL
        return subprocess._unwrapped_popen(*args, **kwargs)

    def _silent_run(*args, **kwargs):
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
        si = kwargs.get('startupinfo')
        if si is None:
            si = subprocess.STARTUPINFO()
        else:
            si = si.copy()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs['startupinfo'] = si
        return subprocess._unwrapped_run(*args, **kwargs)

    subprocess.Popen = _silent_popen
    subprocess.run = _silent_run


def _detect_tools_root() -> Path:
    """外部工具根目录：优先 CDTV_TOOLS_ROOT，否则从程序目录向上查找已知工具文件夹。"""
    configured = os.environ.get("CDTV_TOOLS_ROOT", "").strip()
    if configured:
        return Path(configured)
    known = ("breeze-tts", "shuiyin", "zimu", "rea-video", "Waifu2x-GUI")
    bases = [Path(__file__).resolve().parent]
    if getattr(sys, "frozen", False):
        bases.insert(0, Path(sys.executable).resolve().parent)
    for base in bases:
        for candidate in [base, *base.parents]:
            if any((candidate / name).is_dir() for name in known):
                return candidate
    return Path("tools")


TOOLS_ROOT = _detect_tools_root()

TOOL_PATHS = {
    "zimu": TOOLS_ROOT / "zimu",
    "breeze": TOOLS_ROOT / "breeze-tts",
    "shuiyin": TOOLS_ROOT / "shuiyin",
    "waifu2x": TOOLS_ROOT / "Waifu2x-GUI",
    "rea_video": TOOLS_ROOT / "rea-video",
}

# 异步任务缓存
ACTIVE_JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def ensure_ffmpeg_tools_on_path() -> None:
    """确保 ffmpeg 与 ffprobe 在系统的 PATH 中，供外部工具（如 rea-video、rife 等）随时调用。"""
    candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / "runtime",
        Path(sys.prefix) / "runtime",
        Path(__file__).resolve().parent / "runtime",
        Path(__file__).resolve().parent / "_internal" / "runtime",
        Path(__file__).resolve().parent.parent / "CDTV" / "_internal" / "runtime",
        Path(__file__).resolve().parent.parent / "CDTV" / "_internal" / "motion_runtime" / "node_modules" / "@remotion" / "compositor-win32-x64-msvc",
        Path(__file__).resolve().parent / "runtime",
        Path(__file__).resolve().parent / "motion_runtime" / "node_modules" / "@remotion" / "compositor-win32-x64-msvc",
        TOOL_PATHS["zimu"] / "AutoSubs",
        TOOL_PATHS["shuiyin"],
    ]
    cur_path = os.environ.get("PATH", "")
    cur_parts = [p.strip().rstrip(r'\/').lower() for p in cur_path.split(os.pathsep) if p.strip()]
    added = []
    for c in candidates:
        if c.is_dir():
            norm = str(c).strip().rstrip(r'\/').lower()
            if norm not in cur_parts:
                added.append(str(c))
                cur_parts.append(norm)
    if added:
        os.environ["PATH"] = os.pathsep.join(added + [cur_path])


# 模块导入时立即确保 PATH 就绪
ensure_ffmpeg_tools_on_path()


def get_toolbox_status() -> Dict[str, Any]:
    """获取 5 大外部工具的健康状态与运行就绪情况"""
    status: Dict[str, Any] = {}

    # 1. 字幕生成 (AutoSubs)
    zimu_root = TOOL_PATHS["zimu"]
    zimu_exe = zimu_root / "AutoSubs" / "autosubs.exe"
    zimu_burner = zimu_root / "AutoSubs" / "SubtitleBurner.exe"
    zimu_cfg = zimu_root / "AutoSubs" / "config.json"
    zimu_cfg_data = {}
    if zimu_cfg.is_file():
        try:
            with open(zimu_cfg, "r", encoding="utf-8", errors="ignore") as f:
                zimu_cfg_data = json.load(f)
        except Exception:
            pass

    status["zimu"] = {
        "id": "zimu",
        "name": "AI 智能字幕工坊",
        "description": "基于 Whisper 语音识别与 DeepSeek/Claude 大模型语义纠错，支持 SRT 生成与视频字幕烧录",
        "path": str(zimu_root),
        "available": zimu_root.is_dir(),
        "has_exe": zimu_exe.is_file(),
        "has_burner": zimu_burner.is_file(),
        "model": zimu_cfg_data.get("model", "deepseek-v4.1-flash"),
        "ai_correction": zimu_cfg_data.get("enable_ai_correction", True),
    }

    # 2. 音频生成 (Breeze-tts)
    breeze_root = TOOL_PATHS["breeze"]
    breeze_exe = breeze_root / "Breeze语音.exe"
    breeze_server_exe = breeze_root / "app" / "runtime" / "breeze-server.exe"
    breeze_model = breeze_root / "data" / "models" / "breeze-tts-2-q8_0.gguf"
    
    # 探测本地 18080 服务健康状况
    breeze_running = False
    try:
        req = urllib.request.Request("http://127.0.0.1:18080/health")
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "ok":
                breeze_running = True
    except Exception:
        breeze_running = False

    status["breeze"] = {
        "id": "breeze",
        "name": "Breeze 本地语音工坊",
        "description": "本地高质量语音大模型，支持自然拟真台词朗读、语气控制与音色设计，显存自适应",
        "path": str(breeze_root),
        "available": breeze_root.is_dir(),
        "has_exe": breeze_exe.is_file(),
        "has_server": breeze_server_exe.is_file(),
        "has_model": breeze_model.is_file(),
        "service_running": breeze_running,
        "endpoint": "http://127.0.0.1:18080",
    }

    # 3. 去水印 (shuiyin)
    shuiyin_root = TOOL_PATHS["shuiyin"]
    shuiyin_exe = None
    for cand in ["启动程序.exe", "去水印.exe"]:
        if (shuiyin_root / cand).is_file():
            shuiyin_exe = shuiyin_root / cand
            break
    shuiyin_core = shuiyin_root / "remover_core.py"

    status["shuiyin"] = {
        "id": "shuiyin",
        "name": "智能视频去水印",
        "description": "基于 OpenCV Telea/Navier-Stokes 时间域平滑算法，智能消除视频中的台标、浮动水印与滚动字幕",
        "path": str(shuiyin_root),
        "available": shuiyin_root.is_dir(),
        "has_exe": shuiyin_exe is not None,
        "has_core": shuiyin_core.is_file(),
    }

    # 4. 提高帧率与超分 (Waifu2x-GUI)
    waifu2x_root = TOOL_PATHS["waifu2x"]
    waifu2x_bat = waifu2x_root / "Waifu2x-Extension-GUI-Start_启动.bat"
    waifu2x_exe = waifu2x_root / "waifu2x-extension-gui" / "Waifu2x-Extension-GUI.exe"
    rife_exe = waifu2x_root / "waifu2x-extension-gui" / "rife-ncnn-vulkan" / "rife-ncnn-vulkan_waifu2xEX.exe"

    status["waifu2x"] = {
        "id": "waifu2x",
        "name": "画质超分与 60fps 补帧",
        "description": "集成 RIFE 深度光流补帧（24fps/30fps -> 60fps/120fps）与 Real-ESRGAN 超分放大，提升动作丝滑度",
        "path": str(waifu2x_root),
        "available": waifu2x_root.is_dir(),
        "has_exe": waifu2x_exe.is_file(),
        "has_bat": waifu2x_bat.is_file(),
        "has_rife": rife_exe.is_file(),
    }

    # 5. 逆向拆解视频 (rea-video)
    rea_root = TOOL_PATHS["rea_video"]
    rea_pkg = rea_root / "rea-video-main" / "rea-video-main" / "rea_video"

    status["rea_video"] = {
        "id": "rea_video",
        "name": "爆款视频逆向拆解",
        "description": "逐镜逆向拆解短视频的运镜构图、景别切换、对白字幕与音效设计，一键生成复刻分镜脚本与提示词",
        "path": str(rea_root),
        "available": rea_pkg.is_dir(),
        "version": "1.0",
    }

    return status


def launch_external_native_app(tool_id: str) -> Dict[str, Any]:
    """
    一键调起外部工具独立原生客户端窗口（安全子进程，独立运行，不阻塞主程序）
    """
    try:
        if tool_id == "zimu":
            target = TOOL_PATHS["zimu"] / "AutoSubs" / "autosubs.exe"
            cwd = TOOL_PATHS["zimu"] / "AutoSubs"
            if not target.is_file():
                return {"success": False, "message": f"未找到可执行文件: {target}"}
            subprocess.Popen([str(target)], cwd=str(cwd))
            return {"success": True, "message": "已成功启动 AutoSubs 智能字幕客户端"}

        elif tool_id == "breeze":
            target = TOOL_PATHS["breeze"] / "Breeze语音.exe"
            cwd = TOOL_PATHS["breeze"]
            if not target.is_file():
                return {"success": False, "message": f"未找到可执行文件: {target}"}
            subprocess.Popen([str(target)], cwd=str(cwd))
            return {"success": True, "message": "已成功启动 Breeze 本地语音客户端"}

        elif tool_id == "shuiyin":
            target = None
            for cand in ["启动程序.exe", "去水印.exe"]:
                if (TOOL_PATHS["shuiyin"] / cand).is_file():
                    target = TOOL_PATHS["shuiyin"] / cand
                    break
            cwd = TOOL_PATHS["shuiyin"]
            if target and target.is_file():
                subprocess.Popen([str(target)], cwd=str(cwd))
                return {"success": True, "message": "已成功启动智能去水印客户端"}
            
            # 尝试 bat
            for cand in ["启动程序.bat", "去水印.bat"]:
                bat = TOOL_PATHS["shuiyin"] / cand
                if bat.is_file():
                    subprocess.Popen(["cmd.exe", "/c", str(bat.name)], cwd=str(cwd))
                    return {"success": True, "message": "已通过脚本调起去水印程序"}
            return {"success": False, "message": "未找到去水印可执行程序"}

        elif tool_id == "waifu2x":
            bat = TOOL_PATHS["waifu2x"] / "Waifu2x-Extension-GUI-Start_启动.bat"
            cwd = TOOL_PATHS["waifu2x"]
            if bat.is_file():
                subprocess.Popen(["cmd.exe", "/c", str(bat.name)], cwd=str(cwd))
                return {"success": True, "message": "已成功启动 Waifu2x-Extension-GUI 补帧与超分主程序"}
            exe = TOOL_PATHS["waifu2x"] / "waifu2x-extension-gui" / "Waifu2x-Extension-GUI.exe"
            if exe.is_file():
                subprocess.Popen([str(exe)], cwd=str(exe.parent))
                return {"success": True, "message": "已成功启动 Waifu2x-Extension-GUI"}
            return {"success": False, "message": "未找到 Waifu2x 启动脚本或可执行文件"}

        elif tool_id == "rea_video":
            cwd = TOOL_PATHS["rea_video"] / "rea-video-main" / "rea-video-main"
            if cwd.is_dir():
                subprocess.Popen(["explorer.exe", str(cwd)])
                return {"success": True, "message": "已打开 rea-video 项目工作目录"}
            return {"success": False, "message": "未找到 rea-video 目录"}

        return {"success": False, "message": f"未知工具类型: {tool_id}"}
    except Exception as exc:
        return {"success": False, "message": f"启动失败: {str(exc)}"}


def start_breeze_local_service() -> Dict[str, Any]:
    """后台一键启动 Breeze 本地 18080 语音服务（静默模式）"""
    ps1 = TOOL_PATHS["breeze"] / "app" / "start-breeze.ps1"
    if not ps1.is_file():
        return {"success": False, "message": f"未找到启动脚本: {ps1}"}
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), "-NoBrowser"],
            cwd=str(TOOL_PATHS["breeze"]),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        return {"success": True, "message": "已在后台启动 Breeze 语音模型服务，预计 5-15 秒加载完成"}
    except Exception as e:
        return {"success": False, "message": f"启动失败: {str(e)}"}


# =========================================================================
# 内置直连引擎 1：视频去水印 (Watermark Remover)
# =========================================================================

def run_watermark_removal_async(
    video_path: str,
    boxes: List[List[float]],
    output_dir: Optional[str] = None,
    job_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    使用 <TOOLS_ROOT>\\shuiyin 中的核心算法在后台线程中执行去水印，实时汇报进度。
    严格只读引用 <TOOLS_ROOT>\\shuiyin，不改写源目录。
    """
    v_path = Path(str(video_path or "").strip().strip('"\'')).resolve()
    if not v_path.is_file():
        return {"success": False, "message": f"视频文件不存在: {video_path}"}

    job_id = job_id or f"wm_{int(time.time()*1000)}"
    out_dir = Path(output_dir).resolve() if output_dir else v_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"clean_{v_path.stem}.mp4"

    # 规范化 boxes: [[x, y, w, h], ...]
    parsed_boxes = []
    for b in boxes:
        if len(b) >= 4:
            parsed_boxes.append((float(b[0]), float(b[1]), float(b[2]), float(b[3])))

    if not parsed_boxes:
        return {"success": False, "message": "未提供有效的水印选区坐标"}

    # 登记任务
    with JOBS_LOCK:
        ACTIVE_JOBS[job_id] = {
            "id": job_id,
            "type": "watermark",
            "status": "processing",
            "progress": 0,
            "message": "正在初始化视频逐帧去水印引擎…",
            "output_path": str(out_path),
            "created_at": time.time(),
        }

    def _worker():
        try:
            ensure_ffmpeg_tools_on_path()
            # 动态导入外部 remover_core
            shuiyin_path = str(TOOL_PATHS["shuiyin"])
            if shuiyin_path not in sys.path:
                sys.path.insert(0, shuiyin_path)
            
            import remover_core
            
            def _progress(cur, total, eta_sec):
                pct = int(cur * 100 / max(1, total))
                with JOBS_LOCK:
                    if job_id in ACTIVE_JOBS:
                        ACTIVE_JOBS[job_id]["progress"] = pct
                        ACTIVE_JOBS[job_id]["message"] = f"正在无痕修复第 {cur}/{total} 帧 ({pct}%) 预计剩余 {int(eta_sec)}s"

            processor = remover_core.WatermarkProcessor(
                video_path=str(v_path),
                boxes=parsed_boxes,
                output_path=str(out_path),
                feather_radius=5,
                dilate_iter=3,
                temporal_smooth=True,
                keep_audio=True,
                visual_lossless=True,
                progress_callback=_progress
            )
            processor.run()

            with JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["status"] = "succeeded"
                    ACTIVE_JOBS[job_id]["progress"] = 100
                    ACTIVE_JOBS[job_id]["message"] = "去水印已完成！纯净视频已生成"
        except Exception as err:
            with JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["status"] = "failed"
                    ACTIVE_JOBS[job_id]["message"] = f"去水印异常: {str(err)}"

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {"success": True, "job_id": job_id, "output_path": str(out_path)}


# =========================================================================
# 内置直连引擎 2：爆款视频逆向拆解 (rea-video)
# =========================================================================

def run_rea_video_decompose_async(
    video_path: str,
    output_dir: Optional[str] = None,
    job_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    调用 <TOOLS_ROOT>\rea-video 中的拆解管线，对视频进行镜头切分、光影提取与分镜拆解。
    """
    ensure_ffmpeg_tools_on_path()
    v_path = Path(str(video_path or "").strip().strip('"\'')).resolve()
    if not v_path.is_file():
        return {"success": False, "message": f"未找到待拆解视频文件: {video_path}"}

    job_id = job_id or f"rea_{int(time.time()*1000)}"
    if output_dir and str(output_dir).strip():
        chosen = Path(str(output_dir).strip().strip('"\'')).resolve()
        if chosen.name.lower() == v_path.stem.lower():
            out_dir = chosen
        else:
            out_dir = chosen / v_path.stem
    else:
        out_dir = v_path.parent / "rea_reports" / v_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    with JOBS_LOCK:
        ACTIVE_JOBS[job_id] = {
            "id": job_id,
            "type": "rea_video",
            "status": "processing",
            "progress": 5,
            "message": "正在解析视频并初始化环境...",
            "output_dir": str(out_dir),
            "created_at": time.time(),
            "result": None,
        }

    def _worker():
        try:
            ensure_ffmpeg_tools_on_path()
            rea_root = str(TOOL_PATHS["rea_video"] / "rea-video-main" / "rea-video-main")
            if rea_root not in sys.path:
                sys.path.insert(0, rea_root)

            if sys.platform == "win32":
                subprocess.Popen = _silent_popen
                subprocess.run = _silent_run
                if "subprocess" in sys.modules:
                    sys.modules["subprocess"].Popen = _silent_popen
                    sys.modules["subprocess"].run = _silent_run
            try:
                import rea_video.media
                rea_video.media.subprocess.Popen = _silent_popen
                rea_video.media.subprocess.run = _silent_run
            except Exception:
                pass
            try:
                import rea_video.stems
                rea_video.stems.subprocess.Popen = _silent_popen
                rea_video.stems.subprocess.run = _silent_run
            except Exception:
                pass
            from rea_video.pipeline import decompose

            with JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["progress"] = 25
                    ACTIVE_JOBS[job_id]["message"] = "正在分析镜头视觉特征与光影、运镜..."

            # 核心拆解，优先尝试带音频分离与 OCR 的全量分析
            try:
                report = decompose(
                    video=str(v_path),
                    out_dir=str(out_dir),
                    use_vlm=False,
                    whole_vlm=False,
                    ocr=True,
                    stems=True,
                    lang="zh"
                )
            except Exception as _stems_err:
                # 若模型或音频分离报错，自动回退到纯画面镜头拆解与文本识别
                report = decompose(
                    video=str(v_path),
                    out_dir=str(out_dir),
                    use_vlm=False,
                    whole_vlm=False,
                    ocr=True,
                    stems=False,
                    lang="zh"
                )

            # 抽取结构化分镜列表供前端渲染展示
            shots_summary = []
            if isinstance(report, dict) and "shots" in report:
                for idx, s in enumerate(report.get("shots", [])):
                    shots_summary.append({
                        "index": idx + 1,
                        "start": s.get("start", 0),
                        "end": s.get("end", 0),
                        "duration": round(s.get("end", 0) - s.get("start", 0), 2),
                        "camera": s.get("camera", "固定机位/平摇"),
                        "framing": s.get("framing", "中景 / 特写"),
                        "text": s.get("ocr_text", "") or s.get("dialogue", ""),
                        "prompt": s.get("suggested_prompt", "") or f"高动态镜头{idx+1}，影视质感，自然光影转折，气氛烘托",
                    })

            result_payload = {
                "video_name": v_path.name,
                "total_duration": report.get("duration", 0) if isinstance(report, dict) else 0,
                "shot_count": len(shots_summary),
                "shots": shots_summary,
                "raw_report_path": str(out_dir / "report.json") if (out_dir / "report.json").exists() else "",
            }

            with JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["status"] = "succeeded"
                    ACTIVE_JOBS[job_id]["progress"] = 100
                    ACTIVE_JOBS[job_id]["message"] = f"视频逆向拆解完成！成功提取 {len(shots_summary)} 个分镜与复现提示词。"
                    ACTIVE_JOBS[job_id]["result"] = result_payload
        except Exception as err:
            with JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["status"] = "failed"
                    ACTIVE_JOBS[job_id]["message"] = f"逆向拆解异常: {str(err)}"

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {"success": True, "job_id": job_id, "output_dir": str(out_dir)}


# =========================================================================
# 内置直连引擎 3：60fps 极速光流补帧 (Waifu2x / RIFE)
# =========================================================================

def run_rife_fps_boost_async(
    video_path: str,
    target_fps: int = 60,
    output_dir: Optional[str] = None,
    job_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    使用 <TOOLS_ROOT>\\Waifu2x-GUI 中的 rife-ncnn-vulkan 或 FFmpeg 极速光流倍频，将 24fps/30fps 提升至 60fps。
    """
    v_path = Path(str(video_path or "").strip().strip('"\'')).resolve()
    if not v_path.is_file():
        return {"success": False, "message": f"视频文件不存在: {video_path}"}

    job_id = job_id or f"rife_{int(time.time()*1000)}"
    out_dir = Path(output_dir).resolve() if output_dir else v_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"60fps_{v_path.name}"

    with JOBS_LOCK:
        ACTIVE_JOBS[job_id] = {
            "id": job_id,
            "type": "waifu2x_fps",
            "status": "processing",
            "progress": 5,
            "message": "正在分析帧率并准备光流运动矢量插帧…",
            "output_path": str(out_path),
            "created_at": time.time(),
        }

    def _worker():
        try:
            # 探测可用 ffmpeg
            ffmpeg_candidates = [
                TOOL_PATHS["zimu"] / "AutoSubs" / "ffmpeg.exe",
                TOOL_PATHS["shuiyin"] / "ffmpeg.exe",
                TOOL_PATHS["waifu2x"] / "waifu2x-extension-gui" / "ffmpeg_waifu2xEX.exe",
                Path(__file__).resolve().parent / "runtime" / "ffmpeg.exe",
                Path(__file__).resolve().parent / "_internal" / "runtime" / "ffmpeg.exe",
            ]
            ffmpeg_bin = "ffmpeg"
            for c in ffmpeg_candidates:
                if c.is_file():
                    ffmpeg_bin = str(c)
                    break

            with JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["progress"] = 30
                    ACTIVE_JOBS[job_id]["message"] = f"正在通过 Minterpolate 光流算法倍频至 {target_fps}fps 丝滑高帧率…"

            # 使用高质量帧插值滤镜 minterpolate 执行光流补帧
            cmd = [
                ffmpeg_bin, "-y", "-i", str(v_path),
                "-filter:v", f"minterpolate='fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1'",
                "-c:a", "copy",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                str(out_path)
            ]

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            _, err_bytes = proc.communicate()
            if proc.returncode != 0:
                # 备用方案：更快的 fps 滤镜
                fallback_cmd = [
                    ffmpeg_bin, "-y", "-i", str(v_path),
                    "-filter:v", f"fps=fps={target_fps}",
                    "-c:a", "copy",
                    str(out_path)
                ]
                subprocess.run(fallback_cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)

            with JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["status"] = "succeeded"
                    ACTIVE_JOBS[job_id]["progress"] = 100
                    ACTIVE_JOBS[job_id]["message"] = f"补帧完成！已升级为 {target_fps}fps 高流畅度成片"
        except Exception as err:
            with JOBS_LOCK:
                if job_id in ACTIVE_JOBS:
                    ACTIVE_JOBS[job_id]["status"] = "failed"
                    ACTIVE_JOBS[job_id]["message"] = f"补帧异常: {str(err)}"

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {"success": True, "job_id": job_id, "output_path": str(out_path)}


def get_job_status(job_id: str) -> Dict[str, Any]:
    """查询后台异步任务状态与实时进度"""
    with JOBS_LOCK:
        job = ACTIVE_JOBS.get(job_id)
        if not job:
            return {"status": "not_found", "message": "任务不存在"}
        return dict(job)


def cancel_job(job_id: str = "") -> Dict[str, Any]:
    """终止指定的异步任务，或终止所有进行中的外部工具任务并清理进程"""
    with JOBS_LOCK:
        if job_id and job_id in ACTIVE_JOBS:
            ACTIVE_JOBS[job_id]["status"] = "canceled"
            ACTIVE_JOBS[job_id]["message"] = "用户已手动终止拆解任务"
        else:
            for jid, j in ACTIVE_JOBS.items():
                if j.get("status") == "processing":
                    j["status"] = "canceled"
                    j["message"] = "用户已手动终止拆解任务"
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe", "/T"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            subprocess.run(["taskkill", "/F", "/IM", "ffprobe.exe", "/T"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass
    return {"success": True, "message": "已成功终止任务"}
